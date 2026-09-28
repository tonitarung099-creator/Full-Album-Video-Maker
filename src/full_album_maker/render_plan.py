from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .editor_models import ProjectDocument
from .timeline_resolver import ResolvedTimeline, TimelineResolver

RENDER_PLAN_FORMAT = "full-album-maker-render-plan"
RENDER_PLAN_VERSION = 1


@dataclass(frozen=True)
class RenderAudioEvent:
    song_id: str
    asset_id: str
    source_in_tick: int
    source_out_tick: int
    start_tick: int
    end_tick: int
    gain: float
    crossfade_in_tick: int


@dataclass(frozen=True)
class RenderLayerEvent:
    layer_id: str
    layer_type: str
    order: int
    intervals: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class RenderPlan:
    format: str
    version: int
    project_id: str
    source_revision: int
    content_signature: str
    timebase: int
    duration_tick: int
    audio_events: tuple[RenderAudioEvent, ...] = field(default_factory=tuple)
    layer_events: tuple[RenderLayerEvent, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "version": self.version,
            "project_id": self.project_id,
            "source_revision": self.source_revision,
            "content_signature": self.content_signature,
            "timebase": self.timebase,
            "duration_tick": self.duration_tick,
            "audio_events": [asdict(x) for x in self.audio_events],
            "layer_events": [
                {
                    "layer_id": x.layer_id,
                    "layer_type": x.layer_type,
                    "order": x.order,
                    "intervals": [list(pair) for pair in x.intervals],
                }
                for x in self.layer_events
            ],
        }


def compile_render_plan(
    document: ProjectDocument,
    resolved: ResolvedTimeline | None = None,
) -> RenderPlan:
    document.validate()
    resolved = resolved or TimelineResolver().resolve(document)
    if resolved.errors:
        raise ValueError("Timeline belum siap dirender: " + " | ".join(resolved.errors))
    assets = document.asset_map()
    songs = document.song_map()
    audio_events: list[RenderAudioEvent] = []
    for event in resolved.songs:
        song = songs[event.song_id]
        asset = assets[event.asset_id]
        source_out = (
            song.source_out_tick
            if song.source_out_tick is not None
            else asset.source_duration_tick
        )
        audio_events.append(
            RenderAudioEvent(
                song_id=event.song_id,
                asset_id=event.asset_id,
                source_in_tick=song.source_in_tick,
                source_out_tick=source_out,
                start_tick=event.start_tick,
                end_tick=event.end_tick,
                gain=float(song.gain),
                crossfade_in_tick=(
                    int(song.crossfade_in_tick)
                    if document.playlist.mode == "free"
                    else 0
                ),
            )
        )
    layers = document.layer_map()
    layer_events = tuple(
        RenderLayerEvent(
            layer_id=item.layer_id,
            layer_type=layers[item.layer_id].type,
            order=layers[item.layer_id].order,
            intervals=tuple((x.start_tick, x.end_tick) for x in item.intervals),
        )
        for item in resolved.layers
    )
    return RenderPlan(
        format=RENDER_PLAN_FORMAT,
        version=RENDER_PLAN_VERSION,
        project_id=document.project_id,
        source_revision=document.revision,
        content_signature=document.content_signature(),
        timebase=document.timebase,
        duration_tick=resolved.duration_tick,
        audio_events=tuple(audio_events),
        layer_events=layer_events,
    )
