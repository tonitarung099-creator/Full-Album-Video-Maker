from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from full_album_maker import __version__


FFMPEG = {
    "provider": "BtbN/FFmpeg-Builds",
    "release_id": 398275969,
    "asset_id": 595476894,
    "asset_name": "ffmpeg-n9.0-latest-win64-gpl-9.0.zip",
    "sha256": "e6db684f1527f4c2280b017c7af19ebd359424eee8b35974bc35b4d7ee110989",
    "version_family": "9.0",
    "download_strategy": "github_release_asset_api_id",
}

PYTHON_BUILD = {
    "python": "3.12.10",
    "pip": "26.2.1",
    "PySide6": "6.11.2",
    "PyInstaller": "6.22.3",
    "pytest": "8.4.2",
    "Pillow": "11.3.0",
}

FONT = {
    "family": "Noto Sans",
    "source": "google/fonts",
    "commit": "23e54b51ddffbc7713c583748e3bd86f62b1fa4a",
    "path": "ofl/notosans/NotoSans[wdth,wght].ttf",
    "license": "SIL Open Font License 1.1",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", default="CAPABILITIES.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = root / args.output

    payload = {
        "format": "full-album-maker-capability-report",
        "version": 1,
        "app_version": __version__,
        "release_tag": f"v{__version__}",
        "build_commit": os.environ.get("GITHUB_SHA", "unknown"),
        "platform": "Windows x86_64 portable onedir",
        "offline_manual_workflow": True,
        "api_key_required_for_manual_edit_preview_render": False,
        "global_python_required": False,
        "global_ffmpeg_required": False,
        "bundled": {
            "ffmpeg": FFMPEG,
            "python_build": PYTHON_BUILD,
            "font": FONT,
        },
        "features": {
            "packed_timeline": "supported",
            "free_timeline_gap_silence": "supported",
            "free_timeline_explicit_crossfade": "supported",
            "spectrum_mixed_audio_parity": "supported",
            "circular_spectrum": "supported; showfreqs + bounded polar geq remap",
            "circular_spectrum_internal_side_max": 512,
            "ten_builtin_templates": "supported",
            "custom_templates": "supported",
            "bulk_song_cover_manager": "supported",
            "ai_editor": "optional; requires configured provider key only for AI actions",
        },
        "s12_validation": {
            "long_project_model": "200 songs x 54 seconds = 3 hours",
            "long_project_scope": [
                "timeline resolve",
                "render-plan compile",
                "FFmpeg graph generation",
                "Windows command-line length gate",
            ],
            "portable_zip_smoke": [
                "relocated Unicode/space/apostrophe path",
                "no global Python on PATH",
                "no global FFmpeg on PATH",
                "no Gemini/Google API key",
                "real bundled-FFmpeg A/V render",
                "ffprobe audio+video verification",
                "Qt main-window construction",
            ],
        },
        "limitations": [
            "CI does not fully encode a three-hour album; it compile-stresses the 200-song/3-hour project and separately performs short real FFmpeg renders.",
            "Circular Spectrum bounds the expensive polar remap to at most 512x512 pixels before scaling to the requested layer box.",
            "User-selected custom font_path assets remain the user's responsibility; the portable build bundles Noto Sans as its deterministic fallback font asset.",
            "AI actions are unavailable without an API key, while manual editing/template/preview/render remain available offline.",
        ],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
