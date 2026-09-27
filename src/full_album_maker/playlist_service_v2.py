from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .editor_commands import CommandError
from .editor_models import ProjectDocument, SongInstance
from .timeline_resolver import TimelineResolver


@dataclass(frozen=True)
class PlaylistRow:
    position: int
    song_id: str
    asset_id: str
    title: str
    artist: str
    original_name: str
    duration_tick: int
    cover_asset_id: str | None
    visual_asset_id: str | None


@dataclass(frozen=True)
class PlaylistMarker:
    position: int
    song_id: str
    title: str
    artist: str
    start_tick: int
    end_tick: int


def _metadata_text(asset, *keys: str) -> str:
    for key in keys:
        value = asset.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _song_title(asset, song: SongInstance) -> str:
    if song.display_title.strip():
        return song.display_title.strip()
    metadata = _metadata_text(asset, "display_title", "title", "TITLE")
    if metadata:
        return metadata
    name = asset.original_name or Path(asset.locator).name
    return Path(name).stem


def _song_artist(asset, song: SongInstance) -> str:
    if song.display_artist.strip():
        return song.display_artist.strip()
    return _metadata_text(asset, "display_artist", "artist", "ARTIST")


def song_duration_tick(document: ProjectDocument, song: SongInstance) -> int:
    asset = document.asset_map().get(song.asset_id)
    if asset is None:
        raise CommandError("Lagu merujuk asset yang tidak ada.")
    source_out = song.source_out_tick if song.source_out_tick is not None else asset.source_duration_tick
    duration = source_out - song.source_in_tick
    if duration <= 0:
        raise CommandError("Durasi lagu tidak valid.")
    return duration


class PlaylistServiceV2:
    """Pure playlist operations keyed by stable IDs, never by displayed row/path."""

    @staticmethod
    def build_entries(document: ProjectDocument, asset_ids: list[str]) -> list[SongInstance]:
        assets = document.asset_map()
        result: list[SongInstance] = []
        for asset_id in asset_ids:
            asset = assets.get(asset_id)
            if asset is None:
                raise CommandError("Asset playlist tidak ditemukan.")
            if asset.kind != "audio":
                raise CommandError("Playlist hanya dapat memakai asset audio.")
            title = _metadata_text(asset, "display_title", "title", "TITLE")
            artist = _metadata_text(asset, "display_artist", "artist", "ARTIST")
            result.append(
                SongInstance(
                    asset_id=asset.asset_id,
                    display_title=title,
                    display_artist=artist,
                    source_in_tick=0,
                    source_out_tick=asset.source_duration_tick or None,
                )
            )
        return result

    @classmethod
    def use_all_audio(cls, document: ProjectDocument) -> list[SongInstance]:
        return cls.build_entries(
            document,
            [asset.asset_id for asset in document.media if asset.kind == "audio"],
        )

    @staticmethod
    def ordered_ids_for_move(
        document: ProjectDocument,
        song_id: str,
        *,
        before_song_id: str | None = None,
        target_position: int | None = None,
    ) -> list[str]:
        ids = [song.song_id for song in document.playlist.entries]
        if song_id not in ids:
            raise CommandError("Lagu yang dipindahkan tidak ditemukan.")
        if before_song_id is not None and target_position is not None:
            raise CommandError("Pilih before_song_id atau target_position, bukan keduanya.")

        ids.remove(song_id)
        if before_song_id is not None:
            if before_song_id == song_id:
                return [song.song_id for song in document.playlist.entries]
            if before_song_id not in ids:
                raise CommandError("Lagu tujuan tidak ditemukan.")
            ids.insert(ids.index(before_song_id), song_id)
            return ids

        if target_position is None:
            ids.append(song_id)
            return ids
        if not 1 <= int(target_position) <= len(ids) + 1:
            raise CommandError("Posisi tujuan playlist tidak valid.")
        ids.insert(int(target_position) - 1, song_id)
        return ids

    @staticmethod
    def rows(document: ProjectDocument, query: str = "") -> list[PlaylistRow]:
        document.validate()
        assets = document.asset_map()
        needle = " ".join(str(query or "").casefold().split())
        rows: list[PlaylistRow] = []
        for position, song in enumerate(document.playlist.entries, start=1):
            asset = assets[song.asset_id]
            title = _song_title(asset, song)
            artist = _song_artist(asset, song)
            original = asset.original_name or Path(asset.locator).name
            haystack = " ".join((title, artist, original)).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(
                PlaylistRow(
                    position=position,
                    song_id=song.song_id,
                    asset_id=song.asset_id,
                    title=title,
                    artist=artist,
                    original_name=original,
                    duration_tick=song_duration_tick(document, song),
                    cover_asset_id=song.cover_asset_id,
                    visual_asset_id=song.visual_asset_id,
                )
            )
        return rows

    @staticmethod
    def reorder_allowed(query: str = "") -> bool:
        # Reordering a filtered list is ambiguous because visual row numbers no
        # longer equal global playlist positions. The UI can still offer an
        # explicit "pindah ke nomor" action using a global target position.
        return not bool(str(query or "").strip())

    @staticmethod
    def markers(document: ProjectDocument) -> list[PlaylistMarker]:
        resolved = TimelineResolver().resolve(document)
        enabled_count = sum(1 for song in document.playlist.entries if song.enabled)
        # Visual-layer errors must not hide playlist markers. Only a broken song
        # schedule (a missing/invalid duration that caused a song to be skipped)
        # blocks marker publication.
        if len(resolved.songs) != enabled_count:
            raise CommandError("Schedule lagu belum valid untuk membuat marker playlist.")
        song_map = document.song_map()
        assets = document.asset_map()
        result: list[PlaylistMarker] = []
        for position, event in enumerate(resolved.songs, start=1):
            song = song_map[event.song_id]
            asset = assets[event.asset_id]
            result.append(
                PlaylistMarker(
                    position=position,
                    song_id=event.song_id,
                    title=_song_title(asset, song),
                    artist=_song_artist(asset, song),
                    start_tick=event.start_tick,
                    end_tick=event.end_tick,
                )
            )
        return result
