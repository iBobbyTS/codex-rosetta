from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from codex_rosetta.gateway.tool_history_translation import ToolHistoryObjectKind
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.observability.tool_history_store import (
    ToolHistoryCapacityError,
    ToolHistoryConflictError,
)
from codex_rosetta.observability.tool_mapping_crypto import (
    KEY_ENV_VAR,
    KEY_FILENAME,
    PAYLOAD_VERSION,
    ToolMappingCipher,
    ToolMappingIntegrityError,
    ToolMappingKeyError,
    mapping_aad,
)


def _call(call_id: str, *, name: str = "exec_command") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps({"cmd": "pwd", "nested": {"id": "kept"}}),
        },
    }


def _result(call_id: str, content: object = "workspace result") -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
    }


def _upsert(
    persistence: PersistenceManager,
    source: dict,
    target: dict,
    *,
    principal_id: str = "principal-a",
    kind: ToolHistoryObjectKind = ToolHistoryObjectKind.CALL,
    expire_at: str = "2030-01-02T00:00:00+00:00",
    timestamp: str = "2026-01-01T00:00:00+00:00",
) -> bool:
    return persistence.upsert_tool_history_translation(
        principal_id=principal_id,
        object_kind=kind,
        source_object=source,
        target_object=target,
        expire_at=expire_at,
        timestamp=timestamp,
    )


def _create_legacy_v1_table(data_dir) -> None:
    conn = sqlite3.connect(data_dir / "gateway.db")
    conn.execute("""
        CREATE TABLE tool_call_mappings (
            principal_id TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            model TEXT NOT NULL,
            session_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            payload_version INTEGER NOT NULL,
            key_id TEXT NOT NULL,
            nonce BLOB NOT NULL,
            encrypted_payload BLOB NOT NULL,
            expire_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (
                principal_id, provider_name, model, session_id, tool_call_id
            )
        )
    """)
    conn.commit()
    conn.close()


def _insert_legacy_v1(
    data_dir,
    *,
    call_id: str,
    source: dict,
    target: dict,
    principal_id: str = "principal-a",
    provider_name: str = "provider-a",
    model: str = "model-a",
    session_id: str = "window-a",
    expire_at: str = "2030-01-02T00:00:00+00:00",
    updated_at: str = "2026-01-01T00:00:00+00:00",
) -> None:
    cipher = ToolMappingCipher.load(data_dir, create=True)
    nonce, encrypted = cipher.encrypt(
        original_tool_call=target,
        codex_tool_call=source,
        aad=mapping_aad(
            principal_id=principal_id,
            provider_name=provider_name,
            model=model,
            session_id=session_id,
            tool_call_id=call_id,
        ),
    )
    conn = sqlite3.connect(data_dir / "gateway.db")
    conn.execute(
        "INSERT INTO tool_call_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            principal_id,
            provider_name,
            model,
            session_id,
            call_id,
            PAYLOAD_VERSION,
            cipher.key_id,
            nonce,
            encrypted,
            expire_at,
            "2026-01-01T00:00:00+00:00",
            updated_at,
        ),
    )
    conn.commit()
    conn.close()


def test_object_translation_survives_window_model_provider_and_call_id_changes(
    tmp_path,
):
    persistence = PersistenceManager(str(tmp_path))
    persistence.upsert_tool_history_translation(
        principal_id="principal-a",
        object_kind=ToolHistoryObjectKind.CALL,
        source_object=_call("parent-call"),
        target_object=_call("parent-call", name="Bash"),
        expire_at="2026-01-02T00:00:00+00:00",
        timestamp="2026-01-01T00:00:00+00:00",
    )

    rows = persistence.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[(ToolHistoryObjectKind.CALL, _call("fork-call"))],
        now="2026-01-01T12:00:00+00:00",
    )

    assert rows[0] is not None
    assert rows[0]["id"] == "fork-call"
    assert rows[0]["function"]["name"] == "Bash"
    assert json.loads(rows[0]["function"]["arguments"])["nested"]["id"] == "kept"
    persistence.close()


