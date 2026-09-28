from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from .album_visuals import (
    make_playlist_visual_layer,
    make_progress_layer,
    make_song_cover_layer,
    make_song_time_layer,
    make_vinyl_layer,
)
from .editor_commands import CommandError, EditorCommand
from .editor_models import Layer, ProjectDocument, TimeBinding, Transform
from .overlay_effects import make_effect_properties
from .spectrum_feature import make_dynamic_title_layer, make_spectrum_layer


@dataclass(frozen=True)
class TemplateDefinition:
    template_id: str
    label: str
    description: str
    spectrum_preset: str
    category: str = "Bawaan"
    required_capabilities: tuple[str, ...] = ("spectrum", "overlay")


# Public S10 catalog. The order is deliberate and stable because the combo/card
# library stores the selected template by ID and presents this order to users.
TEMPLATES: dict[str, TemplateDefinition] = {
    "spotify_clean": TemplateDefinition(
        "spotify_clean",
        "Spotify Clean",
        "Clean player tanpa logo/aset Spotify: cover, judul, playlist, progress tipis dan spectrum minimal.",
        "thin_line",
    ),
    "cafe_acoustic": TemplateDefinition(
        "cafe_acoustic",
        "Cafe Acoustic",
        "Nuansa hangat dengan slow zoom, waveform lembut dan light leak tipis.",
        "thin_line",
    ),
    "viral_full_album": TemplateDefinition(
        "viral_full_album",
        "Viral Full Album",
        "Komposisi padat: cover, playlist, neon bars, progress dan bokeh halus.",
        "neon_bars",
    ),
    "vinyl_nostalgia": TemplateDefinition(
        "vinyl_nostalgia",
        "Vinyl Nostalgia",
        "Vinyl besar, teks hangat, waveform mirror, grain dan light leak retro.",
        "mirror",
    ),
    "neon_spectrum": TemplateDefinition(
        "neon_spectrum",
        "Neon Spectrum",
        "Spectrum neon dominan dengan glow dan partikel deterministik.",
        "bass_bars",
    ),
    "romantic_bokeh": TemplateDefinition(
        "romantic_bokeh",
        "Romantic Bokeh",
        "Bokeh lembut, cover besar, judul elegan dan waveform tipis.",
        "thin_line",
    ),
    "dark_cinematic": TemplateDefinition(
        "dark_cinematic",
        "Dark Cinematic",
        "Visual gelap dengan vignette, grain, judul kontras dan spectrum line.",
        "thin_line",
    ),
    "photo_album": TemplateDefinition(
        "photo_album",
        "Photo Album",
        "Foto dominan dengan Ken Burns sederhana, judul, playlist dan spectrum minimal.",
        "minimal_bars",
    ),
    "cassette_retro": TemplateDefinition(
        "cassette_retro",
        "Cassette Retro",
        "Gaya kaset retro berbasis warna analog, VHS scanline, grain dan bass bars.",
        "bass_bars",
    ),
    "music_channel_pro": TemplateDefinition(
        "music_channel_pro",
        "Music Channel Pro",
        "Layout kanal musik profesional: cover, artist/track, playlist, spectrum dan progress.",
        "neon_bars",
    ),
}

# S07 exposed this ID publicly. Keep it load/apply-compatible so saved projects
# from S07/S08 do not break, but do not count it as an eleventh S10 template.
LEGACY_TEMPLATES: dict[str, TemplateDefinition] = {
    "minimal_spectrum": TemplateDefinition(
        "minimal_spectrum",
        "Minimal Spectrum (Legacy)",
        "Layout spectrum minimal dari S07; dipertahankan untuk kompatibilitas proyek lama.",
        "minimal_bars",
        category="Legacy",
    )
}

ALL_TEMPLATE_DEFINITIONS = {**TEMPLATES, **LEGACY_TEMPLATES}


def template_choices() -> tuple[TemplateDefinition, ...]:
    return tuple(TEMPLATES.values())


def template_definition(template_id: str) -> TemplateDefinition:
    try:
        return ALL_TEMPLATE_DEFINITIONS[str(template_id)]
    except KeyError as exc:
        raise ValueError(f"Template tidak ditemukan: {template_id}") from exc


