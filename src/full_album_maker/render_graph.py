from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .editor_models import Layer, ProjectDocument, TIMEBASE
from .render_plan import RenderPlan, compile_render_plan
from .timeline_resolver import TimelineResolver


class RenderCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledFFmpeg:
    args: tuple[str, ...]
    render_plan: RenderPlan
    text_files: tuple[Path, ...]


def ticks_to_seconds(value: int) -> float:
    return value / TIMEBASE


def _filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    value = value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return value


def _color(value: object, default: str = "#ffffff") -> str:
    text = str(value or default).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
        raise RenderCompileError(f"Warna tidak valid: {text}")
    return "0x" + text[1:]


def _font_size(layer: Layer, canvas_height: int) -> int:
    raw = layer.properties.get("font_size", 64)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RenderCompileError("font_size tidak valid.") from exc
    if not 4 <= value <= canvas_height * 2:
        raise RenderCompileError("font_size di luar batas.")
    return max(4, round(value))


def _position_expr(layer: Layer, axis: str) -> str:
    value = layer.transform.x if axis == "x" else layer.transform.y
    if not -2.0 <= value <= 2.0:
        raise RenderCompileError(f"Transform {axis} di luar batas render editor.")
    return f"{value:.8f}*{'W' if axis == 'x' else 'H'}"


def _overlay_position_expr(layer: Layer, axis: str) -> str:
    value = layer.transform.x if axis == "x" else layer.transform.y
    if not -2.0 <= value <= 2.0:
        raise RenderCompileError(f"Transform {axis} di luar batas render editor.")
    return f"{value:.8f}*{'main_w' if axis == 'x' else 'main_h'}"


def _layer_size(layer: Layer, document: ProjectDocument) -> tuple[int, int]:
    width = float(layer.transform.width)
    height = float(layer.transform.height)
    if not 0.02 <= width <= 3.0 or not 0.02 <= height <= 3.0:
        raise RenderCompileError("Ukuran transform background di luar batas 0.02..3.0.")
    return (
        max(2, round(document.canvas.width * width)),
        max(2, round(document.canvas.height * height)),
    )


def _rotation_chain(layer: Layer) -> str:
    value = float(layer.transform.rotation)
    if not -180.0 <= value <= 180.0:
        raise RenderCompileError("Rotasi layer di luar batas -180..180 derajat.")
    if abs(value) < 0.0001:
        return ""
    return f",rotate={value:.8f}*PI/180:ow=rotw(iw):oh=roth(ih):c=none"


def _escape_enable(intervals: Iterable[tuple[int, int]]) -> str:
    pieces = [
        f"between(t,{ticks_to_seconds(start):.6f},{ticks_to_seconds(end):.6f})"
        for start, end in intervals
        if end > start
    ]
    return "+".join(pieces) or "0"


