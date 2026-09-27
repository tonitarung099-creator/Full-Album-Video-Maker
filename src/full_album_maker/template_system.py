from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable

from .album_visuals import (
    make_playlist_visual_layer,
    make_progress_layer,
    make_song_cover_layer,
    make_song_time_layer,
    make_vinyl_layer,
)
from .editor_commands import CommandError, EditorCommand
from .editor_models import Layer, ProjectDocument, Transform
from .spectrum_feature import make_dynamic_title_layer, make_spectrum_layer


@dataclass(frozen=True)
class TemplateDefinition:
    template_id: str
    label: str
    description: str
    spectrum_preset: str


TEMPLATES: dict[str, TemplateDefinition] = {
    "spotify_clean": TemplateDefinition(
        "spotify_clean",
        "Spotify Clean",
        "Layout bersih: cover + judul dominan, spectrum tipis, playlist rapi.",
        "thin_line",
    ),
    "vinyl_nostalgia": TemplateDefinition(
        "vinyl_nostalgia",
        "Vinyl Nostalgia",
        "Vinyl besar, warna hangat, waveform lembut, playlist klasik.",
        "mirror",
    ),
    "minimal_spectrum": TemplateDefinition(
        "minimal_spectrum",
        "Minimal Spectrum",
        "Spectrum menjadi fokus utama dengan cover/vinyl kecil dan ruang lega.",
        "minimal_bars",
    ),
    "viral_full_album": TemplateDefinition(
        "viral_full_album",
        "Viral Full Album",
        "Komposisi padat untuk video album: cover, vinyl, neon spectrum dan playlist.",
        "neon_bars",
    ),
}


def template_choices() -> tuple[TemplateDefinition, ...]:
    return tuple(TEMPLATES.values())


def template_definition(template_id: str) -> TemplateDefinition:
    try:
        return TEMPLATES[str(template_id)]
    except KeyError as exc:
        raise ValueError(f"Template tidak ditemukan: {template_id}") from exc


def _visual_track_id(document: ProjectDocument) -> str:
    track = next((item for item in document.tracks if item.kind == "visual" and item.enabled), None)
    if track is None:
        track = next((item for item in document.tracks if item.kind == "visual"), None)
    if track is None:
        raise ValueError("Template membutuhkan track visual.")
    return track.track_id


def _fallback_image(document: ProjectDocument) -> str:
    return next((asset.asset_id for asset in document.media if asset.kind == "image"), "")


def _mark_template(layer: Layer, template_id: str) -> Layer:
    layer.origin = "template"
    layer.properties = dict(layer.properties)
    layer.properties["template_id"] = template_id
    return layer


