from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .album_visuals import format_duration_tick, normalize_visual_properties
from .circular_spectrum import circular_spectrum_filter
from .editor_models import Layer, ProjectDocument, TIMEBASE
from .overlay_effects import effect_source_filter, normalize_effect_properties
from .render_plan import RenderPlan, compile_render_plan
from .spectrum_feature import dynamic_song_text, normalize_spectrum_properties
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


def _rgb(value: object, default: str = "#ffffff") -> tuple[int, int, int]:
    text = str(value or default).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
        raise RenderCompileError(f"Warna tidak valid: {text}")
    return tuple(int(text[index : index + 2], 16) for index in (1, 3, 5))


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
        raise RenderCompileError("Ukuran transform visual di luar batas 0.02..3.0.")
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


def _intersect_intervals(
    intervals: Iterable[tuple[int, int]], start_tick: int, end_tick: int
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in intervals:
        left = max(start, start_tick)
        right = min(end, end_tick)
        if right > left:
            result.append((left, right))
    return result


def _ffmpeg_scale(value: str) -> str:
    return {
        "linear": "lin",
        "sqrt": "sqrt",
        "cbrt": "cbrt",
        "log": "log",
        "rlog": "rlog",
    }.get(value, value)


def _clock_text(total_tick: int) -> str:
    total = format_duration_tick(total_tick).replace(":", "\\:")
    return (
        "%{eif\\:floor(t/60)\\:d\\:2}\\:"
        "%{eif\\:mod(floor(t)\\,60)\\:d\\:2} / " + total
    )


class FFmpegV2Compiler:
    """Compiler shared by final render and accurate preview.

    S10 extends the same proven S06 compiler with bounded procedural overlay
    effects. v1.2 adds Circular Spectrum inside this same compiler, so Preview
    Akurat and final render still use one composition path.
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

        args: list[str] = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        args += [
            "-f",
            "lavfi",
            "-i",
            f"color=c={_color(document.canvas.background_color, '#101114')}:s={document.canvas.width}x{document.canvas.height}:r={fps:g}:d={duration:.6f}",
        ]

        assets = document.asset_map()
        songs = document.song_map()
        resolved_by_layer = {item.layer_id: item for item in resolved.layers}
        media_input_index: dict[str, int] = {}
        cover_input_index: dict[tuple[str, str], int] = {}
        next_input = 1

        active_layers: list[Layer] = []
        track_map = {track.track_id: track for track in document.tracks}
        supported = {
            "background",
            "text",
            "song_title",
            "spectrum",
            "song_cover",
            "vinyl",
            "playlist_visual",
            "progress",
            "song_time",
        }
        for layer in sorted(document.layers, key=lambda x: x.order):
            track = track_map[layer.track_id]
            if not layer.enabled or not track.enabled:
                continue
            if layer.type not in supported:
                raise RenderCompileError(
                    f"Layer aktif belum didukung compiler S10: {layer.type}"
                )
            if layer.type == "spectrum":
                try:
                    normalize_spectrum_properties(layer.properties)
                except ValueError as exc:
                    raise RenderCompileError(str(exc)) from exc
            if layer.type in {
                "song_cover",
                "vinyl",
                "playlist_visual",
                "progress",
                "song_time",
            }:
                try:
                    normalize_visual_properties(layer.type, layer.properties)
                except ValueError as exc:
                    raise RenderCompileError(str(exc)) from exc
            if layer.type == "background":
                mode = str(
                    layer.properties.get(
                        "mode",
                        "asset" if layer.asset_refs else "solid",
                    )
                )
                if mode == "effect":
                    try:
                        normalize_effect_properties(layer.properties)
                    except ValueError as exc:
                        raise RenderCompileError(str(exc)) from exc
                elif mode not in {"solid", "asset"}:
                    raise RenderCompileError("Mode background harus solid/asset/effect.")
            active_layers.append(layer)

            if layer.type == "background":
                mode = str(
                    layer.properties.get(
                        "mode",
                        "asset" if layer.asset_refs else "solid",
                    )
                )
                if mode in {"solid", "effect"}:
                    continue
                if not layer.asset_refs:
                    raise RenderCompileError(
                        "Background asset tidak memiliki referensi media."
                    )
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
                    playback = str(layer.properties.get("playback", "loop"))
                    if playback not in {"loop", "freeze"}:
                        raise RenderCompileError(
                            "playback background harus loop/freeze."
                        )
                    if playback == "loop":
                        args += [
                            "-stream_loop",
                            "-1",
                            "-an",
                            "-i",
                            asset.locator,
                        ]
                    else:
                        args += ["-an", "-i", asset.locator]

        cover_layers = [
            layer for layer in active_layers if layer.type == "song_cover"
        ]
        for layer in cover_layers:
            props = normalize_visual_properties("song_cover", layer.properties)
            fallback_id = props["fallback_asset_id"]
            if fallback_id and fallback_id not in assets:
                raise RenderCompileError("Fallback cover tidak ditemukan di Media.")
            used_ids: set[str] = set()
            for event in plan.audio_events:
                song = songs[event.song_id]
                asset_id = song.cover_asset_id or fallback_id
                if not asset_id or asset_id in used_ids:
                    continue
                asset = assets.get(asset_id)
                if asset is None or asset.kind != "image":
                    raise RenderCompileError(
                        "Cover dinamis harus merujuk asset image."
                    )
                used_ids.add(asset_id)
                cover_input_index[(layer.layer_id, asset_id)] = next_input
                next_input += 1
                args += ["-loop", "1", "-i", asset.locator]

        spectrum_layers = [
            layer for layer in active_layers if layer.type == "spectrum"
        ]
        needs_album_audio = include_audio or bool(spectrum_layers)
        audio_input_index: dict[str, int] = {}
        if needs_album_audio:
            for event in plan.audio_events:
                asset = assets[event.asset_id]
                audio_input_index[event.song_id] = next_input
                next_input += 1
                source_in = ticks_to_seconds(event.source_in_tick)
                source_duration = ticks_to_seconds(
                    event.source_out_tick - event.source_in_tick
                )
                args += [
                    "-ss",
                    f"{source_in:.6f}",
                    "-t",
                    f"{source_duration:.6f}",
                    "-i",
                    asset.locator,
                ]

        filters: list[str] = ["[0:v]setpts=PTS-STARTPTS[v0]"]
        current = "v0"
        text_files: list[Path] = []

        spectrum_audio_labels: dict[str, str] = {}
        if needs_album_audio:
            audio_labels: list[str] = []
            for idx, event in enumerate(plan.audio_events):
                input_index = audio_input_index[event.song_id]
                label = f"aseg{idx}"
                event_duration = ticks_to_seconds(
                    event.end_tick - event.start_tick
                )
                filters.append(
                    f"[{input_index}:a]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=duration={event_duration:.6f},asetpts=PTS-STARTPTS[{label}]"
                )
                audio_labels.append(f"[{label}]")
            filters.append(
                "".join(audio_labels)
                + f"concat=n={len(audio_labels)}:v=0:a=1[album_audio]"
            )

            branches: list[tuple[str, str]] = []
            if include_audio:
                branches.append(("render", "aout"))
            for idx, layer in enumerate(spectrum_layers):
                label = f"specaudio{idx}"
                branches.append((layer.layer_id, label))
                spectrum_audio_labels[layer.layer_id] = label
            if len(branches) == 1:
                filters.append(f"[album_audio]anull[{branches[0][1]}]")
            else:
                outputs = "".join(f"[{label}]" for _, label in branches)
                filters.append(
                    f"[album_audio]asplit={len(branches)}{outputs}"
                )

        stage = 1
        for layer in active_layers:
            resolved_layer = resolved_by_layer.get(layer.layer_id)
            intervals = (
                []
                if resolved_layer is None
                else [
                    (item.start_tick, item.end_tick)
                    for item in resolved_layer.intervals
                ]
            )
            enable = _escape_enable(intervals)

            if layer.type == "background":
                out = f"v{stage}"
                local_stage = stage
                stage += 1
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                source_label = f"bg{local_stage}"
                mode = str(
                    layer.properties.get(
                        "mode",
                        "asset" if layer.asset_refs else "solid",
                    )
                )
                if mode == "solid":
                    color = _color(
                        layer.properties.get(
                            "color",
                            document.canvas.background_color,
                        )
                    )
                    filters.append(
                        f"color=c={color}:s={width}x{height}:r={fps:g}:d={duration:.6f},"
                        f"format=rgba,colorchannelmixer=aa={alpha:.6f}{rotate}[{source_label}]"
                    )
                elif mode == "effect":
                    try:
                        effect_chain = effect_source_filter(
                            layer.properties,
                            width=width,
                            height=height,
                            fps=fps,
                            duration=duration,
                            layer_opacity=alpha,
                        )
                    except ValueError as exc:
                        raise RenderCompileError(str(exc)) from exc
                    filters.append(
                        f"{effect_chain}{rotate}[{source_label}]"
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
                        raise RenderCompileError(
                            "Mode fit background tidak valid."
                        )
                    playback = str(layer.properties.get("playback", "loop"))
                    freeze = ""
                    if asset.kind == "video" and playback == "freeze":
                        freeze = (
                            f",trim=end_frame=1,loop=loop=-1:size=1:start=0,"
                            f"setpts=N/{fps:g}/TB"
                        )
                    motion = str(layer.properties.get("motion", "static"))
                    if motion not in {
                        "static",
                        "zoom_in",
                        "zoom_out",
                        "pan_left",
                        "pan_right",
                    }:
                        raise RenderCompileError(
                            "Motion background belum didukung."
                        )
                    motion_chain = ""
                    frame_count = max(1, round(duration * fps))
                    if motion == "zoom_in":
                        motion_chain = (
                            f",zoompan=z='min(1.08,1+0.08*on/{frame_count})':"
                            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                            f"d=1:s={width}x{height}:fps={fps:g}"
                        )
                    elif motion == "zoom_out":
                        motion_chain = (
                            f",zoompan=z='max(1,1.08-0.08*on/{frame_count})':"
                            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                            f"d=1:s={width}x{height}:fps={fps:g}"
                        )
                    elif motion in {"pan_left", "pan_right"}:
                        if motion == "pan_right":
                            x_expr = f"(iw-iw/zoom)*on/{frame_count}"
                        else:
                            x_expr = (
                                f"(iw-iw/zoom)*(1-on/{frame_count})"
                            )
                        motion_chain = (
                            f",zoompan=z='1.08':x='{x_expr}':"
                            f"y='ih/2-(ih/zoom/2)':d=1:"
                            f"s={width}x{height}:fps={fps:g}"
                        )
                    filters.append(
                        f"[{index}:v]{geometry}{freeze}{motion_chain},format=rgba,"
                        f"colorchannelmixer=aa={alpha:.6f},setpts=PTS-STARTPTS"
                        f"{rotate}[{source_label}]"
                    )
                filters.append(
                    f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                    f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                    f"eof_action=repeat:enable='{enable}'[{out}]"
                )
                current = out
                continue

            if layer.type == "song_cover":
                props = normalize_visual_properties(
                    "song_cover",
                    layer.properties,
                )
                fallback_id = props["fallback_asset_id"]
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
                for event in plan.audio_events:
                    song = songs[event.song_id]
                    asset_id = song.cover_asset_id or fallback_id
                    if not asset_id:
                        continue
                    grouped[asset_id].extend(
                        _intersect_intervals(
                            intervals,
                            event.start_tick,
                            event.end_tick,
                        )
                    )
                for asset_id, cover_intervals in grouped.items():
                    if not cover_intervals:
                        continue
                    index = cover_input_index[(layer.layer_id, asset_id)]
                    fit = props["fit"]
                    if fit == "fill":
                        geometry = (
                            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                            f"crop={width}:{height}"
                        )
                    else:
                        geometry = (
                            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0"
                        )
                    source_label = f"cover{stage}"
                    out = f"v{stage}"
                    stage += 1
                    filters.append(
                        f"[{index}:v]{geometry},format=rgba,"
                        f"colorchannelmixer=aa={alpha:.6f},setpts=PTS-STARTPTS"
                        f"{rotate}[{source_label}]"
                    )
                    filters.append(
                        f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                        f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                        f"eof_action=repeat:enable='{_escape_enable(cover_intervals)}'[{out}]"
                    )
                    current = out
                continue

            if layer.type == "vinyl":
                props = normalize_visual_properties("vinyl", layer.properties)
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                base = _rgb(props["color"])
                groove = _rgb(props["groove_color"])
                center_rgb = _rgb(props["center_color"])
                spin = props["spin_seconds"]
                center_ratio = props["center_ratio"]
                radius = "hypot(X-W/2,Y-H/2)"
                dot = (
                    f"lte(hypot(X-(W/2+cos(2*PI*T/{spin:.6f})*W*0.32),"
                    f"Y-(H/2+sin(2*PI*T/{spin:.6f})*H*0.32)),"
                    "min(W,H)*0.025)"
                )
                channel_exprs: list[str] = []
                for base_value, groove_value, center_value in zip(
                    base,
                    groove,
                    center_rgb,
                ):
                    channel_exprs.append(
                        f"if(lte({radius},min(W,H)*{center_ratio:.6f}),"
                        f"{center_value},if({dot},{groove_value},"
                        f"if(lt(mod({radius},12),1.4),{groove_value},{base_value})))"
                    )
                source_label = f"vinyl{stage}"
                out = f"v{stage}"
                stage += 1
                filters.append(
                    f"nullsrc=s={width}x{height}:r={fps:g}:d={duration:.6f},"
                    f"format=rgba,geq=r='{channel_exprs[0]}':"
                    f"g='{channel_exprs[1]}':b='{channel_exprs[2]}':"
                    f"a='if(lte({radius},min(W,H)/2),255,0)',"
                    f"colorchannelmixer=aa={alpha:.6f}{rotate}[{source_label}]"
                )
                filters.append(
                    f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                    f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                    f"eof_action=pass:enable='{enable}'[{out}]"
                )
                current = out
                continue

            if layer.type == "playlist_visual":
                props = normalize_visual_properties(
                    "playlist_visual",
                    layer.properties,
                )
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                max_items = props["max_items"]
                fontcolor = _color(props["color"])
                active_color = _color(props["active_color"])
                fontsize = props["font_size"]
                row_height = height / max(1, max_items)
                source_label = f"playlist{stage}"
                out = f"v{stage}"
                stage += 1
                chain = (
                    f"color=c=black@0:s={width}x{height}:r={fps:g}:d={duration:.6f},"
                    f"format=rgba,drawbox=x=0:y=0:w=iw:h=ih:"
                    f"color=black@{props['background_opacity']:.3f}:t=fill:"
                    f"enable='{enable}'"
                )
                events = list(plan.audio_events)
                font_path = str(
                    layer.properties.get("font_path", "") or ""
                ).strip()
                font_prefix = (
                    f"fontfile='{_filter_path(Path(font_path))}':"
                    if font_path
                    else ""
                )
                for page_index in range(0, len(events), max_items):
                    page = events[page_index : page_index + max_items]
                    if not page:
                        continue
                    page_intervals = _intersect_intervals(
                        intervals,
                        page[0].start_tick,
                        page[-1].end_tick,
                    )
                    page_enable = _escape_enable(page_intervals)
                    for row_index, event in enumerate(page):
                        song = songs[event.song_id]
                        asset = assets[song.asset_id]
                        title = (
                            song.display_title or Path(asset.locator).stem
                        ).strip()
                        if props["show_artist"] and song.display_artist:
                            title = f"{title} — {song.display_artist.strip()}"
                        if props["numbered"]:
                            title = (
                                f"{page_index + row_index + 1:02d}. {title}"
                            )
                        title = title[:96]
                        text_path = work / (
                            f"playlist-{layer.layer_id}-{page_index + row_index}.txt"
                        )
                        text_path.write_text(title, encoding="utf-8")
                        text_files.append(text_path)
                        y = row_index * row_height
                        common = (
                            f"{font_prefix}textfile='{_filter_path(text_path)}':"
                            f"reload=0:x=10:y='{y:.3f}+({row_height:.3f}-text_h)/2':"
                            f"fontsize={fontsize}"
                        )
                        chain += (
                            f",drawtext={common}:fontcolor={fontcolor}:"
                            f"enable='{page_enable}'"
                        )
                        active_intervals = _intersect_intervals(
                            intervals,
                            event.start_tick,
                            event.end_tick,
                        )
                        chain += (
                            f",drawtext={common}:fontcolor={active_color}:"
                            f"enable='{_escape_enable(active_intervals)}'"
                        )
                chain += (
                    f",colorchannelmixer=aa={alpha:.6f}{rotate}[{source_label}]"
                )
                filters.append(chain)
                filters.append(
                    f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                    f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                    f"eof_action=pass:enable='{enable}'[{out}]"
                )
                current = out
                continue

            if layer.type == "progress":
                props = normalize_visual_properties("progress", layer.properties)
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                bg = _rgb(props["background_color"])
                fill = _rgb(props["fill_color"])

                def append_progress_source(
                    source_duration: float,
                    start_tick: int,
                    source_enable: str,
                ) -> None:
                    nonlocal current, stage
                    if source_duration <= 0:
                        return
                    ratio = f"min(1,max(0,T/{source_duration:.6f}))"
                    source_label = f"progress{stage}"
                    out_label = f"v{stage}"
                    stage += 1
                    setpts = (
                        ""
                        if start_tick <= 0
                        else f",setpts=PTS+{ticks_to_seconds(start_tick):.6f}/TB"
                    )
                    filters.append(
                        f"nullsrc=s={width}x{height}:r={fps:g}:d={source_duration:.6f},"
                        f"format=rgba,geq=r='if(lte(X,W*({ratio})),{fill[0]},{bg[0]})':"
                        f"g='if(lte(X,W*({ratio})),{fill[1]},{bg[1]})':"
                        f"b='if(lte(X,W*({ratio})),{fill[2]},{bg[2]})':a='255',"
                        f"colorchannelmixer=aa={alpha:.6f}{rotate}{setpts}"
                        f"[{source_label}]"
                    )
                    filters.append(
                        f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                        f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                        f"eof_action=pass:enable='{source_enable}'[{out_label}]"
                    )
                    current = out_label

                if props["mode"] == "album":
                    append_progress_source(duration, 0, enable)
                else:
                    for event in plan.audio_events:
                        event_intervals = _intersect_intervals(
                            intervals,
                            event.start_tick,
                            event.end_tick,
                        )
                        append_progress_source(
                            ticks_to_seconds(event.end_tick - event.start_tick),
                            event.start_tick,
                            _escape_enable(event_intervals),
                        )
                continue

            if layer.type == "song_time":
                props = normalize_visual_properties("song_time", layer.properties)
                width, height = _layer_size(layer, document)
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                fontcolor = _color(props["color"])
                fontsize = props["font_size"]
                font_path = str(
                    layer.properties.get("font_path", "") or ""
                ).strip()
                font_prefix = (
                    f"fontfile='{_filter_path(Path(font_path))}':"
                    if font_path
                    else ""
                )

                def append_time_source(
                    source_tick: int,
                    start_tick: int,
                    source_enable: str,
                ) -> None:
                    nonlocal current, stage
                    source_duration = ticks_to_seconds(source_tick)
                    if source_duration <= 0:
                        return
                    source_label = f"songtime{stage}"
                    out_label = f"v{stage}"
                    stage += 1
                    setpts = (
                        ""
                        if start_tick <= 0
                        else f",setpts=PTS+{ticks_to_seconds(start_tick):.6f}/TB"
                    )
                    filters.append(
                        f"color=c=black@0:s={width}x{height}:r={fps:g}:d={source_duration:.6f},"
                        f"format=rgba,drawtext={font_prefix}text='{_clock_text(source_tick)}':"
                        f"x=0:y='(h-text_h)/2':fontsize={fontsize}:fontcolor={fontcolor},"
                        f"colorchannelmixer=aa={alpha:.6f}{rotate}{setpts}[{source_label}]"
                    )
                    filters.append(
                        f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                        f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                        f"eof_action=pass:enable='{source_enable}'[{out_label}]"
                    )
                    current = out_label

                if props["mode"] == "album":
                    append_time_source(resolved.duration_tick, 0, enable)
                else:
                    for event in plan.audio_events:
                        event_intervals = _intersect_intervals(
                            intervals,
                            event.start_tick,
                            event.end_tick,
                        )
                        append_time_source(
                            event.end_tick - event.start_tick,
                            event.start_tick,
                            _escape_enable(event_intervals),
                        )
                continue

            if layer.type == "spectrum":
                out = f"v{stage}"
                local_stage = stage
                stage += 1
                width, height = _layer_size(layer, document)
                props = normalize_spectrum_properties(layer.properties)
                style = props["style"]
                gain = props["gain"]
                color = _color(props["color"])
                ascale = _ffmpeg_scale(props["amplitude_scale"])
                audio_label = spectrum_audio_labels[layer.layer_id]
                source_label = f"spec{local_stage}"
                if style == "circular_spectrum":
                    fscale = _ffmpeg_scale(props["frequency_scale"])
                    try:
                        visual_chain = circular_spectrum_filter(
                            width=width,
                            height=height,
                            color=color,
                            frequency_scale=fscale,
                            amplitude_scale=ascale,
                            inner_ratio=props["inner_ratio"],
                        )
                    except ValueError as exc:
                        raise RenderCompileError(str(exc)) from exc
                elif style in {"bars", "spectrum_line"}:
                    mode = "bar" if style == "bars" else "line"
                    fscale = _ffmpeg_scale(props["frequency_scale"])
                    visualizer = (
                        f"showfreqs=s={width}x{height}:mode={mode}:"
                        f"fscale={fscale}:ascale={ascale}:colors={color}"
                    )
                    visual_chain = (
                        f"{visualizer},format=rgba,"
                        "colorkey=0x000000:0.08:0.0"
                    )
                else:
                    split = (
                        ":split_channels=1"
                        if style == "stereo_waveform"
                        else ""
                    )
                    visualizer = (
                        f"showwaves=s={width}x{height}:mode=line:scale={ascale}:"
                        f"colors={color}{split}"
                    )
                    visual_chain = (
                        f"{visualizer},format=rgba,"
                        "colorkey=0x000000:0.08:0.0"
                    )
                mirror = ",vflip" if props["mirror"] else ""
                rotate = _rotation_chain(layer)
                alpha = max(0.0, min(1.0, float(layer.opacity)))
                filters.append(
                    f"[{audio_label}]volume={gain:.6f},{visual_chain},"
                    f"colorchannelmixer=aa={alpha:.6f}"
                    f"{mirror}{rotate}[{source_label}]"
                )
                filters.append(
                    f"[{current}][{source_label}]overlay=x='{_overlay_position_expr(layer, 'x')}':"
                    f"y='{_overlay_position_expr(layer, 'y')}':shortest=0:"
                    f"eof_action=pass:enable='{enable}'[{out}]"
                )
                current = out
                continue

            if abs(float(layer.transform.rotation)) > 0.0001:
                raise RenderCompileError(
                    "Rotasi text/judul dinamis belum didukung."
                )

            if layer.type == "song_title":
                template = str(
                    layer.properties.get("template", "{title}\n{artist}")
                )
                fontcolor = _color(
                    layer.properties.get("color", "#ffffff")
                )
                fontsize = _font_size(layer, document.canvas.height)
                for event in plan.audio_events:
                    event_intervals = _intersect_intervals(
                        intervals,
                        event.start_tick,
                        event.end_tick,
                    )
                    if not event_intervals:
                        continue
                    song = songs[event.song_id]
                    text = dynamic_song_text(
                        template,
                        song.display_title,
                        song.display_artist,
                    )
                    text_path = work / (
                        f"song-title-{layer.layer_id}-{event.song_id}.txt"
                    )
                    text_path.write_text(text, encoding="utf-8")
                    text_files.append(text_path)
                    out = f"v{stage}"
                    stage += 1
                    parts = [
                        f"textfile='{_filter_path(text_path)}'",
                        "reload=0",
                        f"x={_position_expr(layer, 'x')}",
                        f"y={_position_expr(layer, 'y')}",
                        f"fontsize={fontsize}",
                        f"fontcolor={fontcolor}",
                        f"alpha={layer.opacity:.6f}",
                        f"enable='{_escape_enable(event_intervals)}'",
                    ]
                    font_path = str(
                        layer.properties.get("font_path", "") or ""
                    ).strip()
                    if font_path:
                        parts.insert(
                            0,
                            f"fontfile='{_filter_path(Path(font_path))}'",
                        )
                    filters.append(
                        f"[{current}]drawtext="
                        + ":".join(parts)
                        + f"[{out}]"
                    )
                    current = out
                continue

            text = str(layer.properties.get("text", ""))
            text_path = work / f"text-{layer.layer_id}.txt"
            text_path.write_text(text, encoding="utf-8")
            text_files.append(text_path)
            fontcolor = _color(layer.properties.get("color", "#ffffff"))
            fontsize = _font_size(layer, document.canvas.height)
            out = f"v{stage}"
            stage += 1
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
            font_path = str(
                layer.properties.get("font_path", "") or ""
            ).strip()
            if font_path:
                parts.insert(
                    0,
                    f"fontfile='{_filter_path(Path(font_path))}'",
                )
            filters.append(
                f"[{current}]drawtext=" + ":".join(parts) + f"[{out}]"
            )
            current = out

        filters.append(f"[{current}]format=yuv420p[vout]")

        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
        ]
        if include_audio:
            args += ["-map", "[aout]"]
        encoder = (
            "libx265"
            if document.render_settings.get("codec") == "h265"
            else "libx264"
        )
        args += [
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            "-r",
            f"{fps:g}",
        ]
        if include_audio:
            args += [
                "-c:a",
                "aac",
                "-b:a",
                str(document.render_settings.get("audio_bitrate", "320k")),
            ]
        args += [
            "-t",
            f"{duration:.6f}",
            "-movflags",
            "+faststart",
            str(destination),
        ]
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
        compiled = self.compile_video(
            document,
            destination,
            work_dir,
            include_audio=False,
        )
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
        return CompiledFFmpeg(
            tuple(args),
            compiled.render_plan,
            compiled.text_files,
        )