def test_principal_scoped_hmac_prevents_cross_principal_lookup_and_plaintext_storage(
    tmp_path,
):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("call-a")
    source["function"]["arguments"] = json.dumps(
        {"cmd": "printf super-secret-argument"}
    )
    target = _call("call-a", name="Bash")
    target["function"]["arguments"] = json.dumps(
        {"command": "printf super-secret-result"}
    )
    persistence.upsert_tool_history_translation(
        principal_id="principal-a",
        object_kind=ToolHistoryObjectKind.CALL,
        source_object=source,
        target_object=target,
        expire_at="2026-01-02T00:00:00+00:00",
        timestamp="2026-01-01T00:00:00+00:00",
    )

    assert persistence.lookup_tool_history_translations(
        principal_id="principal-b",
        objects=[(ToolHistoryObjectKind.CALL, source)],
        now="2026-01-01T12:00:00+00:00",
    ) == [None]
    raw = persistence._conn.execute(
        "SELECT lookup_token, encrypted_payload FROM tool_history_object_translations"
    ).fetchone()
    assert raw is not None
    stored = bytes(raw[0]) + bytes(raw[1])
    assert b"super-secret-argument" not in stored
    assert b"super-secret-result" not in stored
    persistence.close()


def test_same_source_uses_different_hmac_tokens_for_each_principal(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("source")
    target = _call("source", name="Bash")
    _upsert(persistence, source, target, principal_id="principal-a")
    _upsert(persistence, source, target, principal_id="principal-b")

    rows = persistence._conn.execute(
        "SELECT principal_id, lookup_token FROM tool_history_object_translations "
        "ORDER BY principal_id"
    ).fetchall()
    assert rows[0][0] == "principal-a"
    assert rows[1][0] == "principal-b"
    assert bytes(rows[0][1]) != bytes(rows[1][1])
    persistence.close()


@pytest.mark.parametrize(
    "content",
    [
        "plain output",
        '{"ok":true,"value":7}',
        "Error: command failed",
        "Client cancelled, did not execute",
    ],
)
def test_result_cache_is_independent_and_reinjects_current_id(tmp_path, content):
    persistence = PersistenceManager(str(tmp_path))
    _upsert(
        persistence,
        _result("old-result", content),
        _result("old-result", content),
        kind=ToolHistoryObjectKind.RESULT,
    )

    call_miss, result_hit = persistence.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[
            (ToolHistoryObjectKind.CALL, _call("new-call")),
            (ToolHistoryObjectKind.RESULT, _result("new-result", content)),
        ],
        now="2026-01-01T12:00:00+00:00",
    )

    assert call_miss is None
    assert result_hit == _result("new-result", content)
    persistence.close()


def test_parallel_identical_calls_and_reverse_results_do_not_bind_ids(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("call-a")
    target = _call("call-a", name="Bash")
    _upsert(persistence, source, target)
    _upsert(
        persistence,
        _result("call-a", "same result"),
        _result("call-a", "same result"),
        kind=ToolHistoryObjectKind.RESULT,
    )

    hits = persistence.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[
            (ToolHistoryObjectKind.CALL, _call("call-b")),
            (ToolHistoryObjectKind.CALL, _call("call-a")),
            (ToolHistoryObjectKind.RESULT, _result("call-b", "same result")),
            (ToolHistoryObjectKind.RESULT, _result("call-a", "same result")),
        ],
        now="2026-01-01T12:00:00+00:00",
    )

    assert all(item is not None for item in hits)
    restored = [item for item in hits if item is not None]
    assert [item["id"] for item in restored[:2]] == ["call-b", "call-a"]
    assert [item["tool_call_id"] for item in restored[2:]] == ["call-b", "call-a"]
    persistence.close()


def test_exact_source_conflict_does_not_overwrite_existing_target(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("source")
    first = _call("source", name="Bash")
    second = _call("source", name="Read")
    assert _upsert(persistence, source, first) is True

    with pytest.raises(ToolHistoryConflictError, match="conflicting translations"):
        _upsert(persistence, _call("different-id"), second)

    hit = persistence.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[(ToolHistoryObjectKind.CALL, _call("current-id"))],
        now="2026-01-01T12:00:00+00:00",
    )[0]
    assert hit is not None
    assert hit["function"]["name"] == "Bash"
    persistence.close()


