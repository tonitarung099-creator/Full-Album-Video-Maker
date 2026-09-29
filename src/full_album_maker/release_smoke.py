from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from .editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from .paths import app_root, ffmpeg_path, ffprobe_path, temp_dir
from .s11_render_graph import S11FFmpegCompiler


def _run(args: list[str] | tuple[str, ...], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
    )


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _write_report(payload: dict) -> Path:
    target = temp_dir() / "portable-smoke.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def run_portable_smoke() -> int:
    """Exercise the extracted frozen app without relying on global Python/FFmpeg/API.

    This intentionally renders a tiny real A/V output through the same S11/S12
    compiler used by the editor, probes both streams, then constructs the actual
    v1.4 Qt main window. It is a release gate, not a substitute for the full suite.
    """

    root = app_root().resolve()
    report: dict[str, object] = {
        "ok": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "app_root": str(root),
        "python_executable": str(Path(sys.executable).resolve()),
        "api_key_present": bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        ),
    }
    try:
        ffmpeg = Path(ffmpeg_path()).resolve()
        ffprobe = Path(ffprobe_path()).resolve()
        if not ffmpeg.exists() or not ffprobe.exists():
            raise RuntimeError("FFmpeg/ffprobe portable tidak ditemukan.")
        if getattr(sys, "frozen", False):
            if not _inside(ffmpeg, root) or not _inside(ffprobe, root):
                raise RuntimeError("Smoke portable memakai FFmpeg dari luar folder aplikasi.")

        _run([str(ffmpeg), "-version"], timeout=15)
        _run([str(ffprobe), "-version"], timeout=15)

        work = temp_dir() / "release-smoke-work"
        work.mkdir(parents=True, exist_ok=True)
        tone = work / "smoke-tone.wav"
        output = work / "smoke-output.mp4"
        _run(
            [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=523.25:duration=0.20",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(tone),
            ],
            timeout=20,
        )

        duration_tick = seconds_to_tick(0.20)
        doc = ProjectDocument.new_empty("Portable Smoke")
        doc.canvas.width = 320
        doc.canvas.height = 240
        asset = MediaAsset(
            kind="audio",
            locator=str(tone),
            original_name=tone.name,
            source_duration_tick=duration_tick,
        )
        doc.media.append(asset)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                display_title="Portable Smoke",
                source_out_tick=duration_tick,
            )
        )
        doc.validate()
        compiled = S11FFmpegCompiler(str(ffmpeg)).compile_video(
            doc,
            output,
            work / "compile",
        )
        _run(compiled.args, timeout=30)
        if not output.exists() or output.stat().st_size <= 0:
            raise RuntimeError("Render smoke portable tidak menghasilkan output.")

        probe = _run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(output),
            ],
            timeout=15,
        )
        probe_json = json.loads(probe.stdout)
        stream_types = sorted(
            item.get("codec_type", "") for item in probe_json.get("streams", [])
        )
        duration = float(probe_json.get("format", {}).get("duration", 0.0))
        if "audio" not in stream_types or "video" not in stream_types:
            raise RuntimeError("Output smoke portable tidak memiliki audio dan video.")
        if not 0.15 <= duration <= 0.50:
            raise RuntimeError(f"Durasi output smoke tidak wajar: {duration}")

        from PySide6.QtWidgets import QApplication
        from .v14_window import V14EditorMainWindow

        app = QApplication.instance() or QApplication([])
        window = V14EditorMainWindow()
        window.show()
        app.processEvents()
        gui_title = window.windowTitle()
        ai_parity = type(window._ai_context_builder).__name__ == "V14EditorAIContextBuilder"
        window.hide()
        window.deleteLater()
        app.processEvents()
        if not ai_parity:
            raise RuntimeError("Smoke portable tidak memakai AI context v1.4.")

        report.update(
            {
                "ok": True,
                "ffmpeg": str(ffmpeg),
                "ffprobe": str(ffprobe),
                "output": str(output),
                "output_bytes": output.stat().st_size,
                "output_duration_seconds": duration,
                "output_streams": stream_types,
                "gui_title": gui_title,
                "ai_parity": ai_parity,
            }
        )
        target = _write_report(report)
        print(f"PORTABLE_SMOKE_OK {target}")
        return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        target = _write_report(report)
        print(f"PORTABLE_SMOKE_FAILED {target}: {report['error']}", file=sys.stderr)
        return 2
