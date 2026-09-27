from types import SimpleNamespace

from full_album_maker.editor_models import ProjectDocument
from full_album_maker.legacy_sync_v2 import sync_legacy_media


def _item(path, duration, **extras):
    data = {"path": path, "duration": duration}
    data.update(extras)
    return SimpleNamespace(**data)


def test_legacy_sync_preserves_asset_ids_and_does_not_reseed_nonempty_playlist():
    legacy = SimpleNamespace(
        videos=[_item("bg.mp4", 8.0)],
        audios=[_item("a.mp3", 2.0), _item("b.mp3", 3.0)],
        images=[],
        _active_audio_paths=["b.mp3"],
    )
    doc, changed = sync_legacy_media(ProjectDocument.new_empty(), legacy)
    assert changed
    ids = {asset.locator: asset.asset_id for asset in doc.media}
    assert [doc.asset_map()[song.asset_id].locator for song in doc.playlist.entries] == ["b.mp3"]

    # New media is merged but an already-owned v2 playlist is not silently reset.
    legacy.audios.append(_item("c.mp3", 4.0))
    merged, changed = sync_legacy_media(doc, legacy)
    assert changed
    assert {asset.locator: asset.asset_id for asset in merged.media}["a.mp3"] == ids["a.mp3"]
    assert [merged.asset_map()[song.asset_id].locator for song in merged.playlist.entries] == ["b.mp3"]
    assert "c.mp3" in {asset.locator for asset in merged.media}