class FFmpegV2Compiler:
    """Compiler shared by final render and accurate preview.

    S04 supports background solid/image/video transforms plus positioned text.
    Other active layer types fail closed instead of silently diverging from the
    editor preview.
    """

    def __init__(self, ffmpeg: str) -> None:
        if not ffmpeg:
            raise RenderCompileError("FFmpeg tidak ditemukan.")
        self.ffmpeg = ffmpeg

    def compile_video(
        self,
        document: ProjectDocument,
        destination: str | Path,
        work_dir: str | Path,
        *,
        include_audio: bool = True,
    ) -> CompiledFFmpeg:
        document.validate()
        resolved = TimelineResolver().resolve(document)
        if resolved.errors:
            raise RenderCompileError("Timeline tidak siap: " + " | ".join(resolved.errors))
        if resolved.duration_tick <= 0:
            raise RenderCompileError("Render album membutuhkan minimal satu lagu aktif.")
        plan = compile_render_plan(document, resolved)
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
        destination = Path(destination)
        duration = ticks_to_seconds(resolved.duration_tick)
        fps = document.canvas.fps_num / document.canvas.fps_den

        args: list[str] = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]
        args += [
            "-f", "lavfi",
            "-i",
            f"color=c={_color(document.canvas.background_color, '#101114')}:s={document.canvas.width}x{document.canvas.height}:r={fps:g}:d={duration:.6f}",
        ]

        assets = document.asset_map()
        resolved_by_layer = {item.layer_id: item for item in resolved.layers}
        media_input_index: dict[str, int] = {}
        next_input = 1

        active_layers: list[Layer] = []
        track_map = {track.track_id: track for track in document.tracks}
        for layer in sorted(document.layers, key=lambda x: x.order):
            track = track_map[layer.track_id]
            if not layer.enabled or not track.enabled:
                continue
            if layer.type not in {"background", "text"}:
                raise RenderCompileError(f"Layer aktif belum didukung compiler S04: {layer.type}")
            active_layers.append(layer)
            if layer.type != "background":
                continue
            mode = str(layer.properties.get("mode", "asset" if layer.asset_refs else "solid"))
            if mode == "solid":
                continue
            if not layer.asset_refs:
                raise RenderCompileError("Background asset tidak memiliki referensi media.")
            asset = assets.get(layer.asset_refs[0])
            if asset is None or asset.kind not in {"image", "video"}:
                raise RenderCompileError("Background harus merujuk image/video.")
            if asset.asset_id in media_input_index:
                continue
            media_input_index[asset.asset_id] = next_input
            next_input += 1
            if asset.kind == "image":
                args += ["-loop", "1", "-i", asset.locator]
            else:
                args += ["-stream_loop", "-1", "-an", "-i", asset.locator]

        audio_input_index: dict[str, int] = {}
        if include_audio:
            for event in plan.audio_events:
                asset = assets[event.asset_id]
                audio_input_index[event.song_id] = next_input
                next_input += 1
                source_in = ticks_to_seconds(event.source_in_tick)
                source_duration = ticks_to_seconds(event.source_out_tick - event.source_in_tick)
                args += ["-ss", f"{source_in:.6f}", "-t", f"{source_duration:.6f}", "-i", asset.locator]

        filters: list[str] = ["[0:v]setpts=PTS-STARTPTS[v0]"]
        current = "v0"
        text_files: list[Path] = []
        stage = 1

        for layer in active_layers:
            resolved_layer = resolved_by_layer.get(layer.layer_id)
            intervals = [] if resolved_layer is None else [(x.start_tick, x.end_tick) for x in resolved_layer.intervals]
            enable = _escape_enable(intervals)
            out = f"v{stage}"
            local_stage = stage
            stage += 1

            if layer.type == "background":
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                source_label = f"bg{local_stage}"
                mode = str(layer.properties.get("mode", "asset" if layer.asset_refs else "solid"))
                if mode == "solid":
                    color = _color(layer.properties.get("color", document.canvas.background_color))
                    filters.append(
                        f"color=c={color}:s={width}x{height}:r={fps:g}:d={duration:.6f},"
                        f"format=rgba,colorchannelmixer=aa={alpha:.6f}{rotate}[{source_label}]"
                    )
                else:
                    asset = assets[layer.asset_refs[0]]
                    index = media_input_index[asset.asset_id]
                    fit = str(layer.properties.get("fit", "fill"))
                    if fit == "fill":
                        geometry = (
                            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                            f"crop={width}:{height}"
                        )
                    elif fit in {"fit", "fit_blur"}:
                        geometry = (
                            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0"
                        )
                    else:
                        raise RenderCompileError("Mode fit background tidak valid.")
                    filters.append(
                        f"[{index}:v]{geometry},format=rgba,colorchannelmixer=aa={alpha:.6f},"
                        f"setpts=PTS-STARTPTS{rotate}[{source_label}]"
                    )
                filters.append(
                    f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                    f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:eof_action=repeat:"
                    f"enable='{enable}'[{out}]"
                )
                current = out
                continue

            if abs(float(layer.transform.rotation)) > 0.0001:
                raise RenderCompileError("Rotasi text belum didukung; rotasi hanya aktif untuk background visual pada S04.")
            text = str(layer.properties.get("text", ""))
            text_path = work / f"text-{layer.layer_id}.txt"
            text_path.write_text(text, encoding="utf-8")
            text_files.append(text_path)
            fontcolor = _color(layer.properties.get("color", "#ffffff"))
            fontsize = _font_size(layer, document.canvas.height)
            parts = [
                f"textfile='{_filter_path(text_path)}'",
                "reload=0",
                f"x={_position_expr(layer, 'x')}",
                f"y={_position_expr(layer, 'y')}",
                f"fontsize={fontsize}",
                f"fontcolor={fontcolor}",
                f"alpha={layer.opacity:.6f}",
                f"enable='{enable}'",
            ]
            font_path = str(layer.properties.get("font_path", "") or "").strip()
            if font_path:
                parts.insert(0, f"fontfile='{_filter_path(Path(font_path))}'")
            filters.append(f"[{current}]drawtext=" + ":".join(parts) + f"[{out}]")
            current = out

        filters.append(f"[{current}]format=yuv420p[vout]")

        if include_audio:
            audio_labels: list[str] = []
            for idx, event in enumerate(plan.audio_events):
                input_index = audio_input_index[event.song_id]
                label = f"a{idx}"
                event_duration = ticks_to_seconds(event.end_tick - event.start_tick)
                filters.append(
                    f"[{input_index}:a]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=duration={event_duration:.6f},asetpts=PTS-STARTPTS[{label}]"
                )
                audio_labels.append(f"[{label}]")
            filters.append("".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[aout]")

        args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
        if include_audio:
            args += ["-map", "[aout]"]
        encoder = "libx265" if document.render_settings.get("codec") == "h265" else "libx264"
        args += ["-c:v", encoder, "-pix_fmt", "yuv420p", "-r", f"{fps:g}"]
        if include_audio:
            args += ["-c:a", "aac", "-b:a", str(document.render_settings.get("audio_bitrate", "320k"))]
        args += ["-t", f"{duration:.6f}", "-movflags", "+faststart", str(destination)]
        return CompiledFFmpeg(tuple(args), plan, tuple(text_files))

    def compile_frame(
        self,
        document: ProjectDocument,
        time_tick: int,
        destination: str | Path,
        work_dir: str | Path,
    ) -> CompiledFFmpeg:
        if time_tick < 0:
            raise RenderCompileError("Waktu preview tidak boleh negatif.")
        compiled = self.compile_video(document, destination, work_dir, include_audio=False)
        args = list(compiled.args)
        output = args.pop()
        if "-c:v" in args:
            idx = args.index("-c:v")
            args[idx + 1] = "png"
        for option in ("-movflags", "-t", "-r"):
            while option in args:
                idx = args.index(option)
                del args[idx : idx + 2]
        if "-pix_fmt" in args:
            idx = args.index("-pix_fmt")
            args[idx + 1] = "rgb24"
        args += [
            "-ss",
            f"{ticks_to_seconds(time_tick):.6f}",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-f",
            "image2",
            output,
        ]
        return CompiledFFmpeg(tuple(args), compiled.render_plan, compiled.text_files)
