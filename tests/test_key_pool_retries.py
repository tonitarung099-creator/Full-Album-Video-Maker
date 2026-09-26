from __future__ import annotations

import io
import json
import time
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


def _http_error(code: int, body: str, headers: dict[str, str] | None = None):
    return urllib.error.HTTPError(
        "https://example.invalid",
        code,
        "error",
        headers or {},
        io.BytesIO(body.encode("utf-8")),
    )


def _pool(tmp_path) -> GeminiKeyPool:
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.records = [KeyRecord(key="k" * 32, label="Key #01")]
    pool.save = lambda: None
    return pool


def test_single_key_retries_503_then_recovers(tmp_path, monkeypatch):
    pool = _pool(tmp_path)
    events = [
        _http_error(503, '{"error":{"message":"high demand"}}'),
        _http_error(503, '{"error":{"message":"high demand"}}'),
        _Response({"ok": True}),
    ]
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(key_pool_module.time, "sleep", sleeps.append)

    result = pool.request_json(
        "https://example.invalid",
        {"hello": "world"},
        timeout=7,
    )

    assert result == {"ok": True}
    assert calls == [7, 7, 7]
    assert sleeps == [1.0, 2.0]
    assert pool.records[0].failures == 0
    assert pool.records[0].cooldown_until == 0.0


def test_single_key_exhausts_503_retries_before_popup(tmp_path, monkeypatch):
    pool = _pool(tmp_path)
    events = [
        _http_error(503, '{"error":{"message":"high demand"}}')
        for _ in range(4)
    ]
    sleeps: list[float] = []
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        raise events.pop(0)

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(key_pool_module.time, "sleep", sleeps.append)

    before = time.time()
    with pytest.raises(RuntimeError, match="Gemini HTTP 503"):
        pool.request_json("https://example.invalid", {})

    assert calls == 4
    assert sleeps == [1.0, 2.0, 4.0]
    assert pool.records[0].cooldown_until >= before + 19.0


def test_503_exhaustion_rotates_to_next_key(tmp_path, monkeypatch):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.records = [
        KeyRecord(key="a" * 32, label="Key #01"),
        KeyRecord(key="b" * 32, label="Key #02"),
    ]
    pool.save = lambda: None
    events = [
        _http_error(503, '{"error":{"message":"high demand"}}')
        for _ in range(4)
    ] + [_Response({"key2": "ok"})]
    seen_keys: list[str] = []

    def fake_urlopen(request, timeout):
        seen_keys.append(request.get_header("X-goog-api-key"))
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(key_pool_module.time, "sleep", lambda _seconds: None)

    result = pool.request_json("https://example.invalid", {})

    assert result == {"key2": "ok"}
    assert seen_keys[:4] == ["a" * 32] * 4
    assert seen_keys[4] == "b" * 32
    assert pool.records[0].cooldown_until > 0


def test_429_honors_retry_after_without_fast_retry(tmp_path, monkeypatch):
    pool = _pool(tmp_path)
    sleeps: list[float] = []
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        raise _http_error(
            429,
            '{"error":{"message":"quota"}}',
            {"Retry-After": "120"},
        )

    monkeypatch.setattr(key_pool_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(key_pool_module.time, "sleep", sleeps.append)

    before = time.time()
    with pytest.raises(RuntimeError, match="Gemini HTTP 429"):
        pool.request_json("https://example.invalid", {})

    assert calls == 1
    assert sleeps == []
    assert pool.records[0].cooldown_until >= before + 119.0
