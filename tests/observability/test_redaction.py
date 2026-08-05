"""Tests for targeted diagnostic secret redaction."""

import json
from typing import Any, cast

import pytest

from codex_rosetta.observability.redaction import (
    REDACTED,
    SecretRedactor,
    collect_token_values,
    secret_fingerprint,
)


def test_secret_fingerprint_is_stable_normalized_and_domain_separated():
    first = secret_fingerprint("candidate", ["beta", "alpha", "beta", ""])

    assert first == secret_fingerprint("candidate", ["alpha", "beta"])
    assert first != secret_fingerprint("other-candidate", ["alpha", "beta"])
    assert first != secret_fingerprint("candidate", ["alpha", "gamma"])
    assert "alpha" not in first
    assert "beta" not in first
    assert first.startswith("hmac-sha256:")


def test_secret_fingerprint_uses_unambiguous_length_prefixes():
    assert secret_fingerprint("ab", ["c"]) != secret_fingerprint("a", ["bc"])
    assert secret_fingerprint("domain", ["a", "bc"]) != secret_fingerprint(
        "domain", ["ab", "c"]
    )


@pytest.mark.parametrize("domain", ["", None, 42])
def test_secret_fingerprint_rejects_invalid_domains(domain):
    error_type = ValueError if domain == "" else TypeError
    with pytest.raises(error_type):
        secret_fingerprint(domain, ["secret"])


def test_secret_fingerprint_ignores_empty_values_and_rejects_non_strings():
    assert secret_fingerprint("candidate", [""]) == secret_fingerprint("candidate", [])
    with pytest.raises(TypeError, match="values must be strings"):
        secret_fingerprint("candidate", cast(Any, ["secret", None]))


def test_collects_only_configured_api_tokens():
    values = collect_token_values(
        {
            "providers": {"p": {"api_key": "provider-secret"}},
            "server": {
                "admin_password": "admin-secret",
                "api_keys": [{"id": "client", "key": "gateway-secret"}],
                "proxy": "http://user:proxy-secret@example.test:8080",
            },
            "oauth": {"access_token": "oauth-token", "client_secret": "keep-me"},
        }
    )
    assert values == {
        "provider-secret",
        "gateway-secret",
        "oauth-token",
    }


def test_redacts_only_tokens_and_preserves_non_token_payload_data():
    redactor = SecretRedactor({"known-api-token"})
    value = {
        "prompt": "Email alice@example.com and keep source: token = user_value",
        "source": "def bearer(value): return value",
        "api_key": "field-secret",
        "password": "password-secret",
        "secret": "ordinary-secret",
        "client_secret": "client-secret",
        "proxy_password": "proxy-secret",
        "token_count": 123,
        "max_tokens": 4096,
        "nested": {
            "Authorization": "Bearer bearer-secret",
            "ordinary": "prefix known-api-token suffix",
        },
    }

    redacted = redactor.redact(value)

    assert redacted["prompt"] == value["prompt"]
    assert redacted["source"] == value["source"]
    assert redacted["api_key"] == REDACTED
    assert redacted["password"] == "password-secret"
    assert redacted["secret"] == "ordinary-secret"
    assert redacted["client_secret"] == "client-secret"
    assert redacted["proxy_password"] == "proxy-secret"
    assert redacted["token_count"] == 123
    assert redacted["max_tokens"] == 4096
    assert redacted["nested"]["Authorization"] == REDACTED
    assert redacted["nested"]["ordinary"] == "prefix [REDACTED] suffix"


def test_redacts_token_fields_inside_encoded_tool_arguments_only():
    redactor = SecretRedactor({"known-api-token"})
    arguments = json.dumps(
        {
            "command": (
                "curl -H 'Authorization: Bearer bearer-secret' "
                "https://user@example.com?key=known-api-token"
            ),
            "api_key": "tool-api-key",
            "password": "ordinary-password",
            "secret": "ordinary-secret",
            "client_secret": "ordinary-client-secret",
            "proxy_password": "ordinary-proxy-password",
            "prompt": "keep user@example.com and the rest of this prompt",
        },
        separators=(",", ":"),
    )
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "Bash", "arguments": arguments},
    }

    redacted = redactor.redact(tool_call)
    redacted_arguments = json.loads(redacted["function"]["arguments"])

    assert "bearer-secret" not in redacted_arguments["command"]
    assert "known-api-token" not in redacted_arguments["command"]
    assert redacted_arguments["api_key"] == REDACTED
    assert redacted_arguments["password"] == "ordinary-password"
    assert redacted_arguments["secret"] == "ordinary-secret"
    assert redacted_arguments["client_secret"] == "ordinary-client-secret"
    assert redacted_arguments["proxy_password"] == "ordinary-proxy-password"
    assert redacted_arguments["prompt"] == (
        "keep user@example.com and the rest of this prompt"
    )


