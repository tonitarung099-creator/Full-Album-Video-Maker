from __future__ import annotations

from typing import Any

from .editor_models import Layer, TIMEBASE, TimeBinding, Transform


ALBUM_VISUAL_TYPES = {
    "song_cover",
    "vinyl",
    "playlist_visual",
    "progress",
    "song_time",
}


def format_duration_tick(tick: int) -> str:
    seconds = max(0, int(tick)) // TIMEBASE
    hours, remain = divmod(seconds, 3600)
    minutes, seconds = divmod(remain, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def normalize_visual_properties(layer_type: str, properties: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(properties or {})
    if layer_type == "song_cover":
        fit = str(source.get("fit", "fill"))
        if fit not in {"fill", "fit"}:
            raise ValueError("Fit cover harus fill/fit.")
        return {
            "fit": fit,
            "fallback_asset_id": str(source.get("fallback_asset_id", "") or ""),
        }
    if layer_type == "vinyl":
        spin_seconds = float(source.get("spin_seconds", 8.0))
        if not 1.0 <= spin_seconds <= 60.0:
            raise ValueError("Kecepatan vinyl harus 1..60 detik per putaran.")
        center_ratio = float(source.get("center_ratio", 0.18))
        if not 0.05 <= center_ratio <= 0.45:
            raise ValueError("Ukuran label tengah vinyl harus 0.05..0.45.")
        return {
            "color": str(source.get("color", "#151515")),
            "groove_color": str(source.get("groove_color", "#2d2d2d")),
            "center_color": str(source.get("center_color", "#d9d9d9")),
            "spin_seconds": spin_seconds,
            "center_ratio": center_ratio,
        }
    if layer_type == "playlist_visual":
        max_items = int(source.get("max_items", 8))
        font_size = int(source.get("font_size", 30))
        if not 1 <= max_items <= 30:
            raise ValueError("Jumlah playlist visual harus 1..30.")
        if not 8 <= font_size <= 160:
            raise ValueError("Ukuran font playlist visual harus 8..160.")
        return {
            "max_items": max_items,
            "font_size": font_size,
            "color": str(source.get("color", "#a9b3bf")),
            "active_color": str(source.get("active_color", "#ffffff")),
            "numbered": bool(source.get("numbered", True)),
            "show_artist": bool(source.get("show_artist", False)),
            "background_opacity": max(0.0, min(0.9, float(source.get("background_opacity", 0.28)))),
        }
    if layer_type == "progress":
        mode = str(source.get("mode", "song"))
        if mode not in {"song", "album"}:
            raise ValueError("Mode progress harus song/album.")
        return {
            "mode": mode,
            "background_color": str(source.get("background_color", "#49515c")),
            "fill_color": str(source.get("fill_color", "#ffffff")),
        }
    if layer_type == "song_time":
        mode = str(source.get("mode", "song"))
        if mode not in {"song", "album"}:
            raise ValueError("Mode waktu harus song/album.")
        font_size = int(source.get("font_size", 26))
        if not 8 <= font_size <= 160:
            raise ValueError("Ukuran font waktu harus 8..160.")
        return {
            "mode": mode,
            "font_size": font_size,
            "color": str(source.get("color", "#dfe6ee")),
        }
    raise ValueError(f"Tipe visual album belum didukung: {layer_type}")


def make_song_cover_layer(track_id: str, order: int, *, fallback_asset_id: str = "") -> Layer:
    return Layer(
        track_id=track_id,
        type="song_cover",
        name="Cover Lagu Dinamis",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.06, y=0.17, width=0.28, height=0.50),
        properties=normalize_visual_properties(
            "song_cover",
            {"fit": "fill", "fallback_asset_id": fallback_asset_id},
        ),
        origin="manual",
    )


def make_vinyl_layer(track_id: str, order: int) -> Layer:
    return Layer(
        track_id=track_id,
        type="vinyl",
        name="Vinyl / Disc",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.31, y=0.20, width=0.25, height=0.44),
        properties=normalize_visual_properties("vinyl", {}),
        origin="manual",
    )


def make_playlist_visual_layer(track_id: str, order: int) -> Layer:
    return Layer(
        track_id=track_id,
        type="playlist_visual",
        name="Playlist Visual",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.63, y=0.12, width=0.31, height=0.64),
        properties=normalize_visual_properties("playlist_visual", {}),
        origin="manual",
    )


def make_progress_layer(track_id: str, order: int) -> Layer:
    return Layer(
        track_id=track_id,
        type="progress",
        name="Progress Lagu",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.06, y=0.89, width=0.88, height=0.02),
        properties=normalize_visual_properties("progress", {}),
        origin="manual",
    )


def make_song_time_layer(track_id: str, order: int) -> Layer:
    return Layer(
        track_id=track_id,
        type="song_time",
        name="Durasi Lagu",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.06, y=0.84, width=0.36, height=0.05),
        properties=normalize_visual_properties("song_time", {}),
        origin="manual",
    )
