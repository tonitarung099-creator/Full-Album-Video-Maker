from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from . import agent_actions as agent_actions_module
from . import gemini_agent as gemini_agent_module
from . import timeline as timeline_module
from . import ui as ui_module
from .controller import ProjectController
from .project import MediaItem, Project
from .renderer import FFmpegRenderer
from .timeline import AudioTimelineClip, EPSILON, TimelineError, TimelinePlan, save_timeline


FEATURE_ACTIONS = {
    "select_audio_by_titles",
    "clear_audio_playlist",
    "render_timeline",
}

_ACTIVE_ATTR = "_active_audio_paths"
_installed = False
_originals: dict[str, Any] = {}


class PlaylistSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class PlaylistSelection:
    requested_titles: list[str]
    selected_paths: list[str]
    selected_names: list[str]

    @property
    def count(self) -> int:
        return len(self.selected_paths)


def _path_key(value: str) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


def _strip_audio_extension(value: str) -> str:
    return re.sub(
        r"\.(?:mp3|wav|flac|m4a|aac|ogg|opus|wma)$",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )


def normalize_title(value: str) -> str:
    text = _strip_audio_extension(str(value))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[\[\](){}]", " ", text)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"^\s*(?:track\s*)?\d{1,4}\s+", "", text)
    return " ".join(text.split())


def _media_title(item: MediaItem) -> str:
    return normalize_title(Path(item.path).stem)


def _similarity(query: str, candidate: str) -> float:
    if query == candidate:
        return 1.0

    shorter = min(len(query), len(candidate))
    if shorter >= 5 and (f" {query} " in f" {candidate} " or f" {candidate} " in f" {query} "):
        return 0.97

    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    if len(query_tokens) >= 2 and query_tokens <= candidate_tokens:
        coverage = len(query) / max(1, len(candidate))
        return 0.93 + min(0.03, coverage * 0.03)

    return SequenceMatcher(None, query, candidate).ratio()