def test_keeps_encoded_tool_arguments_byte_identical_without_tokens():
    arguments = '{"password":"ordinary-password","prompt":"user@example.com"}'
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "Bash", "arguments": arguments},
    }

    redacted = SecretRedactor().redact(tool_call)

    assert redacted["function"]["arguments"] == arguments


def test_exact_redaction_preserves_non_secret_fields_and_nested_shapes():
    redactor = SecretRedactor({"provider-secret"})
    value = {
        "token": "ordinary-model-value",
        "nested": [
            "before provider-secret after",
            {"blob": b"\xffprovider-secret\x00"},
        ],
    }

    redacted = redactor.redact_exact(value)

    assert redacted == {
        "token": "ordinary-model-value",
        "nested": [
            "before [REDACTED] after",
            {"blob": b"\xff[REDACTED]\x00"},
        ],
    }
    assert value["nested"][0] == "before provider-secret after"


@pytest.mark.parametrize("method_name", ["redact", "redact_exact"])
def test_configured_tokens_are_redacted_from_dict_keys_with_last_item_wins(
    method_name: str,
) -> None:
    token = "provider-key-secret"
    value = {
        token: "secret-key-first",
        REDACTED: "ordinary-later-value",
        f"prefix-{token}": "string-key",
        f"bytes-{token}".encode(): "bytes-key",
        7: "non-string-key",
    }

    redacted = getattr(SecretRedactor({token}), method_name)(value)

    assert token not in repr(redacted)
    assert redacted[REDACTED] == "ordinary-later-value"
    assert redacted["prefix-[REDACTED]"] == "string-key"
    assert redacted[b"bytes-[REDACTED]"] == "bytes-key"
    assert redacted[7] == "non-string-key"