def _visual_track_id(document: ProjectDocument) -> str:
    track = next(
        (item for item in document.tracks if item.kind == "visual" and item.enabled),
        None,
    )
    if track is None:
        track = next((item for item in document.tracks if item.kind == "visual"), None)
    if track is None:
        raise ValueError("Template membutuhkan track visual.")
    return track.track_id


def _fallback_image(document: ProjectDocument) -> str:
    return next((asset.asset_id for asset in document.media if asset.kind == "image"), "")


def _background_visual(document: ProjectDocument) -> str:
    return next(
        (
            asset.asset_id
            for asset in document.media
            if asset.kind in {"image", "video"}
        ),
        "",
    )


def _mark_template(layer: Layer, template_id: str) -> Layer:
    layer.origin = "template"
    layer.properties = dict(layer.properties)
    layer.properties["template_id"] = template_id
    return layer


def _make_background_layer(
    document: ProjectDocument,
    template_id: str,
    *,
    color: str,
    use_media: bool = False,
    motion: str = "static",
) -> Layer:
    track_id = _visual_track_id(document)
    asset_id = _background_visual(document) if use_media else ""
    if asset_id:
        props = {
            "mode": "asset",
            "fit": "fill",
            "playback": "loop",
            "motion": motion,
            "color": color,
        }
        refs = [asset_id]
    else:
        props = {
            "mode": "solid",
            "color": color,
            "playback": "loop",
            "motion": "static",
        }
        refs = []
    return _mark_template(
        Layer(
            track_id=track_id,
            type="background",
            name="Background Template",
            order=0,
            time_binding=TimeBinding(kind="album"),
            transform=Transform(x=0.0, y=0.0, width=1.0, height=1.0),
            properties=props,
            asset_refs=refs,
            origin="template",
        ),
        template_id,
    )


def _make_effect_layer(
    track_id: str,
    template_id: str,
    preset: str,
    *,
    name: str | None = None,
    color: str | None = None,
    intensity: float | None = None,
    speed: float | None = None,
    count: int | None = None,
    seed: int = 17,
) -> Layer:
    props = make_effect_properties(
        preset,
        color=color,
        intensity=intensity,
        speed=speed,
        count=count,
        seed=seed,
    )
    props["mode"] = "effect"
    return _mark_template(
        Layer(
            track_id=track_id,
            type="background",
            name=name or f"Effect • {preset}",
            order=90,
            time_binding=TimeBinding(kind="album"),
            transform=Transform(x=0.0, y=0.0, width=1.0, height=1.0),
            properties=props,
            origin="template",
        ),
        template_id,
    )


def _make_base_layers(
    document: ProjectDocument,
    template_id: str,
    *,
    background_color: str = "#101114",
    media_background: bool = False,
    background_motion: str = "static",
) -> dict[str, Layer]:
    track_id = _visual_track_id(document)
    definition = template_definition(template_id)
    layers = {
        "background": _make_background_layer(
            document,
            template_id,
            color=background_color,
            use_media=media_background,
            motion=background_motion,
        ),
        "song_cover": make_song_cover_layer(
            track_id,
            10,
            fallback_asset_id=_fallback_image(document),
        ),
        "vinyl": make_vinyl_layer(track_id, 20),
        "playlist_visual": make_playlist_visual_layer(track_id, 30),
        "spectrum": make_spectrum_layer(
            track_id,
            40,
            preset_id=definition.spectrum_preset,
        ),
        "song_title": make_dynamic_title_layer(track_id, 50),
        "progress": make_progress_layer(track_id, 60),
        "song_time": make_song_time_layer(track_id, 70),
    }
    for key, layer in layers.items():
        if key != "background":
            _mark_template(layer, template_id)
    return layers


def _add_effect(
    layers: dict[str, Layer],
    template_id: str,
    key: str,
    preset: str,
    **kwargs,
) -> None:
    track_id = layers["background"].track_id
    layers[key] = _make_effect_layer(
        track_id,
        template_id,
        preset,
        **kwargs,
    )


