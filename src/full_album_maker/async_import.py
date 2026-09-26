from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

from . import ui as ui_module
from . import visual_feature as visual_feature_module
from .media import MediaProbeError, probe_duration
from .project import MediaItem

_installed = False
_originals: dict[str, Any] = {}


class _ImportBridge(QObject):
    finished = Signal(object)


def _path_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False)).casefold()
    except OSError:
        return str(Path(path).expanduser().absolute()).casefold()


def _target_paths(window, kind: str) -> set[str]:
    if kind == "video":
        items = window.project.videos
    elif kind == "audio":
        items = window.project.audios
    elif kind == "image":
        items = visual_feature_module.images(window.project)
    else:
        items = []
    return {_path_key(item.path) for item in items}


def _probe_one(kind: str, path: str) -> MediaItem:
    if kind == "video":
        return MediaItem(path=path, duration=probe_duration(path, "video"))

    if kind == "audio":
        item = MediaItem(path=path, duration=probe_duration(path, "audio"))
        title, artist = visual_feature_module.probe_audio_tags(path)
        if title:
            setattr(item, "display_title", title)
        if artist:
            setattr(item, "display_artist", artist)
        setattr(item, "metadata_probed", True)
        return item

    if kind == "image":
        info = visual_feature_module.probe_image(path)
        item = MediaItem(path=path, duration=0.0)
        setattr(item, "width", int(info["width"]))
        setattr(item, "height", int(info["height"]))
        return item

    raise ValueError(f"Jenis media tidak dikenal: {kind}")


def _start_import(window, kind: str, paths: list[str]) -> None:
    if not paths:
        return

    current = _target_paths(window, kind)
    pending: set[str] = window._import_pending_keys
    selected: list[str] = []
    skipped = 0
    for raw in paths:
        path = str(raw).strip()
        if not path:
            continue
        key = _path_key(path)
        if key in current or key in pending:
            skipped += 1
            continue
        pending.add(key)
        selected.append(path)

    if skipped:
        window.log.appendPlainText(f"{skipped} file duplikat/pending dilewati saat impor.")
    if not selected:
        return

    project_ref = window.project
    window._import_job_count += 1
    window.log.appendPlainText(
        f"Impor {kind} dimulai di background: {len(selected)} file. UI tetap dapat digunakan."
    )

    def work() -> None:
        items: list[MediaItem] = []
        errors: list[str] = []
        try:
            for path in selected:
                try:
                    items.append(_probe_one(kind, path))
                except (MediaProbeError, ValueError, OSError) as exc:
                    errors.append(str(exc))
                except Exception as exc:  # defensive boundary around codec/decoder tools
                    errors.append(f"Gagal membaca {Path(path).name}: {exc}")
        finally:
            window._import_bridge.finished.emit(
                {
                    "kind": kind,
                    "paths": selected,
                    "items": items,
                    "errors": errors,
                    "project_ref": project_ref,
                }
            )

    threading.Thread(target=work, daemon=True, name=f"fam-import-{kind}").start()


def _finish_import(self, payload: dict[str, Any]) -> None:
    kind = str(payload.get("kind", ""))
    paths = [str(x) for x in payload.get("paths", [])]
    items = list(payload.get("items", []))
    errors = [str(x) for x in payload.get("errors", [])]
    project_ref = payload.get("project_ref")

    for path in paths:
        self._import_pending_keys.discard(_path_key(path))
    self._import_job_count = max(0, int(self._import_job_count) - 1)

    if self.project is not project_ref:
        self.log.appendPlainText(
            f"Hasil impor {kind} diabaikan karena proyek aktif sudah berganti."
        )
        return

    existing = _target_paths(self, kind)
    accepted: list[MediaItem] = []
    for item in items:
        key = _path_key(item.path)
        if key in existing:
            continue
        existing.add(key)
        accepted.append(item)

    if kind == "video":
        self.project.videos.extend(accepted)
    elif kind == "audio":
        self.project.audios.extend(accepted)
    elif kind == "image":
        visual_feature_module.images(self.project).extend(accepted)

    if kind in {"video", "image"} and accepted:
        order = getattr(self.project, "_visual_order", None)
        if not isinstance(order, list):
            order = []
            setattr(self.project, "_visual_order", order)
        known = {_path_key(value) for value in order}
        for item in accepted:
            key = _path_key(item.path)
            if key not in known:
                order.append(item.path)
                known.add(key)

    if accepted:
        self.invalidate_timeline()
        self.refresh()
        self.log.appendPlainText(
            f"Impor {kind} selesai: {len(accepted)} file ditambahkan ke proyek."
        )
    else:
        self.log.appendPlainText(f"Impor {kind} selesai tanpa file baru.")

    if errors:
        preview = "\n".join(f"• {message}" for message in errors[:8])
        more = f"\n• …dan {len(errors) - 8} error lain" if len(errors) > 8 else ""
        self.log.appendPlainText(
            f"{len(errors)} file gagal diimpor:\n{preview}{more}"
        )


def _patched_init(self, *args, **kwargs) -> None:
    self._import_pending_keys: set[str] = set()
    self._import_job_count = 0
    # Keep the bridge un-parented. If the window closes while a daemon import
    # worker is winding down, Qt can safely auto-disconnect the dead receiver
    # without the signal source itself having been deleted first.
    self._import_bridge = _ImportBridge()
    self._import_bridge.finished.connect(self._finish_media_import)
    _originals["ui_init"](self, *args, **kwargs)


def _add_video(self) -> None:
    paths, _ = QFileDialog.getOpenFileNames(
        self,
        "Pilih Footage",
        "",
        "Video (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.wmv)",
    )
    _start_import(self, "video", list(paths))


def _add_audio(self) -> None:
    paths, _ = QFileDialog.getOpenFileNames(
        self,
        "Pilih Lagu",
        "",
        "Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus)",
    )
    _start_import(self, "audio", list(paths))


def _add_image(self) -> None:
    paths, _ = QFileDialog.getOpenFileNames(
        self,
        "Pilih Foto Footage",
        "",
        "Foto (*.jpg *.jpeg *.png *.webp)",
    )
    _start_import(self, "image", list(paths))


def install_async_import() -> None:
    global _installed
    if _installed:
        return
    MainWindow = ui_module.MainWindow
    _originals.update(
        {
            "ui_init": MainWindow.__init__,
            "add_video": MainWindow.add_video,
            "add_audio": MainWindow.add_audio,
            "add_image": MainWindow.add_image,
        }
    )

    MainWindow.__init__ = _patched_init
    MainWindow.add_video = _add_video
    MainWindow.add_audio = _add_audio
    MainWindow.add_image = _add_image
    MainWindow._finish_media_import = _finish_import
    _installed = True


def uninstall_async_import() -> None:
    global _installed
    if not _installed:
        return
    MainWindow = ui_module.MainWindow
    MainWindow.__init__ = _originals["ui_init"]
    MainWindow.add_video = _originals["add_video"]
    MainWindow.add_audio = _originals["add_audio"]
    MainWindow.add_image = _originals["add_image"]
    if hasattr(MainWindow, "_finish_media_import"):
        delattr(MainWindow, "_finish_media_import")
    _originals.clear()
    _installed = False