def test_wire_redaction_handles_json_escaped_credentials():
    token = 'provider-"quoted\\key-\N{SNOWMAN}'
    payload = json.dumps(
        {"nested": {"credential": token}},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()

    redacted = SecretRedactor({token}).redact_wire_bytes(payload)

    assert token.encode() not in redacted
    assert json.loads(redacted)["nested"]["credential"] == "[REDACTED]"


def test_streaming_wire_redaction_covers_every_token_split_and_prefix_overlap():
    token = b"provider-secret-long"
    payload = b'event: message\ndata: {"text":"before ' + token + b' after"}\n\n'
    expected = payload.replace(token, b"[REDACTED]")
    redactor = SecretRedactor({"provider-secret", token.decode()})

    for split in range(len(payload) + 1):
        stream = redactor.streaming_redactor()
        actual = stream.feed(payload[:split])
        actual += stream.feed(payload[split:])
        actual += stream.finish()
        assert actual == expected

    bytewise = redactor.streaming_redactor()
    actual = b"".join(bytewise.feed(bytes([value])) for value in payload)
    actual += bytewise.finish()
    assert actual == expected


def test_streaming_value_detector_covers_splits_unicode_and_prefix_overlap():
    token = "credential-U0001f600-long"
    payload = f"before {token} after".encode()
    redactor = SecretRedactor({"credential", token})

    for split in range(len(payload) + 1):
        detector = redactor.streaming_value_detector()
        detected = detector.feed(payload[:split])
        if not detected:
            detected = detector.feed(payload[split:])
        assert detected


def test_streaming_wire_detector_detects_json_escaped_value_across_splits():
    token = 'provider-"quoted\\key-N{SNOWMAN}'
    encoded = json.dumps(token, ensure_ascii=True)[1:-1].encode()
    redactor = SecretRedactor({token})

    for split in range(len(encoded) + 1):
        detector = redactor.streaming_wire_detector()
        detected = detector.feed(encoded[:split])
        if not detected:
            detected = detector.feed(encoded[split:])
        assert detected


def test_streaming_detector_has_bounded_tail_and_empty_set_is_noop():
    detector = SecretRedactor({"secret-token"}).streaming_value_detector()
    assert not detector.feed(b"x" * 1_000_000)
    assert len(detector._pending) <= len(b"secret-token") - 1
    detector.finish()
    with pytest.raises(RuntimeError):
        detector.feed(b"ordinary")

    empty = SecretRedactor().streaming_wire_detector()
    assert not empty.feed(b"anything")
    empty.finish()


@pytest.mark.parametrize(
    "value",
    [
        "prefix credential suffix",
        b"prefix credential suffix",
        {"credential": "ordinary"},
        {"nested": ["credential"]},
    ],
)
def test_contains_exact_detects_credentials_in_keys_values_and_wire(value):
    assert SecretRedactor({"credential"}).contains_exact(value)


def test_contains_exact_detects_json_escaped_and_scalar_credentials():
    escaped = json.dumps({"value": 'quoted"credential'}, separators=(",", ":"))
    assert SecretRedactor({'quoted"credential'}).contains_wire_bytes(escaped.encode())
    assert SecretRedactor({"1"}).contains_exact(1)


@pytest.mark.parametrize(
    ("token", "payload", "detected_on_wire"),
    [
        ("secret", b'{"value":"\\u0073ecret"}', False),
        ("secret", b'{"\\u0073ecret":"value"}', False),
        ("a/b", b'{"value":"a\\/b"}', False),
        ("emoji-\U0001f600", b'{"value":"emoji-\\ud83d\\ude00"}', True),
        ('quote"slash\\', b'{"value":"quote\\"slash\\\\"}', True),
    ],
)
def test_contains_json_semantic_detects_equivalent_string_encodings(
    token: str,
    payload: bytes,
    detected_on_wire: bool,
) -> None:
    redactor = SecretRedactor({token})

    assert redactor.contains_wire_bytes(payload) is detected_on_wire
    assert redactor.contains_json_semantic(payload)


def test_contains_json_semantic_preserves_invalid_and_unrelated_content() -> None:
    redactor = SecretRedactor({"secret"})

    assert not redactor.contains_json_semantic(b'{"value":"ordinary"}')
    assert not redactor.contains_json_semantic(b'{"value":"\\u0073ecret"')


def test_contains_json_semantic_checks_duplicate_object_members() -> None:
    redactor = SecretRedactor({"secret"})

    assert redactor.contains_json_semantic(
        b'{"value":"\\u0073ecret","value":"ordinary"}'
    )


@pytest.mark.parametrize(
    "values",
    [
        ({"first": "CANARY-ALPHA-"}, {"second": "BETA"}),
        ({"CANARY-ALPHA-": "first"}, {"BETA": "second"}),
        ([b"prefix-CANARY-ALPHA-", "BETA-suffix"],),
    ],
)
def test_contains_ordered_fragments_detects_diagnostic_reconstruction(
    values: tuple[object, ...],
) -> None:
    redactor = SecretRedactor({"CANARY-ALPHA-BETA"})

    assert redactor.contains_ordered_fragments(values)


def test_contains_ordered_fragments_preserves_unrelated_diagnostics() -> None:
    redactor = SecretRedactor({"CANARY-ALPHA-BETA"})

    assert not redactor.contains_ordered_fragments(
        ({"first": "CANARY-OMEGA-"}, {"second": "BETA"})
    )


def test_contains_ordered_fragments_checks_only_token_length_boundary_suffixes() -> (
    None
):
    redactor = SecretRedactor({"CANARY-ALPHA-BETA"})
    long_prefix = "x" * 1_000_000

    assert redactor.contains_ordered_fragments((long_prefix + "CANARY-ALPHA-", "BETA"))


def test_contains_ordered_fragments_parses_json_and_sse_diagnostic_text() -> None:
    redactor = SecretRedactor({"CANARY-ALPHA-BETA"})

    assert redactor.contains_ordered_fragments(
        (
            b'data: {"diagnostic":"CANARY-ALPHA-"}\n\n',
            'event: message\ndata: {"diagnostic":"BETA"}\n\n',
        )
    )


@pytest.mark.parametrize("token", ["null", "true", "1"])
def test_contains_ordered_fragments_preserves_json_scalar_text(token: str) -> None:
    assert SecretRedactor({token}).contains_ordered_fragments((token,))


def test_contains_ordered_fragments_preserves_quoted_plain_text() -> None:
    assert SecretRedactor({'"quoted"'}).contains_ordered_fragments(('"quoted"',))


def test_contains_ordered_fragments_fails_closed_when_work_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_rosetta.observability import redaction

    monkeypatch.setattr(redaction, "MAX_ORDERED_DIAGNOSTIC_WORK", 1)

    assert SecretRedactor({"credential"}).contains_ordered_fragments(("ordinary",))


def test_protocol_diagnostic_preserves_plain_token_and_redacts_known_locations() -> (
    None
):
    redactor = SecretRedactor({"provider-token"})

    assert redactor.redact_protocol_diagnostic(
        {
            "content": "provider-token",
            "authorization": "Bearer provider-token",
            "stream_error": "authorization=provider-token; provider-token",
        }
    ) == {
        "content": "provider-token",
        "authorization": "[REDACTED]",
        "stream_error": "authorization=[REDACTED]; provider-token",
    }
