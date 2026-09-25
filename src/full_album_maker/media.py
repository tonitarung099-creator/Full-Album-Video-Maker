from __future__ import annotations

import json
import subprocess
from pathlib import Path
from .paths import ffprobe_path

class MediaProbeError(RuntimeError):
    pass

def probe_duration(path: str) -> float:
    tool = ffprobe_path()
    if not tool:
        raise MediaProbeError("FFprobe tidak ditemukan. Pastikan tools/ffmpeg/ffprobe.exe tersedia.")
    target = Path(path)
    if not target.exists():
        raise MediaProbeError(f"File tidak ditemukan: {target}")
    cmd = [tool, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(target)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        payload = json.loads(proc.stdout or "{}")
        return float(payload["format"]["duration"])
    except Exception as exc:
        raise MediaProbeError(f"Gagal membaca durasi {target.name}: {exc}") from exc
