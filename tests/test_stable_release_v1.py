from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tomllib

from full_album_maker import __version__
from full_album_maker.project_dirty import _update_window_title


ROOT = Path(__file__).resolve().parents[1]
FFMPEG_ASSET_ID = "595476894"
FFMPEG_SHA256 = "e6db684f1527f4c2280b017c7af19ebd359424eee8b35974bc35b4d7ee110989"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_stable_version_is_consistent_across_package_metadata():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == "1.3.0"
    assert pyproject["project"]["version"] == __version__
    assert (ROOT / f"docs/RELEASE_NOTES_v{__version__}.md").exists()


def test_window_title_exposes_stable_version():
    class DummyWindow:
        _current_project_path = ""

        def is_project_dirty(self) -> bool:
            return False

        def setWindowTitle(self, value: str) -> None:
            self.title = value

    window = DummyWindow()
    _update_window_title(window)
    assert window.title == f"Full Album Maker v{__version__}"


def test_capability_report_records_release_identity_and_immutable_ffmpeg_pin(tmp_path: Path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "build" / "write_release_capabilities.py"),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
    )
    payload = json.loads((tmp_path / "CAPABILITIES.json").read_text(encoding="utf-8"))
    assert payload["app_version"] == __version__
    assert payload["release_tag"] == f"v{__version__}"
    ffmpeg = payload["bundled"]["ffmpeg"]
    assert str(ffmpeg["asset_id"]) == FFMPEG_ASSET_ID
    assert ffmpeg["sha256"] == FFMPEG_SHA256
    assert ffmpeg["download_strategy"] == "github_release_asset_api_id"


def test_release_workflow_is_gated_versioned_checksummed_and_immutable():
    workflow = (ROOT / ".github" / "workflows" / "build-windows-portable.yml").read_text(
        encoding="utf-8"
    )
    local_build = (ROOT / "build" / "build_portable.ps1").read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "Full-Album-Maker-v$version-Windows-Portable.zip" in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "gh release create $tag $env:RELEASE_ZIP SHA256SUMS.txt" in workflow
    assert "docs/RELEASE_NOTES_$tag.md" in workflow
    assert "gui_title -notlike \"*v$env:APP_VERSION*\"" in workflow
    assert 'Set-Content -Path "SHA256SUMS.txt" -Encoding ascii' in workflow
    assert "SHA256SUMS.txt tidak cocok" in workflow

    assert f"actions/checkout@{CHECKOUT_SHA}" in workflow
    assert f"actions/setup-python@{SETUP_PYTHON_SHA}" in workflow
    assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in workflow
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" not in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" not in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" not in workflow

    asset_api_base = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/assets/"
    assert asset_api_base in workflow
    assert asset_api_base in local_build
    assert f'ffmpegAssetId = "{FFMPEG_ASSET_ID}"' in workflow
    assert f'FfmpegAssetId = "{FFMPEG_ASSET_ID}"' in local_build
    assert FFMPEG_SHA256 in workflow
    assert FFMPEG_SHA256 in local_build
    assert "/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip" not in workflow
    assert "/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip" not in local_build

    assert "Full-Album-Maker-v$Version-Windows-Portable.zip" in local_build
    assert "gui_title -notlike \"*v$Version*\"" in local_build
    assert '$ChecksumFile = "$Root\\SHA256SUMS.txt"' in local_build
    assert "SHA256SUMS.txt tidak cocok" in local_build
