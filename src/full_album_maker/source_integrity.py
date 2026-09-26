from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import playlist_feature as playlist_feature_module
from . import playlist_hardening as playlist_hardening_module
from . import timeline as timeline_module
from . import ui as ui_module
from . import visual_feature as visual_feature_module
from .project import Project

_installed = False
_originals: dict[str, Any] = {}


def _fingerprint(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    try:
        canonical = path.resolve(strict=False)
    except OSError:
        canonical = path.absolute()

    result: dict[str, Any] = {
        "path": str(canonical),
        "exists": False,
        "size": None,
        "mtime_ns": None,
        "dev": None,
        "ino": None,
    }
    try:
        stat = canonical.stat()
    except OSError:
        return result

    result.update(
        {
            "exists": True,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "dev": int(getattr(stat, "st_dev", 0) or 0),
            "ino": int(getattr(stat, "st_ino", 0) or 0),
        }
    )
    return result


def project_source_fingerprints(project: Project) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for kind, media_items in (
        ("video", project.videos),
        ("audio", project.audios),
        ("image", visual_feature_module.images(project)),
    ):
        for index, item in enumerate(media_items):
            items.append(
                {
                    "kind": kind,
                    "index": index,
                    "fingerprint": _fingerprint(item.path),
                }
            )
    return items


def source_integrity_signature(project: Project) -> str:
    base_signature = _originals.get("visual_signature")
    if base_signature is None:
        base_signature = visual_feature_module.visual_project_signature
    base = base_signature(project)
    payload = {
        "base": base,
        "source_fingerprints": project_source_fingerprints(project),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def install_source_integrity() -> None:
    global _installed
    if _installed:
        return

    _originals.update(
        {
            "visual_signature": visual_feature_module.visual_project_signature,
            "timeline_signature": timeline_module.project_signature,
            "ui_signature": ui_module.project_signature,
            "playlist_signature": playlist_feature_module.playlist_project_signature,
            "hardening_signature": playlist_hardening_module.playlist_project_signature,
        }
    )

    # These modules hold direct references to the active signature function.
    # Patch every runtime entrypoint so timeline creation, UI stale checks and
    # renderer validation all observe the same filesystem fingerprint.
    visual_feature_module.visual_project_signature = source_integrity_signature
    timeline_module.project_signature = source_integrity_signature
    ui_module.project_signature = source_integrity_signature
    playlist_feature_module.playlist_project_signature = source_integrity_signature
    playlist_hardening_module.playlist_project_signature = source_integrity_signature
    _installed = True


def uninstall_source_integrity() -> None:
    global _installed
    if not _installed:
        return
    visual_feature_module.visual_project_signature = _originals["visual_signature"]
    timeline_module.project_signature = _originals["timeline_signature"]
    ui_module.project_signature = _originals["ui_signature"]
    playlist_feature_module.playlist_project_signature = _originals["playlist_signature"]
    playlist_hardening_module.playlist_project_signature = _originals["hardening_signature"]
    _originals.clear()
    _installed = False