def _spotify_clean(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#111418")
    layers["song_cover"].transform = Transform(x=0.05, y=0.17, width=0.27, height=0.48)
    layers["vinyl"].enabled = False
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
    return layers


def _cafe_acoustic(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(
        document,
        template_id,
        background_color="#2a1d16",
        media_background=True,
        background_motion="zoom_in",
    )
    layers["vinyl"].enabled = False
    layers["song_cover"].transform = Transform(x=0.06, y=0.18, width=0.29, height=0.51)
    layers["playlist_visual"].transform = Transform(x=0.66, y=0.18, width=0.29, height=0.54)
    layers["spectrum"].transform = Transform(x=0.06, y=0.77, width=0.54, height=0.09)
    layers["song_title"].transform = Transform(x=0.06, y=0.65, width=0.54, height=0.11)
    layers["song_title"].properties.update(font_size=48, color="#fff2d8")
    layers["playlist_visual"].properties.update(
        max_items=7,
        font_size=25,
        color="#dfc9aa",
        active_color="#fff2d8",
        show_artist=True,
        background_opacity=0.24,
    )
    layers["progress"].properties.update(background_color="#4b3528", fill_color="#e7bc7a")
    layers["song_time"].properties.update(color="#f4d9b3")
    _add_effect(
        layers,
        template_id,
        "fx_light",
        "light_leak",
        color="#ffb16e",
        intensity=0.20,
        speed=0.35,
        count=2,
        seed=103,
    )
    return layers


def _viral_full_album(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(
        document,
        template_id,
        background_color="#08111c",
        media_background=True,
        background_motion="zoom_out",
    )
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
    _add_effect(
        layers,
        template_id,
        "fx_bokeh",
        "bokeh",
        color="#69e7ff",
        intensity=0.12,
        speed=0.45,
        count=4,
        seed=211,
    )
    return layers


def _vinyl_nostalgia(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#211811")
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
    _add_effect(layers, template_id, "fx_grain", "film_grain", intensity=0.08, seed=307)
    _add_effect(
        layers,
        template_id,
        "fx_light",
        "light_leak",
        color="#e8b37a",
        intensity=0.12,
        speed=0.25,
        seed=311,
    )
    return layers


def _neon_spectrum(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#040710")
    layers["song_cover"].transform = Transform(x=0.07, y=0.12, width=0.24, height=0.43)
    layers["vinyl"].enabled = False
    layers["playlist_visual"].transform = Transform(x=0.70, y=0.12, width=0.25, height=0.56)
    layers["spectrum"].transform = Transform(x=0.08, y=0.48, width=0.84, height=0.28)
    layers["song_title"].transform = Transform(x=0.08, y=0.79, width=0.62, height=0.10)
    layers["song_title"].properties.update(font_size=50, color="#eafbff")
    layers["playlist_visual"].properties.update(
        max_items=7,
        font_size=24,
        color="#7793ae",
        active_color="#4de8ff",
        background_opacity=0.12,
    )
    layers["progress"].properties.update(background_color="#152234", fill_color="#4de8ff")
    _add_effect(
        layers,
        template_id,
        "fx_glow",
        "glow",
        color="#4de8ff",
        intensity=0.16,
        speed=0.28,
        count=2,
        seed=401,
    )
    _add_effect(
        layers,
        template_id,
        "fx_particles",
        "particles",
        color="#bff8ff",
        intensity=0.24,
        speed=0.55,
        count=7,
        seed=409,
    )
    return layers


def _romantic_bokeh(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(
        document,
        template_id,
        background_color="#24131d",
        media_background=True,
        background_motion="zoom_in",
    )
    layers["vinyl"].enabled = False
    layers["song_cover"].transform = Transform(x=0.09, y=0.15, width=0.31, height=0.55)
    layers["playlist_visual"].transform = Transform(x=0.67, y=0.17, width=0.27, height=0.52)
    layers["spectrum"].transform = Transform(x=0.09, y=0.75, width=0.51, height=0.08)
    layers["song_title"].transform = Transform(x=0.09, y=0.61, width=0.51, height=0.12)
    layers["song_title"].properties.update(font_size=52, color="#fff1f6")
    layers["playlist_visual"].properties.update(
        max_items=7,
        font_size=25,
        color="#d6b4c3",
        active_color="#fff1f6",
        background_opacity=0.18,
    )
    layers["progress"].properties.update(background_color="#553746", fill_color="#ffb7d4")
    _add_effect(
        layers,
        template_id,
        "fx_bokeh",
        "bokeh",
        color="#ffd6e7",
        intensity=0.25,
        speed=0.32,
        count=6,
        seed=503,
    )
    _add_effect(
        layers,
        template_id,
        "fx_glow",
        "glow",
        color="#ff93bd",
        intensity=0.10,
        speed=0.20,
        count=2,
        seed=509,
    )
    return layers


def _dark_cinematic(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(
        document,
        template_id,
        background_color="#07090d",
        media_background=True,
        background_motion="pan_left",
    )
    layers["vinyl"].enabled = False
    layers["song_cover"].transform = Transform(x=0.06, y=0.20, width=0.25, height=0.44)
    layers["playlist_visual"].transform = Transform(x=0.70, y=0.17, width=0.25, height=0.56)
    layers["spectrum"].transform = Transform(x=0.06, y=0.75, width=0.58, height=0.10)
    layers["song_title"].transform = Transform(x=0.06, y=0.60, width=0.58, height=0.13)
    layers["song_title"].properties.update(font_size=54, color="#f5f7fa")
    layers["playlist_visual"].properties.update(
        max_items=8,
        font_size=25,
        color="#8c929a",
        active_color="#ffffff",
        background_opacity=0.26,
    )
    layers["progress"].properties.update(background_color="#292d33", fill_color="#d9dde3")
    _add_effect(layers, template_id, "fx_vignette", "vignette", intensity=0.66, seed=601)
    _add_effect(layers, template_id, "fx_grain", "film_grain", intensity=0.07, seed=607)
    return layers


def _photo_album(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(
        document,
        template_id,
        background_color="#14181d",
        media_background=True,
        background_motion="pan_right",
    )
    layers["vinyl"].enabled = False
    layers["song_cover"].transform = Transform(x=0.07, y=0.17, width=0.25, height=0.44)
    layers["playlist_visual"].transform = Transform(x=0.70, y=0.13, width=0.25, height=0.55)
    layers["spectrum"].transform = Transform(x=0.07, y=0.77, width=0.55, height=0.10)
    layers["song_title"].transform = Transform(x=0.07, y=0.63, width=0.55, height=0.12)
    layers["song_title"].properties.update(font_size=50, color="#ffffff")
    layers["playlist_visual"].properties.update(
        max_items=7,
        font_size=24,
        color="#c5ccd4",
        active_color="#ffffff",
        background_opacity=0.16,
    )
    _add_effect(
        layers,
        template_id,
        "fx_bokeh",
        "bokeh",
        color="#ffffff",
        intensity=0.08,
        speed=0.20,
        count=4,
        seed=701,
    )
    return layers


def _cassette_retro(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#1b1914")
    layers["song_cover"].transform = Transform(x=0.08, y=0.19, width=0.25, height=0.44)
    layers["vinyl"].transform = Transform(x=0.29, y=0.24, width=0.22, height=0.38)
    layers["vinyl"].properties.update(
        color="#26231d",
        groove_color="#766a56",
        center_color="#e1c67f",
        spin_seconds=9.0,
        center_ratio=0.16,
    )
    layers["playlist_visual"].transform = Transform(x=0.65, y=0.15, width=0.30, height=0.60)
    layers["spectrum"].transform = Transform(x=0.08, y=0.73, width=0.48, height=0.14)
    layers["song_title"].transform = Transform(x=0.08, y=0.62, width=0.48, height=0.10)
    layers["song_title"].properties.update(font_size=47, color="#f5df9f")
    layers["playlist_visual"].properties.update(
        max_items=8,
        font_size=25,
        color="#c2b28c",
        active_color="#f5df9f",
        numbered=True,
        background_opacity=0.28,
    )
    layers["progress"].properties.update(background_color="#514936", fill_color="#e5c56f")
    _add_effect(layers, template_id, "fx_vhs", "vhs_noise", intensity=0.11, speed=1.0, seed=809)
    _add_effect(layers, template_id, "fx_grain", "film_grain", intensity=0.06, seed=811)
    return layers


def _music_channel_pro(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#081018")
    layers["song_cover"].transform = Transform(x=0.04, y=0.13, width=0.28, height=0.50)
    layers["vinyl"].enabled = False
    layers["playlist_visual"].transform = Transform(x=0.66, y=0.12, width=0.30, height=0.64)
    layers["spectrum"].transform = Transform(x=0.04, y=0.71, width=0.56, height=0.16)
    layers["song_title"].transform = Transform(x=0.04, y=0.58, width=0.56, height=0.12)
    layers["progress"].transform = Transform(x=0.04, y=0.93, width=0.92, height=0.025)
    layers["song_time"].transform = Transform(x=0.66, y=0.81, width=0.30, height=0.05)
    layers["song_title"].properties.update(font_size=58, color="#f7fbff")
    layers["playlist_visual"].properties.update(
        max_items=10,
        font_size=27,
        color="#91a2b5",
        active_color="#4de8ff",
        show_artist=True,
        background_opacity=0.30,
    )
    layers["progress"].properties.update(background_color="#223143", fill_color="#4de8ff")
    _add_effect(
        layers,
        template_id,
        "fx_glow",
        "glow",
        color="#2ea7ff",
        intensity=0.08,
        speed=0.18,
        count=2,
        seed=907,
    )
    return layers


def _minimal_spectrum_legacy(document: ProjectDocument, template_id: str) -> dict[str, Layer]:
    layers = _make_base_layers(document, template_id, background_color="#101114")
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
    return layers


_TEMPLATE_BUILDERS: dict[str, Callable[[ProjectDocument, str], dict[str, Layer]]] = {
    "spotify_clean": _spotify_clean,
    "cafe_acoustic": _cafe_acoustic,
    "viral_full_album": _viral_full_album,
    "vinyl_nostalgia": _vinyl_nostalgia,
    "neon_spectrum": _neon_spectrum,
    "romantic_bokeh": _romantic_bokeh,
    "dark_cinematic": _dark_cinematic,
    "photo_album": _photo_album,
    "cassette_retro": _cassette_retro,
    "music_channel_pro": _music_channel_pro,
    "minimal_spectrum": _minimal_spectrum_legacy,
}


def build_template_layers(document: ProjectDocument, template_id: str) -> list[Layer]:
    template_definition(template_id)
    try:
        layers = _TEMPLATE_BUILDERS[template_id](document, template_id)
    except KeyError as exc:
        raise ValueError(f"Template builder tidak ditemukan: {template_id}") from exc

    order_map = {
        "background": 0,
        "song_cover": 20,
        "vinyl": 30,
        "playlist_visual": 40,
        "spectrum": 50,
        "song_title": 60,
        "progress": 70,
        "song_time": 80,
    }
    for key, layer in layers.items():
        layer.order = order_map.get(key, 90 + list(layers).index(key))
    result = sorted(layers.values(), key=lambda layer: layer.order)
    for layer in result:
        layer.validate()
    return result


def current_template_id(document: ProjectDocument) -> str:
    value = str(document.editor_defaults.get("template_id", "") or "")
    return value if value in ALL_TEMPLATE_DEFINITIONS else ""


@dataclass
class ReplaceTemplateLayers(EditorCommand):
    layers: list[Layer]
    template_id: str = ""

    def apply(self, document: ProjectDocument) -> EditorCommand:
        old_layers = deepcopy(
            [layer for layer in document.layers if layer.origin == "template"]
        )
        old_template_id = current_template_id(document)
        kept = [layer for layer in document.layers if layer.origin != "template"]
        kept_ids = {layer.layer_id for layer in kept}
        replacement = deepcopy(self.layers)
        replacement_ids: set[str] = set()
        valid_tracks = {track.track_id for track in document.tracks}
        for layer in replacement:
            if layer.origin != "template":
                raise CommandError(
                    "ReplaceTemplateLayers hanya menerima layer origin=template."
                )
            if layer.track_id not in valid_tracks:
                raise CommandError("Track template tidak ditemukan.")
            if layer.layer_id in kept_ids or layer.layer_id in replacement_ids:
                raise CommandError("layer_id template duplikat.")
            layer.validate()
            replacement_ids.add(layer.layer_id)
        if self.template_id and self.template_id not in ALL_TEMPLATE_DEFINITIONS:
            raise CommandError(f"Template tidak ditemukan: {self.template_id}")
        document.layers = kept + replacement
        if self.template_id:
            document.editor_defaults["template_id"] = self.template_id
        else:
            document.editor_defaults.pop("template_id", None)
        return ReplaceTemplateLayers(old_layers, old_template_id)


def apply_template_command(
    document: ProjectDocument,
    template_id: str,
) -> ReplaceTemplateLayers:
    return ReplaceTemplateLayers(
        build_template_layers(document, template_id),
        template_id,
    )
