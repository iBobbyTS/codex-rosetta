"""Tests for SQLite-based persistence and request log integration."""

import gzip
import json
import sqlite3
import stat
import time

import pytest

from codex_rosetta.gateway.admin.persistence import (
    DEFAULT_ERROR_MAX,
    DEFAULT_SUCCESS_MAX,
    PersistenceManager,
)
from codex_rosetta.gateway.admin.request_log import RequestLog, RequestLogEntry
from codex_rosetta.observability.persistence import (
    CompactionMappingCapacityError,
)


class TestCodexCompactionMappings:
    def test_stores_plaintext_but_only_token_hash_and_renews_on_read(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        plaintext = "prefixed summary with Orchid and A7-KAPPA"
        pm.store_codex_compaction_mapping(
            principal_id="client-a",
            token_hash="a" * 64,
            replacement_text=plaintext,
            source_model="deepseek-v4-flash",
            reason="comp_hash_changed",
            prompt_sha256="b" * 64,
            created_at="2026-07-01T00:00:00+00:00",
            expires_at="2026-07-08T00:00:00+00:00",
        )

        row = pm.get_codex_compaction_mapping(
            principal_id="client-a",
            token_hash="a" * 64,
            now="2026-07-02T00:00:00+00:00",
            renewed_expires_at="2026-07-09T00:00:00+00:00",
        )

        assert row is not None
        assert row["replacement_text"] == plaintext
        assert row["replacement_bytes"] == len(plaintext.encode("utf-8"))
        assert row["expires_at"] == "2026-07-09T00:00:00+00:00"
        columns = pm._conn.execute(
            "SELECT token_hash, replacement_text FROM codex_compaction_mappings"
        ).fetchone()
        assert columns == ("a" * 64, plaintext)
        pm.close()

    def test_principal_isolation_and_expiry(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.store_codex_compaction_mapping(
            principal_id="client-a",
            token_hash="a" * 64,
            replacement_text="summary",
            source_model="model",
            reason="context_limit",
            prompt_sha256="b" * 64,
            created_at="2026-07-01T00:00:00+00:00",
            expires_at="2026-07-08T00:00:00+00:00",
        )
        assert (
            pm.get_codex_compaction_mapping(
                principal_id="client-b",
                token_hash="a" * 64,
                now="2026-07-02T00:00:00+00:00",
            )
            is None
        )
        assert (
            pm.cleanup_expired_codex_compaction_mappings("2026-07-08T00:00:00+00:00")
            == 1
        )
        assert pm.count_codex_compaction_mappings() == 0
        pm.close()

    def test_enforces_row_and_aggregate_quotas_transactionally(self, tmp_path):
        pm = PersistenceManager(
            str(tmp_path),
            codex_compaction_max_row_bytes=8,
            codex_compaction_max_principal_rows=1,
            codex_compaction_max_principal_bytes=8,
            codex_compaction_max_global_rows=2,
            codex_compaction_max_global_bytes=16,
        )

        def store(principal: str, token: str, text: str) -> None:
            pm.store_codex_compaction_mapping(
                principal_id=principal,
                token_hash=token,
                replacement_text=text,
                source_model="model",
                reason="test",
                prompt_sha256="b" * 64,
                created_at="2027-07-01T00:00:00+00:00",
                expires_at="2027-07-08T00:00:00+00:00",
            )

        store("client-a", "a" * 64, "12345678")
        with pytest.raises(CompactionMappingCapacityError, match="row byte limit"):
            store("client-a", "b" * 64, "123456789")
        with pytest.raises(CompactionMappingCapacityError, match="principal row count"):
            store("client-a", "b" * 64, "1234")
        store("client-b", "b" * 64, "12345678")
        with pytest.raises(CompactionMappingCapacityError, match="global row count"):
            store("client-c", "c" * 64, "1234")
        assert pm.count_codex_compaction_mappings() == 2
        pm.close()


# -- Helpers --


def _make_entry_dict(
    model: str = "gpt-4o",
    status: int = 200,
    provider: str = "openai_chat",
    error_detail: str | None = None,
    api_key_label: str | None = None,
) -> dict:
    e = RequestLogEntry.create(
        model=model,
        source_provider="openai_chat",
        target_provider=provider,
        is_stream=False,
        status_code=status,
        duration_ms=10.0,
        error_detail=error_detail,
        api_key_label=api_key_label,
    )
    return e.to_dict()


def _make_entry(
    model: str = "gpt-4o",
    status: int = 200,
    provider: str = "openai_chat",
) -> RequestLogEntry:
    return RequestLogEntry.create(
        model=model,
        source_provider="openai_chat",
        target_provider=provider,
        is_stream=False,
        status_code=status,
        duration_ms=10.0,
    )


# -- PersistenceManager tests --


class TestPersistenceManagerSchema:
    def test_creates_db_file(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        assert pm.db_path.exists()
        pm.close()

    def test_drops_retired_soft_interrupt_handoff_table(self, tmp_path):
        db_path = tmp_path / "gateway.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE soft_interrupt_handoffs ("
            "principal_id TEXT, thread_id TEXT, hidden_output TEXT)"
        )
        conn.execute(
            "INSERT INTO soft_interrupt_handoffs VALUES (?, ?, ?)",
            ("principal-a", "thread-a", "plaintext hidden response"),
        )
        conn.commit()
        conn.close()

        pm = PersistenceManager(str(tmp_path))

        assert (
            pm._conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'soft_interrupt_handoffs'"
            ).fetchone()
            is None
        )
        pm.close()

    def test_storage_permissions_are_owner_only(self, tmp_path):
        data_dir = tmp_path / "gateway-data"
        pm = PersistenceManager(str(data_dir))
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(pm.db_path.stat().st_mode) == 0o600
        for suffix in ("-wal", "-shm"):
            sidecar = pm.db_path.with_name(pm.db_path.name + suffix)
            if sidecar.exists():
                assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
        pm.close()

    def test_wal_mode(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        row = pm._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        pm.close()

    def test_creates_tool_history_object_table_without_retired_v1_table(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        tables = {
            row[0]
            for row in pm._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "tool_history_object_translations" in tables
        assert "tool_call_mappings" not in tables
        pm.close()

    def test_rejects_same_compaction_columns_without_required_primary_key(
        self, tmp_path
    ):
        conn = sqlite3.connect(tmp_path / "gateway.db")
        conn.execute("""
            CREATE TABLE codex_compaction_mappings (
                principal_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                replacement_text TEXT NOT NULL,
                replacement_bytes INTEGER NOT NULL,
                source_model TEXT NOT NULL,
                reason TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.close()

        with pytest.raises(RuntimeError, match="column/type/constraint shape differs"):
            PersistenceManager(str(tmp_path))

    @pytest.mark.parametrize(
        "index_sql",
        [
            "CREATE UNIQUE INDEX idx_ccm_principal "
            "ON codex_compaction_mappings(principal_id)",
            "CREATE INDEX idx_ccm_principal "
            "ON codex_compaction_mappings(principal_id) "
            "WHERE principal_id IS NOT NULL",
        ],
    )
    def test_rejects_existing_required_index_with_wrong_attributes(
        self, tmp_path, index_sql
    ):
        conn = sqlite3.connect(tmp_path / "gateway.db")
        conn.executescript("""
            CREATE TABLE codex_compaction_mappings (
                principal_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                replacement_text TEXT NOT NULL,
                replacement_bytes INTEGER NOT NULL,
                source_model TEXT NOT NULL,
                reason TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (principal_id, token_hash)
            );
        """)
        conn.execute(index_sql)
        conn.close()

        with pytest.raises(RuntimeError, match="has unexpected attributes"):
            PersistenceManager(str(tmp_path))

    def test_rejects_existing_required_index_with_wrong_columns(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "gateway.db")
        conn.executescript("""
            CREATE TABLE codex_compaction_mappings (
                principal_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                replacement_text TEXT NOT NULL,
                replacement_bytes INTEGER NOT NULL,
                source_model TEXT NOT NULL,
                reason TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (principal_id, token_hash)
            );
            CREATE INDEX idx_ccm_principal
                ON codex_compaction_mappings(token_hash);
        """)
        conn.close()

        with pytest.raises(RuntimeError, match="has unexpected columns"):
            PersistenceManager(str(tmp_path))


class TestPersistenceManagerRequestLog:
    def test_insert_and_query(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        entries = [_make_entry_dict(model=f"m-{i}") for i in range(5)]
        pm.insert_log_entries(entries)

        results, total = pm.query_log_entries(limit=10)
        assert total == 5
        assert len(results) == 5
        pm.close()

    def test_zero_row_provider_backfill_closes_transaction(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))

        assert pm._conn.in_transaction is False

        prepared = pm.prepare_update((), success_max=10, error_max=10)
        pm.commit_update(prepared)
        pm.close()

    def test_newest_first(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        e1 = _make_entry_dict(model="first")
        time.sleep(0.01)  # ensure distinct timestamps
        e2 = _make_entry_dict(model="second")
        pm.insert_log_entries([e1, e2])

        results, _ = pm.query_log_entries()
        assert results[0]["model"] == "second"
        assert results[1]["model"] == "first"
        pm.close()

    def test_filter_by_model(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(model="gpt-4o"),
                _make_entry_dict(model="claude"),
                _make_entry_dict(model="gpt-4o"),
            ]
        )

        results, total = pm.query_log_entries(model="gpt-4o")
        assert total == 2
        assert all(r["model"] == "gpt-4o" for r in results)
        pm.close()

    def test_filter_by_provider(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(provider="openai_chat"),
                _make_entry_dict(provider="anthropic"),
            ]
        )

        results, total = pm.query_log_entries(provider="anthropic")
        assert total == 1
        assert results[0]["target_provider"] == "anthropic"
        pm.close()

    def test_filter_by_status(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(status=200),
                _make_entry_dict(status=500),
                _make_entry_dict(status=404),
            ]
        )

        ok_results, ok_total = pm.query_log_entries(status="ok")
        assert ok_total == 1

        err_results, err_total = pm.query_log_entries(status="error")
        assert err_total == 2
        pm.close()

    def test_filter_by_api_key_label(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(api_key_label="alice"),
                _make_entry_dict(api_key_label="bob"),
                _make_entry_dict(api_key_label="alice"),
                _make_entry_dict(),  # no label
            ]
        )

        results, total = pm.query_log_entries(api_key_label="alice")
        assert total == 2
        assert all(r["api_key_label"] == "alice" for r in results)

        results, total = pm.query_log_entries(api_key_label="bob")
        assert total == 1
        pm.close()

    def test_get_api_key_labels(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(api_key_label="bob"),
                _make_entry_dict(api_key_label="alice"),
                _make_entry_dict(api_key_label="bob"),
                _make_entry_dict(),
            ]
        )

        assert pm.get_api_key_labels() == ["alice", "bob"]
        pm.close()

    def test_pagination(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        entries = [_make_entry_dict(model=f"m-{i}") for i in range(20)]
        pm.insert_log_entries(entries)

        page1, total = pm.query_log_entries(limit=5, offset=0)
        assert total == 20
        assert len(page1) == 5

        page2, _ = pm.query_log_entries(limit=5, offset=5)
        assert len(page2) == 5
        assert page1[0]["id"] != page2[0]["id"]
        pm.close()

    def test_get_log_entry(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        entry = _make_entry_dict()
        pm.insert_log_entries([entry])

        found = pm.get_log_entry(entry["id"])
        assert found is not None
        assert found["id"] == entry["id"]
        assert found["model"] == entry["model"]
        pm.close()

    def test_get_log_entry_not_found(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        assert pm.get_log_entry("nonexistent") is None
        pm.close()

    def test_clear_log(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries([_make_entry_dict() for _ in range(5)])
        assert pm.count_log_entries() == 5

        pm.clear_log()
        assert pm.count_log_entries() == 0
        pm.close()

    def test_prune(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=10)
        # Insert 150 successful entries in batches to trigger prune.
        for batch in range(3):
            entries = [_make_entry_dict(model=f"m-{batch}-{i}") for i in range(50)]
            pm.insert_log_entries(entries)

        assert pm.count_success_entries() <= 10
        pm.close()


class TestPersistenceManagerRetention:
    """Dual-threshold prune: success and error caps are independent."""

    def test_defaults(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        assert pm.success_max == DEFAULT_SUCCESS_MAX
        assert pm.error_max == DEFAULT_ERROR_MAX
        pm.close()

    def test_explicit_caps(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=123, error_max=45)
        assert pm.success_max == 123
        assert pm.error_max == 45
        pm.close()

    def test_errors_not_evicted_by_success_flood(self, tmp_path):
        # Tiny success cap, generous error cap: a flood of successes must
        # not evict the rare error rows.
        pm = PersistenceManager(str(tmp_path), success_max=20, error_max=10)

        err_entries = [_make_entry_dict(status=500, model=f"e-{i}") for i in range(5)]
        pm.insert_log_entries(err_entries)

        for batch in range(2):
            ok_entries = [_make_entry_dict(model=f"ok-{batch}-{i}") for i in range(100)]
            pm.insert_log_entries(ok_entries)

        assert pm.count_success_entries() <= 20
        assert pm.count_error_entries() == 5
        pm.close()

    def test_error_cap_pruned_independently(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=1000, error_max=10)
        # 150 errors, batched to trigger periodic prune at 100.
        for batch in range(3):
            entries = [
                _make_entry_dict(status=500, model=f"e-{batch}-{i}") for i in range(50)
            ]
            pm.insert_log_entries(entries)

        assert pm.count_error_entries() <= 10
        assert pm.count_success_entries() == 0
        pm.close()

    def test_policy_update_decreases_caps_immediately_and_can_rollback(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=10, error_max=10)
        pm.insert_log_entries(
            [_make_entry_dict(model=f"ok-{index}") for index in range(5)]
            + [
                _make_entry_dict(status=500, model=f"error-{index}")
                for index in range(4)
            ]
        )

        prepared = pm.prepare_update(
            {"new-token"},
            success_max=2,
            error_max=1,
        )
        rollback = pm.commit_update(prepared)

        assert pm.success_max == 2
        assert pm.error_max == 1
        assert pm.count_success_entries() == 2
        assert pm.count_error_entries() == 1
        assert pm.redact_sensitive("new-token") == "[REDACTED]"

        pm.rollback_update(rollback)

        assert pm.success_max == 10
        assert pm.error_max == 10
        assert pm.count_success_entries() == 5
        assert pm.count_error_entries() == 4
        assert pm.redact_sensitive("new-token") == "new-token"
        pm.close()

    def test_policy_update_increases_caps_without_deleting_rows(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=10, error_max=10)
        pm.insert_log_entries(
            [_make_entry_dict() for _ in range(5)]
            + [_make_entry_dict(status=500) for _ in range(4)]
        )

        pm.commit_update(pm.prepare_update((), success_max=20, error_max=30))

        assert pm.success_max == 20
        assert pm.error_max == 30
        assert pm.count_success_entries() == 5
        assert pm.count_error_entries() == 4
        pm.close()

    def test_partial_prune_failure_rolls_back_caps_and_rows(
        self,
        tmp_path,
        monkeypatch,
    ):
        pm = PersistenceManager(str(tmp_path), success_max=10, error_max=10)
        pm.insert_log_entries(
            [_make_entry_dict() for _ in range(5)]
            + [_make_entry_dict(status=500) for _ in range(4)]
        )

        def fail_after_first_delete(*, commit: bool = True) -> None:
            assert commit is False
            pm._conn.execute("DELETE FROM request_log WHERE status_code < 400")
            raise RuntimeError("simulated prune failure")

        monkeypatch.setattr(pm, "_prune", fail_after_first_delete)

        with pytest.raises(RuntimeError, match="simulated prune failure"):
            pm.commit_update(pm.prepare_update((), success_max=2, error_max=1))

        assert pm.success_max == 10
        assert pm.error_max == 10
        assert pm.count_success_entries() == 5
        assert pm.count_error_entries() == 4
        pm.close()

    def test_commit_failure_rolls_back_caps_and_rows(self, tmp_path, monkeypatch):
        pm = PersistenceManager(str(tmp_path), success_max=10, error_max=10)
        pm.insert_log_entries(
            [_make_entry_dict() for _ in range(5)]
            + [_make_entry_dict(status=500) for _ in range(4)]
        )

        def fail_commit() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(pm, "_commit_retention_transaction", fail_commit)

        with pytest.raises(RuntimeError, match="simulated commit failure"):
            pm.commit_update(pm.prepare_update((), success_max=2, error_max=1))

        assert pm.success_max == 10
        assert pm.error_max == 10
        assert pm.count_success_entries() == 5
        assert pm.count_error_entries() == 4
        pm.close()

    def test_restart_applies_current_caps_to_existing_rows(self, tmp_path):
        pm = PersistenceManager(str(tmp_path), success_max=10, error_max=10)
        pm.insert_log_entries(
            [_make_entry_dict() for _ in range(5)]
            + [_make_entry_dict(status=500) for _ in range(4)]
        )
        pm.close()

        restarted = PersistenceManager(str(tmp_path), success_max=3, error_max=2)

        assert restarted.count_success_entries() == 3
        assert restarted.count_error_entries() == 2
        restarted.close()

    def test_count_success_and_error_separately(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(status=200),
                _make_entry_dict(status=201),
                _make_entry_dict(status=404),
                _make_entry_dict(status=500),
                _make_entry_dict(status=502),
            ]
        )
        assert pm.count_log_entries() == 5
        assert pm.count_success_entries() == 2
        assert pm.count_error_entries() == 3
        pm.close()


class TestPersistenceManagerSizes:
    def test_db_file_sizes_keys(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        sizes = pm.db_file_sizes()
        assert set(sizes.keys()) == {"db_bytes", "wal_bytes", "shm_bytes"}
        assert all(isinstance(v, int) for v in sizes.values())
        pm.close()

    def test_db_file_sizes_nonzero_after_insert(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries([_make_entry_dict(model=f"m-{i}") for i in range(50)])
        sizes = pm.db_file_sizes()
        # Main db file always exists after init; WAL is created on first write.
        assert sizes["db_bytes"] > 0
        assert sizes["wal_bytes"] >= 0
        pm.close()

    def test_bool_roundtrip(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        e = RequestLogEntry.create(
            model="test",
            source_provider="a",
            target_provider="b",
            is_stream=True,
            status_code=200,
            duration_ms=1.0,
        )
        pm.insert_log_entries([e.to_dict()])

        results, _ = pm.query_log_entries()
        assert results[0]["is_stream"] is True
        pm.close()

    def test_error_detail_stored(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries(
            [
                _make_entry_dict(error_detail="upstream 500: internal error"),
            ]
        )

        results, _ = pm.query_log_entries()
        assert results[0]["error_detail"] == "upstream 500: internal error"
        pm.close()

    def test_request_metadata_is_token_redacted_at_sqlite_write_boundary(
        self, tmp_path
    ):
        pm = PersistenceManager(str(tmp_path), token_values={"provider-token"})
        entry = _make_entry_dict(
            error_detail=(
                "Bearer bearer-token provider-token ordinary-password ordinary-secret"
            )
        )
        entry["profile"] = {
            "stream_error": "provider-token",
            "authorization": "Bearer profile-token",
            "password": "ordinary-password",
            "client_secret": "ordinary-client-secret",
        }
        pm.insert_log_entries([entry])

        pm.update_entry_profile(
            entry["id"],
            {
                "stream_error": "Bearer update-token provider-token",
                "proxy_password": "ordinary-proxy-password",
            },
        )

        row = pm._conn.execute(
            "SELECT error_detail, profile FROM request_log WHERE id = ?",
            (entry["id"],),
        ).fetchone()
        assert row is not None
        persisted = " ".join(str(value) for value in row)
        for raw_token in (
            "bearer-token",
            "provider-token",
            "profile-token",
            "update-token",
        ):
            assert raw_token not in persisted
        assert "ordinary-password" in persisted
        assert "ordinary-secret" in persisted
        assert "ordinary-client-secret" in persisted
        assert "ordinary-proxy-password" in persisted
        pm.close()

    def test_model_response_request_log_uses_protocol_diagnostic_redaction(
        self, tmp_path
    ):
        pm = PersistenceManager(str(tmp_path), token_values={"provider-token"})
        entry = _make_entry_dict(error_detail="authorization=secret; provider-token")
        entry["profile"] = {
            "stream_error": "api_key: secret; provider-token",
            "content": "provider-token",
            "token": "nested-secret",
        }

        pm.insert_log_entries([entry], response_redaction="protocol_fields")
        pm.update_entry_profile(
            entry["id"],
            {
                "stream_error": "authorization=updated; provider-token",
                "content": "provider-token",
            },
            response_redaction="protocol_fields",
        )

        result = pm.get_log_entry(entry["id"])
        assert result is not None
        assert result["error_detail"] == ("authorization=[REDACTED]; provider-token")
        assert result["profile"] == {
            "stream_error": "authorization=[REDACTED]; provider-token",
            "content": "provider-token",
            "token": "[REDACTED]",
        }
        pm.close()

    def test_none_fields_omitted(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.insert_log_entries([_make_entry_dict()])

        results, _ = pm.query_log_entries()
        assert "error_detail" not in results[0]
        assert "api_key_label" not in results[0]
        assert "client_ip" not in results[0]
        pm.close()


class TestPersistenceManagerMetrics:
    def test_save_and_load(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        data = {"total_requests": 42, "total_errors": 3}
        pm.save_metrics(data)

        loaded = pm.load_metrics()
        assert loaded == data
        pm.close()

    def test_load_empty(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        assert pm.load_metrics() is None
        pm.close()

    def test_overwrite(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        pm.save_metrics({"total_requests": 10})
        pm.save_metrics({"total_requests": 20})

        loaded = pm.load_metrics()
        assert loaded is not None
        assert loaded["total_requests"] == 20
        pm.close()


# -- Legacy migration tests --


class TestLegacyPersistenceRejected:
    def test_legacy_jsonl_is_rejected(self, tmp_path):
        # Write legacy JSONL
        entries = [_make_entry_dict(model=f"legacy-{i}") for i in range(3)]
        jsonl_path = tmp_path / "request_log.jsonl"
        with open(jsonl_path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        with pytest.raises(RuntimeError, match="legacy persistence files"):
            PersistenceManager(str(tmp_path))
        assert jsonl_path.exists()

    def test_legacy_metrics_json_is_rejected(self, tmp_path):
        metrics_path = tmp_path / "metrics.json"
        metrics_path.write_text(json.dumps({"total_requests": 99}))

        with pytest.raises(RuntimeError, match="legacy persistence files"):
            PersistenceManager(str(tmp_path))
        assert metrics_path.exists()

    def test_legacy_gzip_backups_are_rejected(self, tmp_path):
        # Write gzipped backup
        entries = [_make_entry_dict(model=f"gz-{i}") for i in range(5)]
        gz_path = tmp_path / "request_log.1.jsonl.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        # Also need the main file to trigger migration
        (tmp_path / "request_log.jsonl").write_text("")

        with pytest.raises(RuntimeError, match="legacy persistence files"):
            PersistenceManager(str(tmp_path))
        assert gz_path.exists()

    def test_no_migration_when_clean(self, tmp_path):
        # No legacy files — should just start clean
        pm = PersistenceManager(str(tmp_path))
        assert pm.count_log_entries() == 0
        assert pm.load_metrics() is None
        pm.close()


# -- RequestLog with persistence integration --


class TestRequestLogWithPersistence:
    def test_add_and_get(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry())

        entries, total = log.get_entries()
        assert total == 1
        assert len(entries) == 1
        pm.close()

    def test_filter_by_model(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry(model="gpt-4o"))
        log.add(_make_entry(model="claude"))
        log.add(_make_entry(model="gpt-4o"))

        entries, total = log.get_entries(model="gpt-4o")
        assert total == 2
        assert all(e["model"] == "gpt-4o" for e in entries)
        pm.close()

    def test_filter_by_status(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry(status=200))
        log.add(_make_entry(status=500))
        log.add(_make_entry(status=404))

        _, ok_total = log.get_entries(status="ok")
        assert ok_total == 1
        _, err_total = log.get_entries(status="error")
        assert err_total == 2
        pm.close()

    def test_clear(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry())
        log.add(_make_entry())
        assert len(log) == 2
        log.clear()
        assert len(log) == 0
        pm.close()

    def test_get_entry_by_id(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        e = _make_entry()
        log.add(e)

        found = log.get_entry(e.id)
        assert found is not None
        assert found["id"] == e.id
        pm.close()

    def test_pending_returns_empty(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry())
        assert log.pending_entries() == []
        pm.close()

    def test_newest_first(self, tmp_path):
        pm = PersistenceManager(str(tmp_path))
        log = RequestLog(persistence=pm)
        log.add(_make_entry(model="first"))
        time.sleep(0.01)
        log.add(_make_entry(model="second"))

        entries, _ = log.get_entries()
        assert entries[0]["model"] == "second"
        assert entries[1]["model"] == "first"
        pm.close()
