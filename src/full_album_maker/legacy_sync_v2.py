from __future__ import annotations

from pathlib import Path

from .editor_models import MediaAsset, ProjectDocument, SongInstance, infer_asset_kind, seconds_to_tick


def _path_key(value: str) -> str:
    return str(Path(value).expanduser()).replace("\\", "/").casefold()


def _item_text(item, name: str) -> str:
    value = getattr(item, name, "")
    return str(value or "").strip()


def sync_legacy_media(document: ProjectDocument, legacy_project) -> tuple[ProjectDocument, bool]:
    """Merge legacy Media-panel assets into v2 without destroying editor edits.

    Existing v2 IDs are retained. New media are appended. Playlist is seeded from
    the legacy active playlist only while the v2 playlist is still empty; after
    that, playlist order is owned by the v2 editor.
    """

    before = document.content_signature()
    result = document.clone()
    by_key = {(asset.kind, _path_key(asset.locator)): asset for asset in result.media}

    def add_or_update(kind: str, item) -> MediaAsset:
        path = str(getattr(item, "path", "") or "").strip()
        if not path:
            raise ValueError("Media legacy memiliki path kosong.")
        key = (kind, _path_key(path))
        duration = seconds_to_tick(max(0.0, float(getattr(item, "duration", 0.0) or 0.0)))
        asset = by_key.get(key)
        metadata = {}
        if kind == "audio":
            title = _item_text(item, "display_title")
            artist = _item_text(item, "display_artist")
            if title:
                metadata["display_title"] = title
            if artist:
                metadata["display_artist"] = artist
        if asset is None:
            asset = MediaAsset(
                kind=kind,
                locator=path,
                source_duration_tick=duration,
                original_name=Path(path).name,
                metadata=metadata,
            )
            result.media.append(asset)
            by_key[key] = asset
        else:
            if duration > 0:
                asset.source_duration_tick = duration
            if not asset.original_name:
                asset.original_name = Path(path).name
            for meta_key, value in metadata.items():
                asset.metadata.setdefault(meta_key, value)
        return asset

    videos = list(getattr(legacy_project, "videos", []) or [])
    audios = list(getattr(legacy_project, "audios", []) or [])
    images = list(getattr(legacy_project, "images", []) or [])
    for item in videos:
        add_or_update("video", item)
    audio_assets = [add_or_update("audio", item) for item in audios]
    for item in images:
        add_or_update("image", item)

    def linked_asset(path: str) -> str | None:
        path = str(path or "").strip()
        if not path:
            return None
        kind = infer_asset_kind(path, "image")
        key = (kind, _path_key(path))
        asset = by_key.get(key)
        if asset is None:
            asset = MediaAsset(kind=kind, locator=path, original_name=Path(path).name)
            result.media.append(asset)
            by_key[key] = asset
        return asset.asset_id

    if not result.playlist.entries and audio_assets:
        active_paths = getattr(legacy_project, "_active_audio_paths", [])
        if not isinstance(active_paths, list):
            active_paths = []
        audio_item_by_path = {_path_key(str(item.path)): item for item in audios}
        asset_by_path = {_path_key(asset.locator): asset for asset in audio_assets}
        selected_paths = [str(path) for path in active_paths if isinstance(path, str) and path.strip()]
        if not selected_paths:
            selected_paths = [str(item.path) for item in audios]
        for path in selected_paths:
            key = _path_key(path)
            asset = asset_by_path.get(key)
            item = audio_item_by_path.get(key)
            if asset is None:
                continue
            title = _item_text(item, "display_title") if item is not None else ""
            artist = _item_text(item, "display_artist") if item is not None else ""
            cover = linked_asset(_item_text(item, "cover_path")) if item is not None else None
            visual = linked_asset(_item_text(item, "visual_path")) if item is not None else None
            result.playlist.entries.append(
                SongInstance(
                    asset_id=asset.asset_id,
                    display_title=title,
                    display_artist=artist,
                    cover_asset_id=cover,
                    visual_asset_id=visual,
                    source_in_tick=0,
                    source_out_tick=asset.source_duration_tick or None,
                )
            )

    result.validate()
    return result, result.content_signature() != before
