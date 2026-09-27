from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .editor_commands import CommandError, EditorCommand, ReorderSongs
from .editor_models import ProjectDocument, SongInstance
from .playlist_service_v2 import PlaylistServiceV2


@dataclass
class MoveSong(EditorCommand):
    song_id: str
    before_song_id: str | None = None
    target_position: int | None = None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        current = [song.song_id for song in document.playlist.entries]
        requested = PlaylistServiceV2.ordered_ids_for_move(
            document,
            self.song_id,
            before_song_id=self.before_song_id,
            target_position=self.target_position,
        )
        ReorderSongs(requested).apply(document)
        return ReorderSongs(current)


@dataclass
class RemoveSong(EditorCommand):
    song_id: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        for index, song in enumerate(document.playlist.entries):
            if song.song_id == self.song_id:
                removed = deepcopy(song)
                del document.playlist.entries[index]
                return RestoreSong(removed, index)
        raise CommandError("Lagu tidak ditemukan di playlist.")


@dataclass
class RestoreSong(EditorCommand):
    song: SongInstance
    index: int

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if self.song.song_id in document.song_map():
            raise CommandError("song_id sudah ada di playlist.")
        restored = deepcopy(self.song)
        restored.validate()
        if restored.asset_id not in document.asset_map():
            raise CommandError("Asset lagu yang dipulihkan tidak ditemukan.")
        index = max(0, min(int(self.index), len(document.playlist.entries)))
        document.playlist.entries.insert(index, restored)
        return RemoveSong(restored.song_id)


@dataclass
class SetSongTitle(EditorCommand):
    song_id: str
    title: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        song = document.song_map().get(self.song_id)
        if song is None:
            raise CommandError("Lagu tidak ditemukan.")
        if not isinstance(self.title, str):
            raise CommandError("Judul lagu harus berupa teks.")
        old = song.display_title
        song.display_title = self.title.strip()
        return SetSongTitle(self.song_id, old)


@dataclass
class SetSongArtist(EditorCommand):
    song_id: str
    artist: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        song = document.song_map().get(self.song_id)
        if song is None:
            raise CommandError("Lagu tidak ditemukan.")
        if not isinstance(self.artist, str):
            raise CommandError("Nama artist harus berupa teks.")
        old = song.display_artist
        song.display_artist = self.artist.strip()
        return SetSongArtist(self.song_id, old)


@dataclass
class SetSongVisual(EditorCommand):
    song_id: str
    asset_id: str | None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        song = document.song_map().get(self.song_id)
        if song is None:
            raise CommandError("Lagu tidak ditemukan.")
        if self.asset_id is not None:
            asset = document.asset_map().get(self.asset_id)
            if asset is None:
                raise CommandError("Asset visual tidak ditemukan.")
            if asset.kind not in {"image", "video"}:
                raise CommandError("Visual lagu harus berupa image/video.")
        old = song.visual_asset_id
        song.visual_asset_id = self.asset_id
        return SetSongVisual(self.song_id, old)


@dataclass
class SetSongCover(EditorCommand):
    song_id: str
    asset_id: str | None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        song = document.song_map().get(self.song_id)
        if song is None:
            raise CommandError("Lagu tidak ditemukan.")
        if self.asset_id is not None:
            asset = document.asset_map().get(self.asset_id)
            if asset is None:
                raise CommandError("Asset cover tidak ditemukan.")
            if asset.kind != "image":
                raise CommandError("Cover lagu harus berupa image.")
        old = song.cover_asset_id
        song.cover_asset_id = self.asset_id
        return SetSongCover(self.song_id, old)
