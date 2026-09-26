from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import ui as ui_module
from .paths import output_dir
from .project_io import save_project

_installed = False
_originals: dict[str, Any] = {}


def _project_state(project) -> str:
    payload = project.to_dict()
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_project_dirty(self) -> bool:
    saved = getattr(self, "_saved_project_state", None)
    if saved is None:
        return False
    try:
        return _project_state(self.project) != saved
    except Exception:
        # If serialization itself becomes invalid, treat it as unsaved instead
        # of silently allowing destructive close/open operations.
        return True


def _update_window_title(self) -> None:
    name = "Full Album Maker"
    current_path = str(getattr(self, "_current_project_path", "") or "")
    if current_path:
        name += f" — {Path(current_path).name}"
    if self.is_project_dirty():
        name += " *"
    self.setWindowTitle(name)


def _patched_init(self, *args, **kwargs) -> None:
    # refresh() can be called by lower layers while __init__ is still running.
    self._saved_project_state = None
    self._current_project_path = ""
    _originals["ui_init"](self, *args, **kwargs)
    self._saved_project_state = _project_state(self.project)
    _update_window_title(self)


def _patched_refresh(self, *args, **kwargs):
    result = _originals["refresh"](self, *args, **kwargs)
    _update_window_title(self)
    return result


def _patched_save_project_file(self) -> bool:
    default = str(
        getattr(self, "_current_project_path", "")
        or (output_dir() / "Full_Album_Project.json")
    )
    path, _ = QFileDialog.getSaveFileName(
        self,
        "Simpan Proyek",
        default,
        "Full Album Project (*.json)",
    )
    if not path:
        return False

    try:
        save_project(path, self.project)
    except Exception as exc:
        self._error(f"Gagal menyimpan proyek: {exc}")
        return False

    self._current_project_path = path
    self._saved_project_state = _project_state(self.project)
    self.refresh()
    if hasattr(self, "log"):
        self.log.appendPlainText(f"Proyek disimpan: {path}")
    return True


def _confirm_unsaved(self, action_text: str) -> bool:
    if not self.is_project_dirty():
        return True

    answer = QMessageBox.question(
        self,
        "Perubahan belum disimpan",
        "Proyek memiliki perubahan yang belum disimpan.\n\n"
        f"Simpan sebelum {action_text}?",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        QMessageBox.Save,
    )
    if answer == QMessageBox.Cancel:
        return False
    if answer == QMessageBox.Save:
        return bool(self.save_project_file())
    return True


def _patched_load_project_file(self) -> bool:
    if getattr(self, "render_busy", False):
        self._error(
            "Tidak dapat membuka proyek lain saat render masih berjalan. "
            "Selesaikan atau batalkan render terlebih dahulu."
        )
        return False
    if not _confirm_unsaved(self, "membuka proyek lain"):
        return False

    previous_project = self.project
    _originals["load_project_file"](self)
    if self.project is previous_project:
        return False

    # The lower UI layer owns the file dialog, so this wrapper may not know the
    # selected path. The loaded content itself is nevertheless the new clean
    # baseline; Save keeps its existing Save-As behavior.
    self._current_project_path = ""
    self._saved_project_state = _project_state(self.project)
    self.refresh()
    return True


def _patched_close_event(self, event) -> None:
    # Render lifecycle owns the first stage of close: it must terminate/wait for
    # FFmpeg before any project-discard decision can actually close the process.
    if getattr(self, "render_busy", False):
        _originals["close_event"](self, event)
        return

    if not _confirm_unsaved(self, "menutup aplikasi"):
        event.ignore()
        return
    _originals["close_event"](self, event)


def install_project_dirty_state() -> None:
    global _installed
    if _installed:
        return
    MainWindow = ui_module.MainWindow
    _originals.update(
        {
            "ui_init": MainWindow.__init__,
            "refresh": MainWindow.refresh,
            "save_project_file": MainWindow.save_project_file,
            "load_project_file": MainWindow.load_project_file,
            "close_event": MainWindow.closeEvent,
        }
    )

    MainWindow.__init__ = _patched_init
    MainWindow.refresh = _patched_refresh
    MainWindow.save_project_file = _patched_save_project_file
    MainWindow.load_project_file = _patched_load_project_file
    MainWindow.closeEvent = _patched_close_event
    MainWindow.is_project_dirty = _is_project_dirty
    _installed = True


def uninstall_project_dirty_state() -> None:
    global _installed
    if not _installed:
        return
    MainWindow = ui_module.MainWindow
    MainWindow.__init__ = _originals["ui_init"]
    MainWindow.refresh = _originals["refresh"]
    MainWindow.save_project_file = _originals["save_project_file"]
    MainWindow.load_project_file = _originals["load_project_file"]
    MainWindow.closeEvent = _originals["close_event"]
    if hasattr(MainWindow, "is_project_dirty"):
        delattr(MainWindow, "is_project_dirty")
    _originals.clear()
    _installed = False
