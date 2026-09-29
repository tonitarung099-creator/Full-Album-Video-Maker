from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .controller import ProjectController
from .project import Project
from .timeline import TimelineEngine, TimelinePlan, save_timeline


LEGACY_ACTIONS = {
    "auto_build_timeline",
    "validate_project",
    "optimize_youtube",
    "set_slowmo",
    "set_auto_speed",
    "set_loop_mode",
    "set_resolution",
    "set_fps",
    "set_codec",
    "set_quality",
    "sort_audio_by_name",
    "sort_video_by_name",
    "move_audio",
    "move_video",
    "remove_audio",
    "remove_video",
}

EDITOR_V2_ACTIONS = {
    "add_text",
    "edit_text",
    "move_layer",
    "resize_layer",
    "delete_layer",
    "duplicate_layer",
    "add_spectrum",
    "set_spectrum_style",
    "set_spectrum_range",
    "add_playlist_visual",
    "set_playlist_style",
    "add_cover",
    "set_cover_style",
    "add_progress_bar",
    "apply_template",
    "save_template",
    "move_song",
    "reorder_playlist",
    "remove_song",
    "set_background",
    "show_layer",
    "hide_layer",
    "render_project",
}

EDITOR_V14_ACTIONS = {
    "add_circular_spectrum",
    "set_circular_spectrum",
    "set_song_cover",
    "clear_song_cover",
    "auto_match_covers",
    "set_song_visual",
    "clear_song_visual",
    "auto_match_song_visuals",
    "set_song_visual_style",
    "set_timeline_mode",
    "set_song_timing",
}

ALLOWED_ACTIONS = LEGACY_ACTIONS | EDITOR_V2_ACTIONS | EDITOR_V14_ACTIONS


@dataclass(frozen=True)
class AgentAction:
    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in ALLOWED_ACTIONS:
            raise ValueError(f"Intent aplikasi tidak dikenal: {self.name}")


@dataclass
class AgentDecision:
    message: str
    actions: list[AgentAction] = field(default_factory=list)


@dataclass
class ActionExecution:
    messages: list[str] = field(default_factory=list)
    timeline_plan: TimelinePlan | None = None
    timeline_path: str = ""
    project_changed: bool = False

    @property
    def summary_text(self) -> str:
        return "\n".join(self.messages).strip()


class AppIntentExecutor:
    """Executes legacy Gemini intents locally. Editor-v2 uses ai_editor.py."""

    def __init__(
        self,
        project: Project,
        *,
        timeline_output_path: str,
    ) -> None:
        self.project = project
        self.controller = ProjectController(project)
        self.timeline_output_path = timeline_output_path

    def execute(self, actions: list[AgentAction]) -> ActionExecution:
        result = ActionExecution()
        build_requested = any(action.name == "auto_build_timeline" for action in actions)

        for action in actions:
            name = action.name
            args = action.args

            if name not in LEGACY_ACTIONS:
                raise ValueError(f"Intent '{name}' hanya berlaku pada editor v2.")

            if name == "auto_build_timeline":
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

            if name == "optimize_youtube":
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
                result.messages.append("✓ Lagu diurutkan berdasarkan nama.")
            elif name == "sort_video_by_name":
                result.messages.append("✓ Footage diurutkan berdasarkan nama.")
            elif name == "move_audio":
                result.messages.append(
                    f"✓ Lagu posisi {args['from_position']} dipindah ke {args['to_position']}."
                )
            elif name == "move_video":
                result.messages.append(
                    f"✓ Video posisi {args['from_position']} dipindah ke {args['to_position']}.")
            elif name == "remove_audio":
                result.messages.append(f"✓ Lagu posisi {args['position']} dihapus.")
            elif name == "remove_video":
                result.messages.append(f"✓ Video posisi {args['position']} dihapus.")

        if build_requested:
            plan = TimelineEngine().build(self.project)
            path = save_timeline(self.timeline_output_path, plan)
            result.timeline_plan = plan
            result.timeline_path = path
            result.messages.append(
                "✓ Auto Timeline dibuat lokal: "
                f"{len(plan.video_clips)} clip video, "
                f"{len(plan.audio_clips)} clip audio, "
                f"speed {plan.planned_speed:.3f}x."
            )
        return result