def test_hit_and_duplicate_insert_do_not_renew_absolute_ttl(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("source")
    target = _call("source", name="Bash")
    assert (
        _upsert(
            persistence,
            source,
            target,
            expire_at="2026-01-02T00:00:00+00:00",
        )
        is True
    )
    assert (
        persistence.lookup_tool_history_translations(
            principal_id="principal-a",
            objects=[(ToolHistoryObjectKind.CALL, _call("hit"))],
            now="2026-01-01T12:00:00+00:00",
        )[0]
        is not None
    )
    assert (
        _upsert(
            persistence,
            _call("duplicate"),
            _call("duplicate", name="Bash"),
            expire_at="2026-02-01T00:00:00+00:00",
            timestamp="2026-01-01T12:00:00+00:00",
        )
        is False
    )
    expire_at, updated_at = persistence._conn.execute(
        "SELECT expire_at, updated_at FROM tool_history_object_translations"
    ).fetchone()
    assert expire_at == "2026-01-02T00:00:00+00:00"
    assert updated_at == "2026-01-01T00:00:00+00:00"
    persistence.close()


def test_expired_translation_is_a_miss_then_can_be_rewritten_with_fresh_ttl(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    source = _call("old-id")
    target = _call("old-id", name="Bash")
    persistence.upsert_tool_history_translation(
        principal_id="principal-a",
        object_kind=ToolHistoryObjectKind.CALL,
        source_object=source,
        target_object=target,
        expire_at="2026-01-01T01:00:00+00:00",
        timestamp="2026-01-01T00:00:00+00:00",
    )

    assert persistence.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[(ToolHistoryObjectKind.CALL, _call("new-id"))],
        now="2026-01-01T02:00:00+00:00",
    ) == [None]
    assert persistence.count_tool_history_translations() == 0

    persistence.upsert_tool_history_translation(
        principal_id="principal-a",
        object_kind=ToolHistoryObjectKind.CALL,
        source_object=_call("new-id"),
        target_object=_call("new-id", name="Bash"),
        expire_at="2026-01-02T02:00:00+00:00",
        timestamp="2026-01-01T02:00:00+00:00",
    )
    row = persistence._conn.execute(
        "SELECT expire_at FROM tool_history_object_translations"
    ).fetchone()
    assert row == ("2026-01-02T02:00:00+00:00",)
    persistence.close()


def test_new_database_does_not_create_retired_call_id_table(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    tables = {
        row[0]
        for row in persistence._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "tool_history_object_translations" in tables
    assert "tool_call_mappings" not in tables
    persistence.close()


def test_encrypted_v1_migration_deduplicates_skips_conflicts_and_expired(tmp_path):
    _create_legacy_v1_table(tmp_path)
    duplicate_source = _call("old-a")
    duplicate_target = _call("old-a", name="Bash")
    _insert_legacy_v1(
        tmp_path,
        call_id="old-a",
        source=duplicate_source,
        target=duplicate_target,
        session_id="window-a",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    _insert_legacy_v1(
        tmp_path,
        call_id="old-b",
        source=_call("old-b"),
        target=_call("old-b", name="Bash"),
        session_id="window-b",
        updated_at="2026-01-01T00:00:01+00:00",
    )
    _insert_legacy_v1(
        tmp_path,
        call_id="conflict-a",
        source={**_call("conflict-a"), "marker": "conflict"},
        target={**_call("conflict-a", name="Bash"), "marker": "conflict"},
        session_id="window-c",
        updated_at="2026-01-01T00:00:02+00:00",
    )
    _insert_legacy_v1(
        tmp_path,
        call_id="conflict-b",
        source={**_call("conflict-b"), "marker": "conflict"},
        target={**_call("conflict-b", name="Read"), "marker": "conflict"},
        session_id="window-d",
        updated_at="2026-01-01T00:00:03+00:00",
    )
    _insert_legacy_v1(
        tmp_path,
        call_id="unique",
        source={**_call("unique"), "marker": "unique"},
        target={**_call("unique", name="Read"), "marker": "unique"},
        session_id="window-e",
        updated_at="2026-01-01T00:00:04+00:00",
    )
    _insert_legacy_v1(
        tmp_path,
        call_id="expired",
        source={**_call("expired"), "marker": "expired"},
        target={**_call("expired", name="Read"), "marker": "expired"},
        session_id="window-f",
        expire_at="2020-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:05+00:00",
    )

    persistence = PersistenceManager(str(tmp_path))
    assert persistence.count_tool_history_translations() == 2
    duplicate_hit, conflict_miss, unique_hit = (
        persistence.lookup_tool_history_translations(
            principal_id="principal-a",
            objects=[
                (ToolHistoryObjectKind.CALL, _call("current")),
                (
                    ToolHistoryObjectKind.CALL,
                    {**_call("current-conflict"), "marker": "conflict"},
                ),
                (
                    ToolHistoryObjectKind.CALL,
                    {**_call("current-unique"), "marker": "unique"},
                ),
            ],
            now="2026-08-01T00:00:00+00:00",
        )
    )
    assert duplicate_hit is not None
    assert duplicate_hit["function"]["name"] == "Bash"
    assert conflict_miss is None
    assert unique_hit is not None
    assert unique_hit["function"]["name"] == "Read"
    persistence.close()
    conn = sqlite3.connect(tmp_path / "gateway.db")
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'table' AND name = 'tool_call_mappings'"
    ).fetchone() == (0,)
    conn.close()


def test_plaintext_legacy_rows_are_discarded_without_touching_other_tables(
    tmp_path, caplog
):
    conn = sqlite3.connect(tmp_path / "gateway.db")
    conn.executescript("""
        CREATE TABLE metrics (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metrics VALUES ('sentinel', '{"ok":true}');
        CREATE TABLE tool_call_mappings (
            principal_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            original_tool_call TEXT NOT NULL,
            codex_tool_call TEXT NOT NULL
        );
        INSERT INTO tool_call_mappings VALUES (
            'principal-a', 'call-a', '{"secret":"[REDACTED]"}', '{}'
        );
    """)
    conn.close()

    persistence = PersistenceManager(str(tmp_path))
    assert persistence._conn.execute(
        "SELECT value FROM metrics WHERE key = 'sentinel'"
    ).fetchone() == ('{"ok":true}',)
    assert (
        persistence._conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'tool_call_mappings'"
        ).fetchone()
        is None
    )
    assert "Discarded 1 plaintext/redacted legacy tool-history row" in caplog.text
    persistence.close()


def test_migration_capacity_failure_rolls_back_and_keeps_v1_table(tmp_path):
    _create_legacy_v1_table(tmp_path)
    for index in range(2):
        _insert_legacy_v1(
            tmp_path,
            call_id=f"legacy-{index}",
            source={**_call(f"legacy-{index}"), "marker": index},
            target={**_call(f"legacy-{index}", name="Bash"), "marker": index},
            session_id=f"window-{index}",
        )

    with pytest.raises(ToolHistoryCapacityError, match="global row count"):
        PersistenceManager(str(tmp_path), tool_mapping_max_global_rows=1)

    conn = sqlite3.connect(tmp_path / "gateway.db")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "tool_call_mappings" in tables
    assert "tool_history_object_translations" not in tables
    assert conn.execute("SELECT COUNT(*) FROM tool_call_mappings").fetchone() == (2,)
    conn.close()


def test_migration_sqlite_failure_rolls_back_without_dropping_v1(tmp_path):
    current = PersistenceManager(str(tmp_path))
    current.close()
    _create_legacy_v1_table(tmp_path)
    _insert_legacy_v1(
        tmp_path,
        call_id="legacy",
        source=_call("legacy"),
        target=_call("legacy", name="Bash"),
    )
    conn = sqlite3.connect(tmp_path / "gateway.db")
    conn.executescript("""
        CREATE TRIGGER fail_tool_history_migration
        BEFORE INSERT ON tool_history_object_translations
        BEGIN
            SELECT RAISE(ABORT, 'simulated migration failure');
        END;
    """)
    conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="simulated migration failure"):
        PersistenceManager(str(tmp_path))

    conn = sqlite3.connect(tmp_path / "gateway.db")
    assert conn.execute("SELECT COUNT(*) FROM tool_call_mappings").fetchone() == (1,)
    assert conn.execute(
        "SELECT COUNT(*) FROM tool_history_object_translations"
    ).fetchone() == (0,)
    conn.close()


def test_row_principal_and_global_quotas_are_transactional(tmp_path):
    row_limited = PersistenceManager(
        str(tmp_path / "row"), tool_mapping_max_row_bytes=128
    )
    with pytest.raises(ToolHistoryCapacityError, match="row bytes"):
        _upsert(row_limited, _call("large"), _call("large", name="Bash"))
    assert row_limited.count_tool_history_translations() == 0
    row_limited.close()

    principal_limited = PersistenceManager(
        str(tmp_path / "principal"), tool_mapping_max_principal_rows=1
    )
    _upsert(principal_limited, _call("one"), _call("one", name="Bash"))
    with pytest.raises(ToolHistoryCapacityError, match="principal row count"):
        _upsert(
            principal_limited,
            {**_call("two"), "marker": 2},
            {**_call("two", name="Bash"), "marker": 2},
        )
    assert principal_limited.count_tool_history_translations() == 1
    principal_limited.close()

    global_limited = PersistenceManager(
        str(tmp_path / "global"), tool_mapping_max_global_rows=1
    )
    _upsert(global_limited, _call("one"), _call("one", name="Bash"))
    with pytest.raises(ToolHistoryCapacityError, match="global row count"):
        _upsert(
            global_limited,
            {**_call("two"), "marker": 2},
            {**_call("two", name="Bash"), "marker": 2},
            principal_id="principal-b",
        )
    assert global_limited.count_tool_history_translations() == 1
    global_limited.close()


@pytest.mark.parametrize(
    ("limit_name", "expected"),
    [
        ("tool_mapping_max_principal_bytes", "principal bytes"),
        ("tool_mapping_max_global_bytes", "global bytes"),
    ],
)
def test_byte_quotas_reject_before_mutation(tmp_path, limit_name, expected):
    if limit_name == "tool_mapping_max_principal_bytes":
        persistence = PersistenceManager(
            str(tmp_path),
            tool_mapping_max_row_bytes=4096,
            tool_mapping_max_principal_bytes=128,
        )
    else:
        persistence = PersistenceManager(
            str(tmp_path),
            tool_mapping_max_row_bytes=4096,
            tool_mapping_max_global_bytes=128,
        )
    with pytest.raises(ToolHistoryCapacityError, match=expected):
        _upsert(persistence, _call("call"), _call("call", name="Bash"))
    assert persistence.count_tool_history_translations() == 0
    persistence.close()


def test_concurrent_inserts_cannot_oversubscribe_global_rows(tmp_path):
    persistence = PersistenceManager(str(tmp_path), tool_mapping_max_global_rows=1)

    def insert(index: int) -> bool:
        try:
            return _upsert(
                persistence,
                {**_call(f"call-{index}"), "marker": index},
                {**_call(f"call-{index}", name="Bash"), "marker": index},
                principal_id=f"principal-{index}",
            )
        except ToolHistoryCapacityError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(insert, range(8)))

    assert sum(accepted) == 1
    assert persistence.count_tool_history_translations() == 1
    persistence.close()


