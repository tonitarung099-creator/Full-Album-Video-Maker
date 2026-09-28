from __future__ import annotations

import re
from pathlib import Path

from .editor_models import Layer, ProjectDocument
from .render_graph import CompiledFFmpeg, FFmpegV2Compiler, ticks_to_seconds


_AUDIO_SEGMENT = re.compile(r"^\[(\d+):a\].*\[aseg(\d+)\]$")


class S11FFmpegCompiler(FFmpegV2Compiler):
    """S10 visual compiler plus the opt-in S11 free-audio compositor.

    Packed projects are returned byte-for-byte through the established S10 graph.
    Free projects replace only the album-audio concat section with timestamped
    segments over a finite silent base. This makes gaps actual silence while the
    same mixed [album_audio] feeds both final audio and every spectrum branch.
    """

    def compile_video(
        self,
        document: ProjectDocument,
        destination: str | Path,
        work_dir: str | Path,
        *,
        include_audio: bool = True,
    ) -> CompiledFFmpeg:
        compiled = super().compile_video(
            document,
            destination,
            work_dir,
            include_audio=include_audio,
        )
        if document.playlist.mode != "free":
            return compiled

        args = list(compiled.args)
        try:
            filter_index = args.index("-filter_complex") + 1
        except ValueError:
            return compiled
        graph = args[filter_index]
        parts = graph.split(";")

        input_by_event: dict[int, int] = {}
        kept: list[str] = []
        for part in parts:
            match = _AUDIO_SEGMENT.match(part)
            if match:
                input_by_event[int(match.group(2))] = int(match.group(1))
                continue
            if "concat=n=" in part and part.endswith("[album_audio]"):
                continue
            if part.startswith("[album_audio]") and (
                "anull[" in part or "asplit=" in part
            ):
                continue
            kept.append(part)

        # Accurate frame rendering without an active spectrum intentionally has
        # no audio inputs. In that case visual free timing still comes from the
        # shared resolver and no audio graph needs to be synthesized.
        if not input_by_event:
            return compiled

        events = list(compiled.render_plan.audio_events)
        if set(input_by_event) != set(range(len(events))):
            raise ValueError("Compiler S11 tidak dapat memetakan input audio free timeline.")

        duration = ticks_to_seconds(compiled.render_plan.duration_tick)
        audio_parts: list[str] = []
        for index, event in enumerate(events):
            input_index = input_by_event[index]
            event_duration = ticks_to_seconds(event.end_tick - event.start_tick)
            start = ticks_to_seconds(event.start_tick)
            fade_in = ticks_to_seconds(event.crossfade_in_tick)
            fade_out = 0.0
            if index + 1 < len(events):
                incoming = events[index + 1]
                if (
                    incoming.crossfade_in_tick > 0
                    and incoming.start_tick < event.end_tick
                ):
                    fade_out = ticks_to_seconds(incoming.crossfade_in_tick)

            chain = (
                f"[{input_index}:a]aresample=48000,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"atrim=duration={event_duration:.6f},asetpts=PTS-STARTPTS,"
                f"volume={float(event.gain):.8f}"
            )
            if fade_in > 0:
                chain += f",afade=t=in:st=0:d={fade_in:.6f}:curve=tri"
            if fade_out > 0:
                fade_start = max(0.0, event_duration - fade_out)
                chain += (
                    f",afade=t=out:st={fade_start:.6f}:d={fade_out:.6f}:curve=tri"
                )
            if start > 0:
                chain += f",asetpts=PTS+{start:.6f}/TB"
            chain += f"[aseg{index}]"
            audio_parts.append(chain)

        audio_parts.append(
            f"anullsrc=r=48000:cl=stereo:d={duration:.6f}[asilence]"
        )
        mix_inputs = "[asilence]" + "".join(
            f"[aseg{index}]" for index in range(len(events))
        )
        audio_parts.append(
            f"{mix_inputs}amix=inputs={len(events) + 1}:duration=longest:"
            f"dropout_transition=0:normalize=0,atrim=duration={duration:.6f},"
            "asetpts=PTS-STARTPTS[album_audio]"
        )

        track_map = {track.track_id: track for track in document.tracks}
        spectrum_layers: list[Layer] = [
            layer
            for layer in sorted(document.layers, key=lambda item: item.order)
            if layer.enabled
            and track_map[layer.track_id].enabled
            and layer.type == "spectrum"
        ]
        branch_labels: list[str] = []
        if include_audio:
            branch_labels.append("aout")
        branch_labels.extend(
            f"specaudio{index}" for index, _ in enumerate(spectrum_layers)
        )
        if len(branch_labels) == 1:
            audio_parts.append(f"[album_audio]anull[{branch_labels[0]}]")
        elif len(branch_labels) > 1:
            outputs = "".join(f"[{label}]" for label in branch_labels)
            audio_parts.append(
                f"[album_audio]asplit={len(branch_labels)}{outputs}"
            )

        # Keep the video base first, then the reconstructed album audio, then all
        # original visual filters. The old audio-only fragments were removed above.
        video_base = [part for part in kept if part.startswith("[0:v]")]
        remaining = [part for part in kept if not part.startswith("[0:v]")]
        args[filter_index] = ";".join(video_base + audio_parts + remaining)
        return CompiledFFmpeg(
            tuple(args),
            compiled.render_plan,
            compiled.text_files,
        )