def _make_base_layers(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    track_id = _visual_track_id(document)
    definition = template_definition(template_id)
    layers = {
        "song_cover": make_song_cover_layer(track_id, 0, fallback_asset_id=_fallback_image(document)),
        "vinyl": make_vinyl_layer(track_id, 1),
        "playlist_visual": make_playlist_visual_layer(track_id, 2),
        "spectrum": make_spectrum_layer(track_id, 3, preset_id=definition.spectrum_preset),
        "song_title": make_dynamic_title_layer(track_id, 4),
        "progress": make_progress_layer(track_id, 5),
        "song_time": make_song_time_layer(track_id, 6),
    }
    for layer in layers.values():
        _mark_template(layer, template_id)
    return layers


def _apply_spotify_clean(layers: dict[str, Layer]) -> None:
    layers["song_cover"].transform = Transform(x=0.05, y=0.17, width=0.27, height=0.48)
    layers["vinyl"].transform = Transform(x=0.27, y=0.21, width=0.24, height=0.42)
    layers["playlist_visual"].transform = Transform(x=0.62, y=0.13, width=0.33, height=0.62)
    layers["spectrum"].transform = Transform(x=0.05, y=0.79, width=0.52, height=0.08)
    layers["song_title"].transform = Transform(x=0.05, y=0.68, width=0.52, height=0.12)
    layers["progress"].transform = Transform(x=0.05, y=0.92, width=0.90, height=0.02)
    layers["song_time"].transform = Transform(x=0.05, y=0.86, width=0.32, height=0.05)
    layers["song_title"].properties.update(font_size=54, color="#ffffff")
    layers["playlist_visual"].properties.update(
        max_items=9,
        font_size=28,
        color="#9aa4af",
        active_color="#ffffff",
        show_artist=True,
        background_opacity=0.18,
    )
    layers["progress"].properties.update(background_color="#343a40", fill_color="#ffffff")
    layers["song_time"].properties.update(font_size=24, color="#d8dee6")


def _apply_vinyl_nostalgia(layers: dict[str, Layer]) -> None:
    layers["song_cover"].transform = Transform(x=0.07, y=0.23, width=0.23, height=0.41)
    layers["vinyl"].transform = Transform(x=0.23, y=0.15, width=0.38, height=0.68)
    layers["playlist_visual"].transform = Transform(x=0.68, y=0.16, width=0.27, height=0.60)
    layers["spectrum"].transform = Transform(x=0.07, y=0.78, width=0.54, height=0.09)
    layers["song_title"].transform = Transform(x=0.07, y=0.66, width=0.54, height=0.12)
    layers["progress"].transform = Transform(x=0.07, y=0.92, width=0.88, height=0.02)
    layers["song_time"].transform = Transform(x=0.68, y=0.80, width=0.27, height=0.05)
    layers["vinyl"].properties.update(
        color="#17130f",
        groove_color="#5b4939",
        center_color="#d7b98b",
        spin_seconds=10.0,
        center_ratio=0.20,
    )
    layers["song_title"].properties.update(font_size=50, color="#f7e6ca")
    layers["playlist_visual"].properties.update(
        max_items=8,
        font_size=27,
        color="#bda98c",
        active_color="#f7e6ca",
        show_artist=False,
        background_opacity=0.30,
    )
    layers["progress"].properties.update(background_color="#594b3e", fill_color="#e8c99c")
    layers["song_time"].properties.update(font_size=24, color="#d5bea0")


def _apply_minimal_spectrum(layers: dict[str, Layer]) -> None:
    layers["song_cover"].transform = Transform(x=0.05, y=0.08, width=0.18, height=0.32)
    layers["vinyl"].transform = Transform(x=0.19, y=0.12, width=0.15, height=0.27)
    layers["playlist_visual"].transform = Transform(x=0.72, y=0.10, width=0.23, height=0.43)
    layers["spectrum"].transform = Transform(x=0.08, y=0.48, width=0.84, height=0.28)
    layers["song_title"].transform = Transform(x=0.08, y=0.78, width=0.65, height=0.10)
    layers["progress"].transform = Transform(x=0.08, y=0.92, width=0.84, height=0.02)
    layers["song_time"].transform = Transform(x=0.75, y=0.82, width=0.17, height=0.05)
    layers["vinyl"].properties.update(spin_seconds=12.0, center_ratio=0.16)
    layers["song_title"].properties.update(font_size=46, color="#f4f7fb")
    layers["playlist_visual"].properties.update(
        max_items=6,
        font_size=23,
        color="#89939e",
        active_color="#f4f7fb",
        numbered=False,
        show_artist=False,
        background_opacity=0.08,
    )
    layers["progress"].properties.update(background_color="#2c3239", fill_color="#f4f7fb")
    layers["song_time"].properties.update(font_size=22, color="#aab3bd")


def _apply_viral_full_album(layers: dict[str, Layer]) -> None:
    layers["song_cover"].transform = Transform(x=0.04, y=0.14, width=0.30, height=0.53)
    layers["vinyl"].transform = Transform(x=0.29, y=0.19, width=0.27, height=0.47)
    layers["playlist_visual"].transform = Transform(x=0.62, y=0.10, width=0.34, height=0.68)
    layers["spectrum"].transform = Transform(x=0.04, y=0.73, width=0.54, height=0.15)
    layers["song_title"].transform = Transform(x=0.04, y=0.60, width=0.54, height=0.12)
    layers["progress"].transform = Transform(x=0.04, y=0.93, width=0.92, height=0.025)
    layers["song_time"].transform = Transform(x=0.62, y=0.82, width=0.34, height=0.05)
    layers["vinyl"].properties.update(
        color="#0b0f18",
        groove_color="#223248",
        center_color="#4de8ff",
        spin_seconds=7.0,
        center_ratio=0.18,
    )
    layers["song_title"].properties.update(font_size=58, color="#ffffff")
    layers["playlist_visual"].properties.update(
        max_items=10,
        font_size=28,
        color="#8da2b8",
        active_color="#4de8ff",
        show_artist=True,
        background_opacity=0.32,
    )
    layers["progress"].properties.update(background_color="#273343", fill_color="#4de8ff")
    layers["song_time"].properties.update(font_size=24, color="#bfefff")


_TEMPLATE_APPLIERS = {
    "spotify_clean": _apply_spotify_clean,
    "vinyl_nostalgia": _apply_vinyl_nostalgia,
    "minimal_spectrum": _apply_minimal_spectrum,
    "viral_full_album": _apply_viral_full_album,
}


def build_template_layers(document: ProjectDocument, template_id: str) -> list[Layer]:
    template_definition(template_id)
    layers = _make_base_layers(document, template_id)
    _TEMPLATE_APPLIERS[template_id](layers)
    result = list(layers.values())
    for order, layer in enumerate(result):
        layer.order = order
        layer.validate()
    return result


def current_template_id(document: ProjectDocument) -> str:
    value = str(document.editor_defaults.get("template_id", "") or "")
    return value if value in TEMPLATES else ""


@dataclass
class ReplaceTemplateLayers(EditorCommand):
    layers: list[Layer]
    template_id: str = ""

    def apply(self, document: ProjectDocument) -> EditorCommand:
        old_layers = deepcopy([layer for layer in document.layers if layer.origin == "template"])
        old_template_id = current_template_id(document)
        kept = [layer for layer in document.layers if layer.origin != "template"]
        kept_ids = {layer.layer_id for layer in kept}
        replacement = deepcopy(self.layers)
        replacement_ids: set[str] = set()
        valid_tracks = {track.track_id for track in document.tracks}
        for layer in replacement:
            if layer.origin != "template":
                raise CommandError("ReplaceTemplateLayers hanya menerima layer origin=template.")
            if layer.track_id not in valid_tracks:
                raise CommandError("Track template tidak ditemukan.")
            if layer.layer_id in kept_ids or layer.layer_id in replacement_ids:
                raise CommandError("layer_id template duplikat.")
            layer.validate()
            replacement_ids.add(layer.layer_id)
        if self.template_id and self.template_id not in TEMPLATES:
            raise CommandError(f"Template tidak ditemukan: {self.template_id}")
        document.layers = kept + replacement
        if self.template_id:
            document.editor_defaults["template_id"] = self.template_id
        else:
            document.editor_defaults.pop("template_id", None)
        return ReplaceTemplateLayers(old_layers, old_template_id)


def apply_template_command(document: ProjectDocument, template_id: str) -> ReplaceTemplateLayers:
    return ReplaceTemplateLayers(build_template_layers(document, template_id), template_id)
