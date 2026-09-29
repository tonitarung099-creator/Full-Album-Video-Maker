from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tomllib

from full_album_maker import __version__
from full_album_maker.project_dirty import _update_window_title


ROOT = Path(__file__).resolve().parents[1]


def test_stable_version_is_consistent_across_package_metadata():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == "1.0.1"
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


def test_capability_report_records_release_identity(tmp_path: Path):
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


def test_release_workflow_is_gated_versioned_and_checksummed():
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

    assert "Full-Album-Maker-v$Version-Windows-Portable.zip" in local_build
    assert "gui_title -notlike \"*v$Version*\"" in local_build
    assert '$ChecksumFile = "$Root\\SHA256SUMS.txt"' in local_build
    assert "SHA256SUMS.txt tidak cocok" in local_build