def select_audio_titles(
    media: Iterable[MediaItem],
    titles: Iterable[str],
) -> PlaylistSelection:
    library = list(media)
    requested = [str(title).strip() for title in titles if str(title).strip()]
    if not requested:
        raise PlaylistSelectionError("Daftar judul lagu kosong.")
    if len(requested) > 500:
        raise PlaylistSelectionError("Maksimal 500 judul dalam satu perintah playlist.")
    if not library:
        raise PlaylistSelectionError("Media belum memiliki lagu.")

    normalized_library = [_media_title(item) for item in library]
    used: set[int] = set()
    selected: list[int] = []
    missing: list[str] = []
    ambiguous: list[tuple[str, list[str]]] = []

    for raw_title in requested:
        query = normalize_title(raw_title)
        if not query:
            missing.append(raw_title)
            continue

        available = [index for index in range(len(library)) if index not in used]
        exact = [index for index in available if normalized_library[index] == query]
        if len(exact) == 1:
            chosen = exact[0]
            used.add(chosen)
            selected.append(chosen)
            continue
        if len(exact) > 1:
            ambiguous.append((raw_title, [library[index].name for index in exact[:5]]))
            continue

        ranked = sorted(
            (
                (_similarity(query, normalized_library[index]), index)
                for index in available
                if normalized_library[index]
            ),
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.88:
            missing.append(raw_title)
            continue

        best_score, best_index = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if second_score >= 0.88 and best_score - second_score < 0.04:
            candidates = [
                library[index].name
                for score, index in ranked[:5]
                if score >= best_score - 0.04
            ]
            ambiguous.append((raw_title, candidates))
            continue

        used.add(best_index)
        selected.append(best_index)

    if missing or ambiguous:
        details: list[str] = [
            f"Playlist tidak dibuat: {len(selected)}/{len(requested)} judul cocok dengan aman."
        ]
        if missing:
            details.append("Tidak ditemukan: " + ", ".join(missing[:12]))
        if ambiguous:
            preview = []
            for title, candidates in ambiguous[:8]:
                preview.append(f"{title} → {' / '.join(candidates)}")
            details.append("Ambigu: " + " | ".join(preview))
        details.append(
            "Tidak ada lagu pengganti yang ditebak otomatis. Perbaiki judul lalu kirim ulang."
        )
        raise PlaylistSelectionError("\n".join(details))

    return PlaylistSelection(
        requested_titles=requested,
        selected_paths=[library[index].path for index in selected],
        selected_names=[library[index].name for index in selected],
    )


def get_active_audio_paths(project: Project) -> list[str]:
    raw = getattr(project, _ACTIVE_ATTR, [])
    if not isinstance(raw, list):
        return []
    return [str(path) for path in raw if isinstance(path, str) and path.strip()]


def set_active_audio_paths(project: Project, paths: Iterable[str]) -> None:
    values = [str(path) for path in paths]
    setattr(project, _ACTIVE_ATTR, values)


def clear_active_audio_playlist(project: Project) -> None:
    setattr(project, _ACTIVE_ATTR, [])


def active_audio_indices(project: Project, *, strict: bool = False) -> list[int]:
    active = get_active_audio_paths(project)
    if not active:
        return list(range(len(project.audios)))

    library = {_path_key(item.path): index for index, item in enumerate(project.audios)}
    result: list[int] = []
    missing: list[str] = []
    for path in active:
        index = library.get(_path_key(path))
        if index is None:
            missing.append(Path(path).name)
        else:
            result.append(index)

    if strict and missing:
        raise PlaylistSelectionError(
            "Playlist aktif merujuk lagu yang sudah tidak ada di Media: "
            + ", ".join(missing[:12])
        )
    return result


def active_audio_items(project: Project, *, strict: bool = False) -> list[MediaItem]:
    return [project.audios[index] for index in active_audio_indices(project, strict=strict)]


def active_audio_duration(project: Project) -> float:
    return sum(max(0.0, item.duration) for item in active_audio_items(project))


def library_audio_duration(project: Project) -> float:
    return sum(max(0.0, item.duration) for item in project.audios)


def playlist_project_signature(project: Project) -> str:
    base_signature = _originals.get("timeline_project_signature")
    if base_signature is None:
        base_signature = timeline_module.project_signature
    base = base_signature(project)
    payload = {
        "base": base,
        "active_audio_paths": get_active_audio_paths(project),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PlaylistTimelineEngine(timeline_module.TimelineEngine):
    """Timeline engine that keeps Media as a library and uses only the active playlist."""

    def build(self, project: Project) -> TimelinePlan:
        self._validate_project_for_timeline(project)

        album_duration = active_audio_duration(project)
        speed = project.planned_speed()
        adjusted_duration = project.total_video_duration / speed
        auto_cut = max(0.0, adjusted_duration - album_duration)
        loop_fill = max(0.0, album_duration - adjusted_duration)

        mode = project.settings.loop_mode
        if mode == "auto":
            mode = "loop" if loop_fill > EPSILON else "none"
        if loop_fill <= EPSILON:
            mode = "none"
        if loop_fill > EPSILON and mode == "none":
            raise TimelineError(
                "Footage lebih pendek dari playlist tetapi mode loop dimatikan."
            )

        plan = TimelinePlan(
            duration=album_duration,
            planned_speed=speed,
            source_video_duration=project.total_video_duration,
            adjusted_video_duration=adjusted_duration,
            auto_cut_seconds=auto_cut,
            loop_fill_seconds=loop_fill,
            loop_mode=mode,
            project_signature=playlist_project_signature(project),
        )
        plan.audio_clips = self._build_audio_track(project)
        plan.video_clips = self._build_video_track(project, plan)

        errors = plan.validate()
        if errors:
            raise TimelineError("Timeline gagal divalidasi: " + " ".join(errors))
        return plan

    @staticmethod
    def _validate_project_for_timeline(project: Project) -> None:
        if not project.videos:
            raise TimelineError("Belum ada footage video.")
        if not project.audios:
            raise TimelineError("Belum ada lagu di Media.")
        try:
            selected = active_audio_items(project, strict=True)
        except PlaylistSelectionError as exc:
            raise TimelineError(str(exc)) from exc
        if not selected:
            raise TimelineError("Playlist aktif tidak memiliki lagu.")
        if project.total_video_duration <= 0:
            raise TimelineError("Durasi footage tidak valid.")
        if active_audio_duration(project) <= 0:
            raise TimelineError("Durasi playlist tidak valid.")
        if project.planned_speed() <= 0:
            raise TimelineError("Speed video tidak valid.")
        for item in project.videos:
            if item.duration <= 0:
                raise TimelineError(f"Durasi footage tidak valid: {item.name}")
        for item in selected:
            if item.duration <= 0:
                raise TimelineError(f"Durasi lagu tidak valid: {item.name}")

    @staticmethod
    def _build_audio_track(project: Project) -> list[AudioTimelineClip]:
        clips: list[AudioTimelineClip] = []
        cursor = 0.0
        for source_index in active_audio_indices(project, strict=True):
            item = project.audios[source_index]
            end = cursor + item.duration
            clips.append(
                AudioTimelineClip(
                    source=item.path,
                    source_index=source_index,
                    name=Path(item.path).stem,
                    source_in=0.0,
                    source_out=item.duration,
                    timeline_in=cursor,
                    timeline_out=end,
                )
            )
            cursor = end
        return clips


def _patched_controller_summary(self: ProjectController) -> dict[str, Any]:
    original = _originals["controller_summary"]
    summary = original(self)
    active = get_active_audio_paths(self.project)
    indices = active_audio_indices(self.project)
    summary["media_audio_count"] = len(self.project.audios)
    summary["media_audio_duration_seconds"] = round(library_audio_duration(self.project), 3)
    summary["playlist_active"] = bool(active)
    summary["active_playlist_count"] = len(indices)
    summary["active_playlist"] = [
        {
            "position": position,
            "media_position": index + 1,
            "name": self.project.audios[index].name,
            "duration_seconds": round(self.project.audios[index].duration, 3),
        }
        for position, index in enumerate(indices, start=1)
    ]
    return summary


def _validated_titles(args: dict[str, Any]) -> list[str]:
    titles = args.get("titles")
    if not isinstance(titles, list):
        raise PlaylistSelectionError("titles harus berupa daftar judul lagu.")
    if not all(isinstance(title, str) for title in titles):
        raise PlaylistSelectionError("Semua judul playlist harus berupa teks.")
    return titles


def _patched_controller_execute(
    self: ProjectController,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if name == "select_audio_by_titles":
        selection = select_audio_titles(self.project.audios, _validated_titles(args))
        set_active_audio_paths(self.project, selection.selected_paths)
        return {
            "playlist_selection": {
                "count": selection.count,
                "names": selection.selected_names,
            },
            "summary": self.summary(),
        }

    if name == "clear_audio_playlist":
        clear_active_audio_playlist(self.project)
        return {
            "playlist_selection": {
                "count": len(self.project.audios),
                "uses_all_media_audio": True,
            },
            "summary": self.summary(),
        }

    return _originals["controller_execute"](self, name, args)


def _patched_executor_execute(self, actions):
    ActionExecution = agent_actions_module.ActionExecution
    result = ActionExecution()
    render_requested = any(action.name == "render_timeline" for action in actions)
    build_requested = render_requested or any(
        action.name == "auto_build_timeline" for action in actions
    )

    for action in actions:
        name = action.name
        args = action.args

        if name in {"auto_build_timeline", "render_timeline"}:
            continue

        if name == "validate_project":
            report = self.project.validation()
            if report["errors"]:
                result.messages.append(
                    "✗ Proyek belum siap: " + " | ".join(report["errors"])
                )
            elif report["warnings"]:
                result.messages.append(
                    "✓ Tidak ada error. Peringatan: " + " | ".join(report["warnings"])
                )
            else:
                result.messages.append("✓ Proyek siap. Tidak ada error atau warning.")
            continue

        before = self.controller.summary()
        after = self.controller.execute(name, args)
        if after != before:
            result.project_changed = True

        if name == "select_audio_by_titles":
            count = len(active_audio_indices(self.project, strict=True))
            result.messages.append(
                f"✓ Playlist aktif dibuat: {count} lagu, sesuai urutan perintah. "
                "Lagu lain tetap berada di Media."
            )
        elif name == "clear_audio_playlist":
            result.messages.append(
                "✓ Playlist pilihan dibersihkan. Timeline kembali memakai semua lagu di Media."
            )
        elif name == "optimize_youtube":
            quality = str(args.get("quality", "1080p"))
            result.messages.append(f"✓ Preset YouTube {quality} diterapkan.")
        elif name == "set_slowmo":
            result.messages.append(f"✓ Slowmo dikunci ke {float(args['speed']):.2f}x.")
        elif name == "set_auto_speed":
            value = self.project.settings.min_speed
            result.messages.append(f"✓ Auto Fit aktif, batas slowmo {value:.2f}x.")
        elif name == "set_loop_mode":
            result.messages.append(f"✓ Mode footage kurang: {args['mode']}.")
        elif name == "set_resolution":
            result.messages.append(
                f"✓ Resolusi {int(args['width'])}×{int(args['height'])}."
            )
        elif name == "set_fps":
            result.messages.append(f"✓ FPS {int(args['fps'])}.")
        elif name == "set_codec":
            result.messages.append(f"✓ Codec {str(args['codec']).upper()}.")
        elif name == "set_quality":
            result.messages.append("✓ Kualitas video/audio diperbarui.")
        elif name == "sort_audio_by_name":
            result.messages.append("✓ Media lagu diurutkan berdasarkan nama.")
        elif name == "sort_video_by_name":
            result.messages.append("✓ Footage diurutkan berdasarkan nama.")
        elif name == "move_audio":
            result.messages.append(
                f"✓ Lagu Media posisi {args['from_position']} dipindah ke {args['to_position']}."
            )
        elif name == "move_video":
            result.messages.append(
                f"✓ Video posisi {args['from_position']} dipindah ke {args['to_position']}."
            )
        elif name == "remove_audio":
            result.messages.append(f"✓ Lagu Media posisi {args['position']} dihapus.")
        elif name == "remove_video":
            result.messages.append(f"✓ Video posisi {args['position']} dihapus.")

    if build_requested:
        plan = PlaylistTimelineEngine().build(self.project)
        path = save_timeline(self.timeline_output_path, plan)
        result.timeline_plan = plan
        result.timeline_path = path
        result.messages.append(
            "✓ Auto Timeline dibuat lokal: "
            f"{len(plan.video_clips)} clip video, "
            f"{len(plan.audio_clips)} lagu playlist, "
            f"speed {plan.planned_speed:.3f}x."
        )
        if plan.auto_cut_seconds > 0:
            result.messages.append(f"✓ Auto Cut: {plan.auto_cut_seconds:.3f} detik.")
        if plan.loop_fill_seconds > 0:
            result.messages.append(
                f"✓ Tambahan {plan.loop_mode}: {plan.loop_fill_seconds:.3f} detik."
            )

    setattr(result, "render_requested", render_requested)
    if render_requested:
        result.messages.append("✓ Render otomatis diminta setelah timeline tervalidasi.")
    return result


def _patched_project_to_dict(self: Project) -> dict:
    data = _originals["project_to_dict"](self)
    data["active_audio_paths"] = get_active_audio_paths(self)
    return data


def _patched_project_from_dict(cls, data: dict) -> Project:
    project = _originals["project_from_dict_bound"](data)
    raw = data.get("active_audio_paths", []) if isinstance(data, dict) else []
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(
        isinstance(path, str) and path.strip() for path in raw
    ):
        raise ValueError("Playlist aktif proyek tidak valid.")

    if raw:
        library = {_path_key(item.path) for item in project.audios}
        missing = [path for path in raw if _path_key(path) not in library]
        if missing:
            raise ValueError(
                "Playlist aktif merujuk lagu yang tidak ada di Media: "
                + ", ".join(Path(path).name for path in missing[:12])
            )
    set_active_audio_paths(project, raw)
    return project


def _patched_total_audio_duration(self: Project) -> float:
    return active_audio_duration(self)


def _patched_refresh(self) -> None:
    _originals["ui_refresh"](self)
    active = get_active_audio_paths(self.project)
    if not active:
        return

    positions: dict[str, list[int]] = {}
    for position, path in enumerate(active, start=1):
        positions.setdefault(_path_key(path), []).append(position)

    for row, item in enumerate(self.project.audios):
        playlist_positions = positions.get(_path_key(item.path), [])
        if playlist_positions:
            pos_text = ",".join(f"P{position:02d}" for position in playlist_positions)
            self.audio_list.item(row).setText(
                f"✓ {pos_text}   {Path(item.path).stem}                              {ui_module.fmt(item.duration)}"
            )

    self.audio_total.setText(
        "♫   Media "
        f"{len(self.project.audios)} lagu  •  Playlist aktif {len(active)} lagu  •  "
        f"Timeline {ui_module.fmt(active_audio_duration(self.project))}"
    )


def _start_agent_render_default(self) -> None:
    if self.render_busy:
        raise RuntimeError("Render lain masih berjalan. Tunggu render tersebut selesai.")

    report = self.project.validation()
    if report["errors"]:
        raise RuntimeError(
            "Proyek belum siap:\n" + "\n".join(f"• {x}" for x in report["errors"])
        )

    if self.timeline_plan is None or not self.timeline_ready:
        raise RuntimeError("Timeline belum siap untuk render otomatis.")

    timeline_errors = timeline_module.validate_timeline_against_project(
        self.timeline_plan,
        self.project,
    )
    if timeline_errors:
        raise RuntimeError(
            "Timeline tidak valid untuk render otomatis:\n"
            + "\n".join(f"• {x}" for x in timeline_errors)
        )

    destination = str(ui_module.output_dir() / "FULL_ALBUM_FINAL.mp4")
    self.render_busy = True
    self.render_btn.setEnabled(False)
    self.render_btn.setText("Rendering otomatis dari AI Agent…")
    project_snapshot = deepcopy(self.project)
    timeline_snapshot = deepcopy(self.timeline_plan)
    self.chat.appendPlainText(
        "APP\n▶ Render otomatis dimulai dari playlist aktif.\n"
        f"Output: {destination}\n"
    )

    def work():
        try:
            renderer = FFmpegRenderer(project_snapshot, timeline_snapshot)
            result = renderer.render(
                destination,
                log=self.bridge.render_log.emit,
            )
            self.bridge.render_done.emit(result)
        except Exception as exc:
            self.bridge.error.emit(str(exc))
            self.bridge.render_done.emit("")

    threading.Thread(target=work, daemon=True).start()


def _patched_handle_agent_decision(self, decision, context_signature: str) -> None:
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
                    timeline_output.write_bytes(previous_timeline_bytes)
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


def _playlist_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "select_audio_by_titles",
            "description": (
                "Buat Playlist Aktif dari judul yang disebut pengguna. Ambil hanya lagu yang sudah ada di Media, "
                "ikuti persis urutan judul pengguna, dan jangan hapus lagu lain dari Media. Wajib kirim semua judul "
                "yang diminta pengguna dalam array titles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    }
                },
                "required": ["titles"],
            },
        },
        {
            "name": "clear_audio_playlist",
            "description": (
                "Hapus pilihan Playlist Aktif tanpa menghapus Media. Setelah ini timeline kembali memakai semua lagu di Media."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "render_timeline",
            "description": (
                "Render timeline secara lokal ke output default. Gunakan hanya jika pengguna eksplisit meminta render, "
                "ekspor, atau lanjut render. Engine aplikasi akan membangun ulang timeline secara defensif sebelum render."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    ]


def _updated_system(system: str) -> str:
    system = system.replace(
        "6. Tidak ada fungsi render. Jangan mengklaim render sudah dimulai/selesai.",
        "6. Ada fungsi render_timeline. Gunakan hanya jika pengguna eksplisit meminta render/ekspor. Jangan mengklaim selesai sebelum aplikasi melaporkannya.",
    )
    extra = """

FITUR PLAYLIST AKTIF:
- Media adalah perpustakaan. Bisa berisi ratusan lagu dan jangan dihapus hanya karena pengguna memilih playlist.
- Jika pengguna menuliskan daftar judul yang ingin dipakai, panggil select_audio_by_titles dengan SEMUA judul dan urutan yang sama.
- Contoh: "pilih 20 lagu ini ... slowmo 0,5 lalu render" -> select_audio_by_titles, set_slowmo 0.5, auto_build_timeline, render_timeline.
- Jika pengguna berkata "pakai semua lagu lagi", panggil clear_audio_playlist.
- Jangan menebak pengganti lagu yang tidak disebut. Matching aman dilakukan engine lokal; jika satu judul tidak ditemukan/ambigu, proses dihentikan sebelum timeline/render.
- render_timeline hanya untuk permintaan render eksplisit. Pemilihan playlist atau setting tanpa kata render tidak boleh memulai render.
"""
    return system.rstrip() + extra


def install_feature() -> None:
    global _installed
    if _installed:
        return

    ProjectClass = Project
    MainWindow = ui_module.MainWindow

    _originals.update(
        {
            "project_total_audio_duration": ProjectClass.__dict__["total_audio_duration"],
            "project_to_dict": ProjectClass.to_dict,
            "project_from_dict_descriptor": ProjectClass.__dict__["from_dict"],
            "project_from_dict_bound": ProjectClass.from_dict,
            "timeline_project_signature": timeline_module.project_signature,
            "controller_summary": ProjectController.summary,
            "controller_execute": ProjectController.execute,
            "executor_execute": agent_actions_module.AppIntentExecutor.execute,
            "ui_project_signature": ui_module.project_signature,
            "ui_timeline_engine": ui_module.TimelineEngine,
            "agent_timeline_engine": agent_actions_module.TimelineEngine,
            "ui_refresh": MainWindow.refresh,
            "ui_handle_agent_decision": MainWindow._handle_agent_decision,
            "ui_start_agent_render": getattr(MainWindow, "_start_agent_render_default", None),
            "gemini_system": gemini_agent_module.SYSTEM,
            "gemini_tools": gemini_agent_module.TOOLS,
        }
    )

    ProjectClass.total_audio_duration = property(_patched_total_audio_duration)
    ProjectClass.to_dict = _patched_project_to_dict
    ProjectClass.from_dict = classmethod(_patched_project_from_dict)

    timeline_module.project_signature = playlist_project_signature
    ui_module.project_signature = playlist_project_signature
    ui_module.TimelineEngine = PlaylistTimelineEngine
    agent_actions_module.TimelineEngine = PlaylistTimelineEngine

    agent_actions_module.ALLOWED_ACTIONS.update(FEATURE_ACTIONS)
    ProjectController.summary = _patched_controller_summary
    ProjectController.execute = _patched_controller_execute
    agent_actions_module.AppIntentExecutor.execute = _patched_executor_execute

    gemini_agent_module.SYSTEM = _updated_system(gemini_agent_module.SYSTEM)
    gemini_agent_module.TOOLS = list(gemini_agent_module.TOOLS) + _playlist_tools()

    MainWindow.refresh = _patched_refresh
    MainWindow._start_agent_render_default = _start_agent_render_default
    MainWindow._handle_agent_decision = _patched_handle_agent_decision

    _installed = True


def uninstall_feature() -> None:
    global _installed
    if not _installed:
        return

    Project.total_audio_duration = _originals["project_total_audio_duration"]
    Project.to_dict = _originals["project_to_dict"]
    Project.from_dict = _originals["project_from_dict_descriptor"]

    timeline_module.project_signature = _originals["timeline_project_signature"]
    ui_module.project_signature = _originals["ui_project_signature"]
    ui_module.TimelineEngine = _originals["ui_timeline_engine"]
    agent_actions_module.TimelineEngine = _originals["agent_timeline_engine"]

    for action in FEATURE_ACTIONS:
        agent_actions_module.ALLOWED_ACTIONS.discard(action)
    ProjectController.summary = _originals["controller_summary"]
    ProjectController.execute = _originals["controller_execute"]
    agent_actions_module.AppIntentExecutor.execute = _originals["executor_execute"]

    gemini_agent_module.SYSTEM = _originals["gemini_system"]
    gemini_agent_module.TOOLS = _originals["gemini_tools"]

    ui_module.MainWindow.refresh = _originals["ui_refresh"]
    ui_module.MainWindow._handle_agent_decision = _originals["ui_handle_agent_decision"]
    previous_start = _originals["ui_start_agent_render"]
    if previous_start is None:
        try:
            delattr(ui_module.MainWindow, "_start_agent_render_default")
        except AttributeError:
            pass
    else:
        ui_module.MainWindow._start_agent_render_default = previous_start

    _originals.clear()
    _installed = False
