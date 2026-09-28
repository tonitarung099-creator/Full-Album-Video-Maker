from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .editor_commands import CommandError, EditorCommand
from .editor_models import ProjectDocument
from .timeline_resolver import TimelineResolver


@dataclass(frozen=True)
class _SongTiming:
    song_id: str
    free_start_tick: int | None
    crossfade_in_tick: int


@dataclass
class RestorePlaylistTiming(EditorCommand):
    mode: str
    timings: tuple[_SongTiming, ...]

    def apply(self, document: ProjectDocument) -> EditorCommand:
        inverse = _capture_timing(document)
        if self.mode not in {"packed", "free"}:
            raise CommandError("Mode playlist tidak valid.")
        by_id = document.song_map()
        if {item.song_id for item in self.timings} != set(by_id):
            raise CommandError("Snapshot timing tidak cocok dengan playlist saat ini.")
        document.playlist.mode = self.mode
        for item in self.timings:
            song = by_id[item.song_id]
            song.free_start_tick = item.free_start_tick
            song.crossfade_in_tick = int(item.crossfade_in_tick)
        document.playlist.validate()
        if self.mode == "free":
            _raise_audio_contract_errors(document)
        return RestorePlaylistTiming(inverse[0], inverse[1])


@dataclass
class SetPlaylistTimingMode(EditorCommand):
    mode: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        target = str(self.mode)
        if target not in {"packed", "free"}:
            raise CommandError("Mode timeline audio harus packed atau free.")
        old_mode, old_timings = _capture_timing(document)
        if target == old_mode:
            return RestorePlaylistTiming(old_mode, old_timings)

        if target == "free":
            # Conversion preserves the exact packed positions first. The user can
            # then introduce gaps/crossfades explicitly without changing playback
            # merely by enabling Free Timeline.
            assets = document.asset_map()
            cursor = 0
            for song in document.playlist.entries:
                song.crossfade_in_tick = 0
                if not song.enabled:
                    song.free_start_tick = None
                    continue
                asset = assets[song.asset_id]
                source_out = (
                    song.source_out_tick
                    if song.source_out_tick is not None
                    else asset.source_duration_tick
                )
                duration = source_out - song.source_in_tick
                if duration <= 0:
                    raise CommandError("Durasi lagu tidak valid untuk konversi Free Timeline.")
                song.free_start_tick = cursor
                cursor += duration
            document.playlist.mode = "free"
            _raise_audio_contract_errors(document)
        else:
            # Packed is an explicit compact conversion. Free-only timing metadata
            # is removed so the strict legacy validator remains authoritative.
            document.playlist.mode = "packed"
            for song in document.playlist.entries:
                song.free_start_tick = None
                song.crossfade_in_tick = 0
            document.playlist.validate()

        return RestorePlaylistTiming(old_mode, old_timings)


@dataclass
class SetSongFreeTiming(EditorCommand):
    song_id: str
    start_tick: int
    crossfade_in_tick: int = 0

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if document.playlist.mode != "free":
            raise CommandError("Timing bebas hanya dapat diubah pada mode Free Timeline.")
        song = document.song_map().get(self.song_id)
        if song is None:
            raise CommandError("Lagu tidak ditemukan.")
        if not song.enabled:
            raise CommandError("Lagu nonaktif tidak dapat diberi timing bebas.")
        if isinstance(self.start_tick, bool) or int(self.start_tick) < 0:
            raise CommandError("Start lagu tidak boleh negatif.")
        if isinstance(self.crossfade_in_tick, bool) or int(self.crossfade_in_tick) < 0:
            raise CommandError("Crossfade tidak boleh negatif.")

        old_start = song.free_start_tick
        old_crossfade = song.crossfade_in_tick
        song.free_start_tick = int(self.start_tick)
        song.crossfade_in_tick = int(self.crossfade_in_tick)
        try:
            _raise_audio_contract_errors(document)
        except Exception:
            song.free_start_tick = old_start
            song.crossfade_in_tick = old_crossfade
            raise
        return SetSongFreeTiming(
            self.song_id,
            0 if old_start is None else old_start,
            old_crossfade,
        )


def _capture_timing(document: ProjectDocument) -> tuple[str, tuple[_SongTiming, ...]]:
    return (
        document.playlist.mode,
        tuple(
            _SongTiming(
                song.song_id,
                song.free_start_tick,
                song.crossfade_in_tick,
            )
            for song in document.playlist.entries
        ),
    )


def _raise_audio_contract_errors(document: ProjectDocument) -> None:
    resolved = TimelineResolver().resolve(document)
    audio_errors = [error for error in resolved.errors if error.startswith("Audio: ")]
    if audio_errors:
        raise CommandError(" | ".join(audio_errors))


def clone_with_free_timing(
    document: ProjectDocument,
    song_id: str,
    *,
    start_tick: int,
    crossfade_in_tick: int = 0,
) -> ProjectDocument:
    """Pure helper used by tests/UI previews; source document is never mutated."""
    clone = deepcopy(document)
    SetSongFreeTiming(song_id, start_tick, crossfade_in_tick).apply(clone)
    clone.validate()
    return clone
