from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import secure_dir

MAX_KEYS = 100

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
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]

def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf

def _configure_dpapi():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_ptr = ctypes.POINTER(_DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [
        blob_ptr, ctypes.wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.wintypes.DWORD, blob_ptr,
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_ptr, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.wintypes.DWORD, blob_ptr,
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
    ok = crypt32.CryptProtectData(ctypes.byref(in_blob), "FullAlbumMaker", None, None, None, 0, ctypes.byref(out_blob))
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
    ok = crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)

class GeminiKeyPool:
    def __init__(self, vault_path: Path | None = None) -> None:
        self.vault_path = vault_path or (secure_dir() / "gemini_keys.dat")
        self.records: list[KeyRecord] = []
        self._cursor = 0
        self.load()

    def load(self) -> None:
        if not self.vault_path.exists():
            self.records = []
            return
        try:
            raw = _dpapi_decrypt(self.vault_path.read_bytes())
            items = json.loads(raw.decode("utf-8"))
            self.records = [KeyRecord(**x) for x in items][:MAX_KEYS]
        except Exception:
            self.records = []

    def save(self) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps([asdict(r) for r in self.records], ensure_ascii=False).encode("utf-8")
        self.vault_path.write_bytes(_dpapi_encrypt(raw))

    def add_keys(self, values: list[str]) -> tuple[int, int]:
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
            self.records.append(KeyRecord(key=key, label=f"Key #{start + offset:02d}"))
        self.save()
        return len(accepted), max(0, len(cleaned) - len(accepted))

    def remove(self, index: int) -> None:
        del self.records[index]
        self.save()

    def summary(self) -> dict[str, int]:
        now = time.time()
        return {
            "total": len(self.records),
            "ready": sum(1 for r in self.records if r.enabled and now >= r.cooldown_until),
            "cooldown": sum(1 for r in self.records if r.enabled and now < r.cooldown_until),
            "disabled": sum(1 for r in self.records if not r.enabled),
        }

    def _next(self) -> tuple[int, KeyRecord]:
        if not self.records:
            raise RuntimeError("Belum ada Gemini API/Auth key.")
        count = len(self.records)
        for offset in range(count):
            idx = (self._cursor + offset) % count
            rec = self.records[idx]
            if rec.available:
                self._cursor = (idx + 1) % count
                return idx, rec
        soonest = min((r.cooldown_until for r in self.records if r.enabled), default=0)
        wait = max(0, int(soonest - time.time()))
        raise RuntimeError(f"Semua key sedang tidak tersedia. Coba lagi sekitar {wait} detik.")

    def request_json(self, url: str, payload: dict[str, Any], attempts: int | None = None, timeout: int = 90) -> dict[str, Any]:
        if not self.records:
            raise RuntimeError("Belum ada Gemini API/Auth key.")

        now = time.time()
        count = len(self.records)
        ordered_indices = [
            (self._cursor + offset) % count
            for offset in range(count)
            if self.records[(self._cursor + offset) % count].enabled
            and now >= self.records[(self._cursor + offset) % count].cooldown_until
        ]

        if not ordered_indices:
            enabled = [r for r in self.records if r.enabled]
            if not enabled:
                raise RuntimeError("Semua Gemini key sedang nonaktif.")
            soonest = min(r.cooldown_until for r in enabled)
            wait = max(0, int(soonest - now))
            raise RuntimeError(f"Semua key sedang cooldown. Coba lagi sekitar {wait} detik.")

        if attempts is not None:
            ordered_indices = ordered_indices[:max(0, attempts)]

        last_error = "Tidak ada key yang dapat digunakan."

        for idx in ordered_indices:
            rec = self.records[idx]
            self._cursor = (idx + 1) % count
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": rec.key},
                method="POST",
            )
            rec.last_used = time.time()
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    rec.failures = 0
                    rec.last_error = ""
                    rec.cooldown_until = 0.0
                    self.save()
                    return result
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                rec.failures += 1
                rec.last_error = f"HTTP {exc.code}: {body}"
                last_error = f"Gemini HTTP {exc.code}: {body[:180]}"

                if exc.code == 429:
                    rec.cooldown_until = time.time() + 60
                elif exc.code == 401:
                    rec.enabled = False
                elif exc.code == 403:
                    rec.cooldown_until = time.time() + 300
                elif 500 <= exc.code <= 599:
                    rec.cooldown_until = time.time() + 20
                else:
                    self.save()
                    raise RuntimeError(last_error) from exc
                self.save()
            except (urllib.error.URLError, TimeoutError) as exc:
                rec.failures += 1
                rec.last_error = str(exc)
                rec.cooldown_until = time.time() + 10
                last_error = f"Gemini jaringan: {exc}"
                self.save()

        raise RuntimeError(last_error)
