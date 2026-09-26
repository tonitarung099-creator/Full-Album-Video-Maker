from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from . import agent_actions as agent_actions_module
from . import timeline as timeline_module
from . import ui as ui_module
from .atomic_io import atomic_write_bytes
from .controller import ProjectController
from .playlist_feature import (
    PlaylistSelectionError,
    active_audio_items,
    get_active_audio_paths,
    playlist_project_signature,
    set_active_audio_paths,
)
from .project import Project

_installed = False
_originals: dict[str, Any] = {}


def _path_key(value: str) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


def _hardened_project_validation(self: Project) -> dict[str, list[str]]:
    """When a playlist is active, unused Media songs must not block rendering."""
    report = _originals["project_validation"](self)
    active = get_active_audio_paths(self)
    if not active:
        return report

    errors = list(report.get("errors", []))
    warnings = list(report.get("warnings", []))

    all_missing = [
        item
        for item in [*self.videos, *self.audios]
        if not Path(item.path).exists()
    ]
    generic_missing = f"{len(all_missing)} file sumber tidak ditemukan."
    if all_missing and generic_missing in errors:
        errors.remove(generic_missing)

    try:
        selected = active_audio_items(self, strict=True)
    except PlaylistSelectionError as exc:
        selected = active_audio_items(self, strict=False)
        errors.append(str(exc))

    used_missing = [
        item
        for item in [*self.videos, *selected]
        if not Path(item.path).exists()
    ]
    if used_missing:
        errors.append(
            f"{len(used_missing)} file sumber yang dipakai timeline tidak ditemukan."
        )

    # Keep order stable while avoiding repeated diagnostics from multiple checks.
    report["errors"] = list(dict.fromkeys(errors))
    report["warnings"] = list(dict.fromkeys(warnings))
    return report


def _hardened_controller_execute(
    self: ProjectController,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if name != "remove_audio":
        return _originals["controller_execute"](self, name, args)

    position = int(args["position"])
    target_path = None
    if 1 <= position <= len(self.project.audios):
        target_path = self.project.audios[position - 1].path

    active_before = get_active_audio_paths(self.project)
    if target_path is not None and active_before:
        target_key = _path_key(target_path)
        selected_target = any(_path_key(path) == target_key for path in active_before)
        if selected_target and len(active_before) == 1:
            raise ValueError(
                "Tidak dapat menghapus satu-satunya lagu di Playlist Aktif karena playlist kosong "
                "berarti 'pakai semua lagu'. Pilih playlist baru atau gunakan perintah 'pakai semua lagu' dulu."
            )

    result = _originals["controller_execute"](self, name, args)

    if target_path is not None and active_before:
        target_key = _path_key(target_path)
        remaining = [path for path in active_before if _path_key(path) != target_key]
        if len(remaining) != len(active_before):
            set_active_audio_paths(self.project, remaining)
            # The underlying controller produced its summary before playlist
            # cleanup. Return a fresh summary so callers never observe stale state.
            return self.summary()
    return result


def _hardened_handle_agent_decision(self, decision, context_signature: str) -> None:
    """Playlist agent transaction with atomic rollback of Timeline_Auto.json."""
    try:
        self.chat.appendPlainText(f"\nGEMINI\n{decision.message}\n")

        if context_signature != playlist_project_signature(self.project):
            self.chat.appendPlainText(
                "APP\nPerintah tidak diterapkan karena proyek berubah saat Gemini sedang memahami perintah. "
                "Kirim ulang perintah pada kondisi proyek terbaru.\n"
            )
            return

        if not decision.actions:
            return

        wants_render = any(action.name == "render_timeline" for action in decision.actions)
        if wants_render and self.render_busy:
            raise RuntimeError("Render lain masih berjalan. Perintah baru tidak diterapkan.")

        project_backup = deepcopy(self.project)
        previous_plan = self.timeline_plan
        previous_ready = self.timeline_ready
        previous_timeline_path = self.timeline_file_path
        timeline_output = ui_module.output_dir() / "Timeline_Auto.json"
        timeline_existed = timeline_output.exists()
        previous_timeline_bytes = (
            timeline_output.read_bytes() if timeline_existed else None
        )

        try:
            executor = agent_actions_module.AppIntentExecutor(
                self.project,
                timeline_output_path=str(timeline_output),
            )
            execution = executor.execute(decision.actions)

            if execution.project_changed:
                self.invalidate_timeline()

            if execution.timeline_plan is not None:
                self.timeline_file_path = execution.timeline_path
                self.apply_timeline_plan(execution.timeline_plan)
            else:
                self._sync_controls_from_project()
                self.refresh()

            if execution.summary_text:
                self.chat.appendPlainText(f"APP\n{execution.summary_text}\n")

            if getattr(execution, "render_requested", False):
                self._start_agent_render_default()
        except Exception:
            self.project = project_backup
            self.controller = ProjectController(self.project)
            self.agent = None
            self.timeline_plan = previous_plan
            self.timeline_ready = previous_ready
            self.timeline_file_path = previous_timeline_path
            self.timeline_preview.set_timeline(previous_plan)
            try:
                if timeline_existed and previous_timeline_bytes is not None:
                    atomic_write_bytes(timeline_output, previous_timeline_bytes)
                else:
                    timeline_output.unlink(missing_ok=True)
            except OSError:
                pass
            self._sync_controls_from_project()
            self.refresh()
            raise
    except Exception as exc:
        self._error(f"Perintah Gemini gagal diterapkan:\n\n{exc}")
    finally:
        self._agent_done()


def install_playlist_hardening() -> None:
    global _installed
    if _installed:
        return

    _originals.update(
        {
            "project_validation": Project.validation,
            "controller_execute": ProjectController.execute,
            "ui_handle_agent_decision": ui_module.MainWindow._handle_agent_decision,
        }
    )
    Project.validation = _hardened_project_validation
    ProjectController.execute = _hardened_controller_execute
    ui_module.MainWindow._handle_agent_decision = _hardened_handle_agent_decision
    _installed = True


def uninstall_playlist_hardening() -> None:
    global _installed
    if not _installed:
        return

    Project.validation = _originals["project_validation"]
    ProjectController.execute = _originals["controller_execute"]
    ui_module.MainWindow._handle_agent_decision = _originals["ui_handle_agent_decision"]
    _originals.clear()
    _installed = False
