from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .controller import ProjectController
from .project import Project
from .timeline import TimelineEngine, TimelinePlan, save_timeline


ALLOWED_ACTIONS = {
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
    """Executes Gemini intents locally. Gemini never performs timeline math itself."""

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

        # Gemini is instructed to put settings before auto_build_timeline, but
        # function-call ordering is not a safety boundary. Apply every project
        # mutation first, then build exactly once from the final project state.
        for action in actions:
            name = action.name
            args = action.args

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
                    f"✓ Video posisi {args['from_position']} dipindah ke {args['to_position']}."
                )
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
            if plan.auto_cut_seconds > 0:
                result.messages.append(
                    f"✓ Auto Cut: {plan.auto_cut_seconds:.3f} detik."
                )
            if plan.loop_fill_seconds > 0:
                result.messages.append(
                    f"✓ Tambahan {plan.loop_mode}: {plan.loop_fill_seconds:.3f} detik."
                )

        return result
