from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_bytes
from .paths import secure_dir

MAX_KEYS = 100
TRANSIENT_SERVER_RETRIES = 3
TRANSIENT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


@dataclass
class KeyRecord:
    key: str
    label: str
    enabled: bool = True
    cooldown_until: float = 0.0
    failures: int = 0
    last_error: str = ""
    last_used: float = 0.0

    @property
    def masked(self) -> str:
        if len(self.key) <= 10:
            return "••••••"
        return f"{self.key[:5]}••••••••{self.key[-4:]}"

    @property
    def available(self) -> bool:
        return self.enabled and time.time() >= self.cooldown_until


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data)
    return (
        _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))),
        buf,
    )


def _configure_dpapi():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_ptr = ctypes.POINTER(_DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [
        blob_ptr,
        ctypes.wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        blob_ptr,
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_ptr,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        blob_ptr,
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _dpapi_encrypt(data: bytes) -> bytes:
    if os.name != "nt":
        return b"DEV0" + data
    crypt32, kernel32 = _configure_dpapi()
    in_blob, keep = _blob(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "FullAlbumMaker",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    if os.name != "nt":
        if not data.startswith(b"DEV0"):
            raise RuntimeError("Vault hanya bisa dibuka pada Windows yang membuatnya.")
        return data[4:]
    crypt32, kernel32 = _configure_dpapi()
    in_blob, keep = _blob(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _retry_after_seconds(
    exc: urllib.error.HTTPError,
    default: float,
    *,
    max_seconds: float,
) -> float:
    """Read numeric Retry-After with a caller-controlled upper bound."""
    headers = getattr(exc, "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is not None:
        try:
            value = float(str(raw).strip())
            if value >= 0:
                return min(max_seconds, max(0.25, value))
        except (TypeError, ValueError):
            pass
    return min(max_seconds, max(0.25, float(default)))


def _invalid_key_response(code: int, body: str) -> bool:
    """Return True only when an HTTP error clearly identifies the API key itself.

    A generic HTTP 400 is usually a bad request/schema and must *not* burn through
    every key. Conversely, Gemini commonly reports an invalid/revoked key as 400,
    401, or 403 depending on endpoint and account state.
    """

    if code == 401:
        return True
    if code not in {400, 403}:
        return False
    text = body.casefold()
    markers = (
        "api key not valid",
        "api_key_invalid",
        "invalid api key",
        "invalid api_key",
        "invalid key",
        "key not valid",
        "key was reported as leaked",
        "api key expired",
        "api key has been revoked",
    )
    return any(marker in text for marker in markers)


class GeminiKeyPool:
    """Thread-safe local Gemini key pool with defensive failover.

    Network I/O and backoff sleeps deliberately happen *without* holding the
    state lock. A key is marked in-flight while a request uses it so concurrent
    agent requests prefer different ready keys instead of racing the same key.
    """

    def __init__(self, vault_path: Path | None = None) -> None:
        self.vault_path = vault_path or (secure_dir() / "gemini_keys.dat")
        self.records: list[KeyRecord] = []
        self._cursor = 0
        self._lock = threading.RLock()
        self._inflight_keys: set[str] = set()
        self.last_load_error = ""
        self.quarantined_vault: Path | None = None
        self.load()

    def _quarantine_corrupt_vault(self, reason: Exception) -> None:
        self.last_load_error = f"Vault Gemini tidak dapat dibuka: {reason}"
        self.quarantined_vault = None
        if not self.vault_path.exists():
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = self.vault_path.with_name(
            f"{self.vault_path.name}.corrupt-{stamp}"
        )
        serial = 1
        while candidate.exists():
            candidate = self.vault_path.with_name(
                f"{self.vault_path.name}.corrupt-{stamp}-{serial}"
            )
            serial += 1
        try:
            self.vault_path.replace(candidate)
            self.quarantined_vault = candidate
            self.last_load_error += f" File lama dikarantina sebagai {candidate.name}."
        except OSError as exc:
            self.last_load_error += f" Gagal mengarantina file lama: {exc}"

    def load(self) -> None:
        with self._lock:
            self.last_load_error = ""
            self.quarantined_vault = None
            if not self.vault_path.exists():
                self.records = []
                self._cursor = 0
                return
            try:
                raw = _dpapi_decrypt(self.vault_path.read_bytes())
                items = json.loads(raw.decode("utf-8"))
                if not isinstance(items, list):
                    raise ValueError("isi vault bukan daftar key")
                records = [KeyRecord(**x) for x in items][:MAX_KEYS]
                if any(not isinstance(record.key, str) or not record.key for record in records):
                    raise ValueError("vault berisi key tidak valid")
                self.records = records
                self._cursor = 0
            except Exception as exc:
                self._quarantine_corrupt_vault(exc)
                self.records = []
                self._cursor = 0

    def _save_locked(self) -> None:
        raw = json.dumps(
            [asdict(r) for r in self.records],
            ensure_ascii=False,
        ).encode("utf-8")
        atomic_write_bytes(self.vault_path, _dpapi_encrypt(raw))

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def add_keys(self, values: list[str]) -> tuple[int, int]:
        with self._lock:
            cleaned = []
            seen = {r.key for r in self.records}
            for value in values:
                key = value.strip()
                if len(key) < 20 or key in seen:
                    continue
                seen.add(key)
                cleaned.append(key)
            room = MAX_KEYS - len(self.records)
            accepted = cleaned[:room]
            start = len(self.records) + 1
            for offset, key in enumerate(accepted):
                self.records.append(
                    KeyRecord(key=key, label=f"Key #{start + offset:02d}")
                )
            self._save_locked()
            return len(accepted), max(0, len(cleaned) - len(accepted))

    def remove(self, index: int) -> None:
        with self._lock:
            if not 0 <= index < len(self.records):
                raise IndexError("Index Gemini key tidak valid.")
            removed = self.records.pop(index)
            self._inflight_keys.discard(removed.key)
            if self.records:
                self._cursor %= len(self.records)
            else:
                self._cursor = 0
            self._save_locked()

    def summary(self) -> dict[str, int]:
        with self._lock:
            now = time.time()
            return {
                "total": len(self.records),
                "ready": sum(
                    1
                    for r in self.records
                    if r.enabled
                    and now >= r.cooldown_until
                    and r.key not in self._inflight_keys
                ),
                "cooldown": sum(
                    1
                    for r in self.records
                    if r.enabled and now < r.cooldown_until
                ),
                "disabled": sum(1 for r in self.records if not r.enabled),
            }

    def _next(self) -> tuple[int, KeyRecord]:
        with self._lock:
            if not self.records:
                raise RuntimeError("Belum ada Gemini API/Auth key.")
            count = len(self.records)
            for offset in range(count):
                idx = (self._cursor + offset) % count
                rec = self.records[idx]
                if rec.available and rec.key not in self._inflight_keys:
                    self._cursor = (idx + 1) % count
                    return idx, rec
            enabled = [r for r in self.records if r.enabled]
            if not enabled:
                raise RuntimeError("Semua Gemini key sedang nonaktif.")
            non_inflight = [r for r in enabled if r.key not in self._inflight_keys]
            if not non_inflight:
                raise RuntimeError("Semua Gemini key siap sedang dipakai request lain.")
            soonest = min((r.cooldown_until for r in non_inflight), default=0)
            wait = max(0, int(soonest - time.time()))
            raise RuntimeError(
                f"Semua key sedang tidak tersedia. Coba lagi sekitar {wait} detik."
            )

    def _reserve_next(
        self,
        excluded_keys: set[str],
    ) -> tuple[KeyRecord | None, str | None]:
        with self._lock:
            if not self.records:
                return None, "Belum ada Gemini API/Auth key."
            now = time.time()
            count = len(self.records)
            for offset in range(count):
                idx = (self._cursor + offset) % count
                rec = self.records[idx]
                if (
                    rec.key not in excluded_keys
                    and rec.key not in self._inflight_keys
                    and rec.enabled
                    and now >= rec.cooldown_until
                ):
                    self._inflight_keys.add(rec.key)
                    self._cursor = (idx + 1) % count
                    return rec, None

            eligible = [
                rec
                for rec in self.records
                if rec.key not in excluded_keys and rec.enabled
            ]
            if not eligible:
                if any(rec.enabled for rec in self.records):
                    return None, None
                return None, "Semua Gemini key sedang nonaktif."

            not_inflight = [
                rec for rec in eligible if rec.key not in self._inflight_keys
            ]
            if not not_inflight:
                return None, "Semua Gemini key siap sedang dipakai request lain."
            soonest = min(rec.cooldown_until for rec in not_inflight)
            wait = max(0, int(soonest - now))
            return None, f"Semua key sedang cooldown. Coba lagi sekitar {wait} detik."

    def _release_key(self, key: str) -> None:
        with self._lock:
            self._inflight_keys.discard(key)

    def _persist_record_state(self) -> None:
        with self._lock:
            self._save_locked()

    def request_json(
        self,
        url: str,
        payload: dict[str, Any],
        attempts: int | None = None,
        timeout: int = 90,
    ) -> dict[str, Any]:
        with self._lock:
            if not self.records:
                raise RuntimeError("Belum ada Gemini API/Auth key.")
            max_key_attempts = (
                max(0, min(int(attempts), len(self.records)))
                if attempts is not None
                else len(self.records)
            )

        if max_key_attempts <= 0:
            raise RuntimeError("Tidak ada key yang diizinkan untuk dicoba.")

        excluded_keys: set[str] = set()
        last_error = "Tidak ada key yang dapat digunakan."
        keys_tried = 0

        while keys_tried < max_key_attempts:
            rec, unavailable = self._reserve_next(excluded_keys)
            if rec is None:
                if unavailable:
                    if keys_tried == 0:
                        raise RuntimeError(unavailable)
                    last_error = unavailable
                break

            keys_tried += 1
            excluded_keys.add(rec.key)
            transient_retry = 0
            rotate_to_next_key = False

            try:
                while True:
                    request = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": rec.key,
                        },
                        method="POST",
                    )
                    with self._lock:
                        rec.last_used = time.time()
                    try:
                        with urllib.request.urlopen(
                            request,
                            timeout=timeout,
                        ) as response:
                            result = json.loads(response.read().decode("utf-8"))
                        with self._lock:
                            rec.failures = 0
                            rec.last_error = ""
                            rec.cooldown_until = 0.0
                            self._save_locked()
                        return result
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode(
                            "utf-8",
                            errors="replace",
                        )[:500]
                        with self._lock:
                            rec.failures += 1
                            rec.last_error = f"HTTP {exc.code}: {body}"
                        last_error = f"Gemini HTTP {exc.code}: {body[:180]}"

                        if _invalid_key_response(exc.code, body):
                            with self._lock:
                                rec.enabled = False
                                rec.cooldown_until = 0.0
                                self._save_locked()
                            rotate_to_next_key = True
                            break

                        if 500 <= exc.code <= 599:
                            if transient_retry < TRANSIENT_SERVER_RETRIES:
                                fallback = TRANSIENT_BACKOFF_SECONDS[
                                    min(
                                        transient_retry,
                                        len(TRANSIENT_BACKOFF_SECONDS) - 1,
                                    )
                                ]
                                delay = _retry_after_seconds(
                                    exc,
                                    fallback,
                                    max_seconds=15.0,
                                )
                                transient_retry += 1
                                self._persist_record_state()
                                time.sleep(delay)
                                continue
                            with self._lock:
                                rec.cooldown_until = time.time() + 20
                                self._save_locked()
                            rotate_to_next_key = True
                            break

                        if exc.code == 429:
                            with self._lock:
                                rec.cooldown_until = time.time() + _retry_after_seconds(
                                    exc,
                                    60.0,
                                    max_seconds=300.0,
                                )
                                self._save_locked()
                            rotate_to_next_key = True
                            break

                        if exc.code == 403:
                            # A permission/quota restriction can be key/account specific.
                            # Cool this key down and let another configured key try.
                            with self._lock:
                                rec.cooldown_until = time.time() + 300
                                self._save_locked()
                            rotate_to_next_key = True
                            break

                        # A generic client/schema error is independent of the key.
                        # Retrying all 100 keys would only waste quota and obscure it.
                        self._persist_record_state()
                        raise RuntimeError(last_error) from exc
                    except (urllib.error.URLError, TimeoutError) as exc:
                        with self._lock:
                            rec.failures += 1
                            rec.last_error = str(exc)
                            rec.cooldown_until = time.time() + 10
                            self._save_locked()
                        last_error = f"Gemini jaringan: {exc}"
                        rotate_to_next_key = True
                        break
            finally:
                self._release_key(rec.key)

            if not rotate_to_next_key:
                break

        raise RuntimeError(last_error)
