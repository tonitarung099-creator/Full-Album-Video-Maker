from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .editor_models import Layer, TimeBinding, Transform


@dataclass(frozen=True)
class SpectrumCapability:
    style_id: str
    label: str
    ffmpeg_filter: str
    supports_frequency_scale: bool
    supports_amplitude_scale: bool
    supports_split_channels: bool = False
    supports_smoothing: bool = False
    supports_inner_ratio: bool = False


SPECTRUM_CAPABILITIES: dict[str, SpectrumCapability] = {
    "bars": SpectrumCapability(
        "bars", "Bars", "showfreqs", True, True, False, False, False
    ),
    "spectrum_line": SpectrumCapability(
        "spectrum_line", "Spectrum Line", "showfreqs", True, True, False, False, False
    ),
    "waveform": SpectrumCapability(
        "waveform", "Waveform", "showwaves", False, True, False, False, False
    ),
    "stereo_waveform": SpectrumCapability(
        "stereo_waveform", "Stereo Waveform", "showwaves", False, True, True, False, False
    ),
    "circular_spectrum": SpectrumCapability(
        "circular_spectrum",
        "Circular Spectrum",
        "showfreqs+geq",
        True,
        True,
        False,
        False,
        True,
    ),
}


SPECTRUM_PRESETS: dict[str, dict[str, Any]] = {
    "minimal_bars": {
        "label": "Minimal Bars",
        "style": "bars",
        "color": "#f4f7fb",
        "gain": 1.0,
        "frequency_scale": "log",
        "amplitude_scale": "sqrt",
        "mirror": False,
    },
    "neon_bars": {
        "label": "Neon Bars",
        "style": "bars",
        "color": "#4de8ff",
        "gain": 1.35,
        "frequency_scale": "log",
        "amplitude_scale": "log",
        "mirror": True,
    },
    "bass_bars": {
        "label": "Bass Bars",
        "style": "bars",
        "color": "#ff5c9a",
        "gain": 1.8,
        "frequency_scale": "log",
        "amplitude_scale": "cbrt",
        "mirror": False,
    },
    "thin_line": {
        "label": "Thin Line",
        "style": "spectrum_line",
        "color": "#ffffff",
        "gain": 1.1,
        "frequency_scale": "log",
        "amplitude_scale": "sqrt",
        "mirror": False,
    },
    "mirror": {
        "label": "Mirror",
        "style": "waveform",
        "color": "#67f0c2",
        "gain": 1.0,
        "frequency_scale": "linear",
        "amplitude_scale": "linear",
        "mirror": True,
    },
    "circular_neon": {
        "label": "Circular Neon",
        "style": "circular_spectrum",
        "color": "#4de8ff",
        "gain": 1.35,
        "frequency_scale": "log",
        "amplitude_scale": "sqrt",
        "mirror": False,
        "inner_ratio": 0.58,
    },
}


def supported_spectrum_styles() -> tuple[str, ...]:
    return tuple(SPECTRUM_CAPABILITIES)


def spectrum_capability(style: str) -> SpectrumCapability:
    try:
        return SPECTRUM_CAPABILITIES[str(style)]
    except KeyError as exc:
        raise ValueError(f"Style spectrum belum didukung: {style}") from exc


def normalize_spectrum_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(properties or {})
    style = str(source.get("style", "bars"))
    capability = spectrum_capability(style)

    color = str(source.get("color", "#4de8ff")).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Warna spectrum harus #RRGGBB.")

    try:
        gain = float(source.get("gain", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Sensitivity/gain spectrum tidak valid.") from exc
    if not 0.05 <= gain <= 8.0:
        raise ValueError("Sensitivity/gain spectrum harus 0.05..8.0.")

    frequency_scale = str(source.get("frequency_scale", "log" if capability.supports_frequency_scale else "linear"))
    if capability.supports_frequency_scale:
        if frequency_scale not in {"linear", "log", "rlog"}:
            raise ValueError("frequency_scale spectrum tidak didukung.")
    else:
        frequency_scale = "linear"

    amplitude_scale = str(source.get("amplitude_scale", "sqrt"))
    if amplitude_scale not in {"linear", "sqrt", "cbrt", "log"}:
        raise ValueError("amplitude_scale spectrum tidak didukung.")

    try:
        inner_ratio = float(source.get("inner_ratio", 0.58))
    except (TypeError, ValueError) as exc:
        raise ValueError("Radius dalam Circular Spectrum tidak valid.") from exc
    if capability.supports_inner_ratio:
        if not 0.15 <= inner_ratio <= 0.85:
            raise ValueError("Radius dalam Circular Spectrum harus 0.15..0.85.")
    else:
        inner_ratio = 0.58

    mirror = bool(source.get("mirror", False))
    return {
        "style": style,
        "color": color,
        "gain": gain,
        "frequency_scale": frequency_scale,
        "amplitude_scale": amplitude_scale,
        "mirror": mirror,
        "inner_ratio": inner_ratio,
        "preset": str(source.get("preset", "") or ""),
    }


def apply_spectrum_preset(properties: dict[str, Any] | None, preset_id: str) -> dict[str, Any]:
    if preset_id not in SPECTRUM_PRESETS:
        raise ValueError(f"Preset spectrum tidak ditemukan: {preset_id}")
    merged = dict(properties or {})
    preset = SPECTRUM_PRESETS[preset_id]
    merged.update({key: value for key, value in preset.items() if key != "label"})
    merged["preset"] = preset_id
    return normalize_spectrum_properties(merged)


def make_spectrum_layer(track_id: str, order: int, *, preset_id: str = "neon_bars") -> Layer:
    properties = apply_spectrum_preset({}, preset_id)
    circular = properties["style"] == "circular_spectrum"
    return Layer(
        track_id=track_id,
        type="spectrum",
        name="Circular Spectrum" if circular else "Spectrum",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=(
            Transform(x=0.34, y=0.22, width=0.32, height=0.56)
            if circular
            else Transform(x=0.08, y=0.72, width=0.84, height=0.20)
        ),
        properties=properties,
        origin="manual",
    )


def make_dynamic_title_layer(track_id: str, order: int) -> Layer:
    return Layer(
        track_id=track_id,
        type="song_title",
        name="Judul Lagu Dinamis",
        order=order,
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.06, y=0.78, width=0.70, height=0.16),
        properties={
            "template": "{title}\n{artist}",
            "font_size": 58,
            "color": "#ffffff",
        },
        origin="manual",
    )


def dynamic_song_text(template: str, title: str, artist: str) -> str:
    value = str(template or "{title}\n{artist}")
    return value.replace("{title}", str(title or "")).replace("{artist}", str(artist or ""))
