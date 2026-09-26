from __future__ import annotations

import io
import json
import threading
import urllib.error

import pytest

from full_album_maker import key_pool as key_pool_module
from full_album_maker.key_pool import GeminiKeyPool, KeyRecord


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error(code: int, body: str):
    return urllib.error.HTTPError(
        "https://example.invalid",
        code,
        "error",
        {},
        io.BytesIO(body.encode("utf-8")),
    )


def test_invalid_key_400_disables_and_rotates_to_next_key(tmp_path, monkeypatch):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.records = [
        KeyRecord(key="a" * 32, label="Key #01"),
        KeyRecord(key="b" * 32, label="Key #02"),
    ]
    pool.save()
    events = [
        _http_error(400, '{"error":{"message":"API key not valid. Please pass a valid API key."}}'),
        _Response({"ok": True}),
    ]
    seen_keys: list[str] = []

    def fake_urlopen(request, timeout):
        seen_keys.append(request.get_header("X-goog-api-key"))
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)

    result = pool.request_json("https://example.invalid", {})

    assert result == {"ok": True}
    assert seen_keys == ["a" * 32, "b" * 32]
    assert pool.records[0].enabled is False
    assert pool.records[1].enabled is True


def test_generic_400_does_not_burn_through_all_keys(tmp_path, monkeypatch):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.records = [
        KeyRecord(key="a" * 32, label="Key #01"),
        KeyRecord(key="b" * 32, label="Key #02"),
    ]
    pool.save()
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise _http_error(400, '{"error":{"message":"Malformed function declaration"}}')

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Gemini HTTP 400"):
        pool.request_json("https://example.invalid", {})

    assert calls == 1
    assert pool.records[0].enabled is True
    assert pool.records[1].enabled is True


def test_corrupt_vault_is_quarantined_instead_of_silently_erased(tmp_path):
    vault = tmp_path / "gemini_keys.dat"
    vault.write_bytes(b"this-is-not-a-valid-vault")

    pool = GeminiKeyPool(vault)

    assert pool.records == []
    assert pool.last_load_error
    assert pool.quarantined_vault is not None
    assert pool.quarantined_vault.exists()
    assert pool.quarantined_vault.read_bytes() == b"this-is-not-a-valid-vault"
    assert not vault.exists()


def test_parallel_requests_reserve_different_ready_keys(tmp_path, monkeypatch):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.records = [
        KeyRecord(key="a" * 32, label="Key #01"),
        KeyRecord(key="b" * 32, label="Key #02"),
    ]
    pool.save()

    entered = threading.Barrier(2, timeout=5)
    seen_keys: list[str] = []
    seen_lock = threading.Lock()

    def fake_urlopen(request, timeout):
        key = request.get_header("X-goog-api-key")
        with seen_lock:
            seen_keys.append(key)
        entered.wait()
        return _Response({"key": key})

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)

    results: list[dict] = []
    errors: list[BaseException] = []

    def worker():
        try:
            results.append(pool.request_json("https://example.invalid", {}))
        except BaseException as exc:  # pragma: no cover - assertion reports it below
            errors.append(exc)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(results) == 2
    assert set(seen_keys) == {"a" * 32, "b" * 32}
    assert pool.summary()["ready"] == 2
