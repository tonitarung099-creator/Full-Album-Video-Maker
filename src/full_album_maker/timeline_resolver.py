from __future__ import annotations

from dataclasses import dataclass, field

from .editor_models import Layer, ProjectDocument, ProjectSchemaError


@dataclass(frozen=True)
class ResolvedSong:
    song_id: str
    asset_id: str
    start_tick: int
    end_tick: int


@dataclass(frozen=True)
class ResolvedInterval:
    start_tick: int
    end_tick: int


@dataclass
class ResolvedLayer:
    layer_id: str
    intervals: list[ResolvedInterval] = field(default_factory=list)
    error: str | None = None


@dataclass
class ResolvedTimeline:
    revision: int
    duration_tick: int
    songs: list[ResolvedSong]
    layers: list[ResolvedLayer]
    errors: list[str]


class TimelineResolver:
    def resolve(self, document: ProjectDocument) -> ResolvedTimeline:
        document.validate()
        assets = document.asset_map()
        songs: list[ResolvedSong] = []
        cursor = 0
        errors: list[str] = []

        if document.playlist.mode != "packed":
            raise ProjectSchemaError("Resolver S01 baru mendukung playlist mode packed.")

        for song in document.playlist.entries:
            if not song.enabled:
                continue
            asset = assets[song.asset_id]
            source_out = song.source_out_tick if song.source_out_tick is not None else asset.source_duration_tick
            duration = source_out - song.source_in_tick
            if duration <= 0:
                errors.append(f"Durasi lagu tidak valid: {song.song_id}")
                continue
            songs.append(ResolvedSong(song.song_id, song.asset_id, cursor, cursor + duration))
            cursor += duration

        by_song = {item.song_id: item for item in songs}
        resolved_layers: list[ResolvedLayer] = []
        track_map = {track.track_id: track for track in document.tracks}

        for layer in sorted(document.layers, key=lambda x: x.order):
            track = track_map[layer.track_id]
            if not layer.enabled or not track.enabled:
                continue
            resolved = self._resolve_layer(layer, by_song, cursor)
            resolved_layers.append(resolved)
            if resolved.error:
                errors.append(f"{layer.name}: {resolved.error}")

        return ResolvedTimeline(document.revision, cursor, songs, resolved_layers, errors)

    @staticmethod
    def _resolve_layer(layer: Layer, by_song: dict[str, ResolvedSong], album_end: int) -> ResolvedLayer:
        binding = layer.time_binding
        result = ResolvedLayer(layer.layer_id)

        def append(start: int, end: int) -> None:
            start = max(0, start)
            end = min(album_end, end) if album_end > 0 else end
            if end > start:
                result.intervals.append(ResolvedInterval(start, end))

        if binding.kind == "absolute":
            duration = binding.duration_tick or 0
            append(binding.start_tick, binding.start_tick + duration)
            if duration <= 0:
                result.error = "Layer absolute belum memiliki durasi aktif."
            return result

        if binding.kind == "album":
            start = binding.start_offset_tick
            end = album_end - binding.end_offset_tick
            if binding.duration_tick is not None:
                end = min(end, start + binding.duration_tick)
            append(start, end)
            return result

        if binding.kind == "song":
            song = by_song.get(binding.song_id or "")
            if song is None:
                result.error = "Anchor lagu tidak ditemukan."
                return result
            start = song.start_tick + binding.offset_tick
            end = song.end_tick
            if binding.duration_tick is not None:
                end = min(end, start + binding.duration_tick)
            append(start, end)
            return result

        if binding.kind == "song_range":
            missing = [song_id for song_id in binding.ordered_song_ids if song_id not in by_song]
            if missing:
                result.error = "Satu atau lebih anchor song_range tidak ditemukan."
                return result
            for song_id in binding.ordered_song_ids:
                song = by_song[song_id]
                start = song.start_tick + binding.offset_tick
                end = song.end_tick
                if binding.duration_tick is not None:
                    end = min(end, start + binding.duration_tick)
                append(start, end)
            return result

        result.error = "Binding waktu tidak didukung."
        return result