def test_accounting_tamper_fails_closed_on_restart(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    _upsert(persistence, _call("call"), _call("call", name="Bash"))
    persistence._conn.execute(
        "UPDATE tool_history_object_translations "
        "SET translation_bytes = translation_bytes + 1"
    )
    persistence._conn.commit()
    persistence.close()

    with pytest.raises(ToolHistoryCapacityError, match="accounting is invalid"):
        PersistenceManager(str(tmp_path))


def test_runtime_sqlite_failure_rolls_back_expiry_cleanup(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    _upsert(
        persistence,
        _call("expired"),
        _call("expired", name="Bash"),
        expire_at="2026-01-01T00:00:01+00:00",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    persistence._conn.executescript("""
        CREATE TRIGGER fail_tool_history_insert
        BEFORE INSERT ON tool_history_object_translations
        BEGIN
            SELECT RAISE(ABORT, 'simulated insert failure');
        END;
    """)

    with pytest.raises(sqlite3.IntegrityError, match="simulated insert failure"):
        _upsert(
            persistence,
            {**_call("current"), "marker": "current"},
            {**_call("current", name="Bash"), "marker": "current"},
            timestamp="2026-01-01T00:00:02+00:00",
        )

    assert persistence.count_tool_history_translations() == 1
    persistence.close()


def test_encrypted_rows_survive_restart_and_matched_backup(tmp_path):
    live_dir = tmp_path / "live"
    backup_dir = tmp_path / "backup"
    restored_dir = tmp_path / "restored"
    source = {**_call("source"), "secret": "exact source secret"}
    target = {**_call("source", name="Bash"), "secret": "exact target secret"}
    persistence = PersistenceManager(str(live_dir))
    _upsert(persistence, source, target)
    persistence.close()

    restarted = PersistenceManager(str(live_dir))
    hit = restarted.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[(ToolHistoryObjectKind.CALL, {**source, "id": "restart"})],
        now="2026-01-01T00:00:00+00:00",
    )[0]
    assert hit == {**target, "id": "restart"}
    restarted.close()

    backup_dir.mkdir()
    shutil.copy2(live_dir / "gateway.db", backup_dir / "gateway.db")
    shutil.copy2(live_dir / KEY_FILENAME, backup_dir / KEY_FILENAME)
    shutil.copytree(backup_dir, restored_dir)
    restored = PersistenceManager(str(restored_dir))
    assert restored.lookup_tool_history_translations(
        principal_id="principal-a",
        objects=[(ToolHistoryObjectKind.CALL, {**source, "id": "restored"})],
        now="2026-01-01T00:00:00+00:00",
    )[0] == {**target, "id": "restored"}
    restored.close()


def test_missing_malformed_wrong_key_and_tamper_fail_closed(tmp_path, monkeypatch):
    missing_dir = tmp_path / "missing"
    persistence = PersistenceManager(str(missing_dir))
    _upsert(persistence, _call("call"), _call("call", name="Bash"))
    persistence.close()
    (missing_dir / KEY_FILENAME).unlink()
    with pytest.raises(ToolMappingKeyError, match="missing"):
        PersistenceManager(str(missing_dir))

    malformed_dir = tmp_path / "malformed"
    persistence = PersistenceManager(str(malformed_dir))
    _upsert(persistence, _call("call"), _call("call", name="Bash"))
    persistence.close()
    key_path = malformed_dir / KEY_FILENAME
    key_path.write_text("v1:not-valid-base64\n")
    key_path.chmod(0o600)
    with pytest.raises(ToolMappingKeyError, match="base64-encoded"):
        PersistenceManager(str(malformed_dir))

    wrong_dir = tmp_path / "wrong"
    first_key = base64.urlsafe_b64encode(b"a" * 32).decode()
    second_key = base64.urlsafe_b64encode(b"b" * 32).decode()
    monkeypatch.setenv(KEY_ENV_VAR, first_key)
    persistence = PersistenceManager(str(wrong_dir))
    _upsert(persistence, _call("call"), _call("call", name="Bash"))
    persistence.close()
    monkeypatch.setenv(KEY_ENV_VAR, second_key)
    with pytest.raises(ToolMappingKeyError) as raised:
        PersistenceManager(str(wrong_dir))
    assert first_key not in str(raised.value)
    assert second_key not in str(raised.value)
    monkeypatch.delenv(KEY_ENV_VAR)

    tamper_dir = tmp_path / "tamper"
    persistence = PersistenceManager(str(tamper_dir))
    _upsert(persistence, _call("call"), _call("call", name="Bash"))
    payload = persistence._conn.execute(
        "SELECT encrypted_payload FROM tool_history_object_translations"
    ).fetchone()[0]
    tampered = bytes([payload[0] ^ 1]) + payload[1:]
    persistence._conn.execute(
        "UPDATE tool_history_object_translations SET encrypted_payload = ?",
        (tampered,),
    )
    persistence._conn.commit()
    persistence.close()
    with pytest.raises(ToolMappingIntegrityError, match="authentication"):
        PersistenceManager(str(tamper_dir))


def test_concurrent_key_creation_returns_one_owner_only_key(tmp_path):
    def load_key(_index: int) -> str:
        return ToolMappingCipher.load(tmp_path, create=True).key_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        key_ids = list(pool.map(load_key, range(32)))

    assert len(set(key_ids)) == 1
    assert stat.S_IMODE((tmp_path / KEY_FILENAME).stat().st_mode) == 0o600
    assert not list(tmp_path.glob(f".{KEY_FILENAME}.*.tmp"))
