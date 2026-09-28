from __future__ import annotations

import math
import re
from typing import Any


EFFECT_PRESETS: dict[str, dict[str, Any]] = {
    "vignette": {
        "label": "Vignette",
        "color": "#000000",
        "intensity": 0.58,
        "speed": 0.0,
        "count": 1,
    },
    "bokeh": {
        "label": "Bokeh",
        "color": "#ffd6e7",
        "intensity": 0.26,
        "speed": 0.45,
        "count": 5,
    },
    "light_leak": {
        "label": "Light Leak",
        "color": "#ff8a5c",
        "intensity": 0.28,
        "speed": 0.55,
        "count": 2,
    },
    "particles": {
        "label": "Particles",
        "color": "#ffffff",
        "intensity": 0.30,
        "speed": 0.70,
        "count": 7,
    },
    "film_grain": {
        "label": "Film Grain",
        "color": "#ffffff",
        "intensity": 0.10,
        "speed": 1.0,
        "count": 1,
    },
    "vhs_noise": {
        "label": "VHS Noise",
        "color": "#d7e6ff",
        "intensity": 0.13,
        "speed": 1.0,
        "count": 1,
    },
    "glow": {
        "label": "Glow",
        "color": "#4de8ff",
        "intensity": 0.22,
        "speed": 0.35,
        "count": 2,
    },
}

CIRCULAR_SPECTRUM_STATUS = {
    "available": False,
    "reason": (
        "Circular Spectrum masih ditunda sampai spike FFT/circular terukur lulus "
        "uji packaging, parity preview/render, performa, dan cancel."
    ),
}


def _color(value: Any, default: str) -> str:
    text = str(value or default).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise ValueError("Warna effect harus #RRGGBB.")
    return text.lower()


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def normalize_effect_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(properties or {})
    preset = str(source.get("effect_preset", source.get("preset", "vignette")))
    if preset not in EFFECT_PRESETS:
        raise ValueError(f"Effect overlay belum didukung: {preset}")
    defaults = EFFECT_PRESETS[preset]
    intensity = float(source.get("intensity", defaults["intensity"]))
    speed = float(source.get("speed", defaults["speed"]))
    count = int(source.get("count", defaults["count"]))
    seed = int(source.get("seed", 17))
    if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.0:
        raise ValueError("Intensity effect harus 0..1.")
    if not math.isfinite(speed) or not 0.0 <= speed <= 4.0:
        raise ValueError("Speed effect harus 0..4.")
    if not 1 <= count <= 12:
        raise ValueError("Jumlah elemen effect harus 1..12 agar beban render tetap bounded.")
    if not 0 <= seed <= 999_999:
        raise ValueError("Seed effect harus 0..999999.")
    return {
        "effect_preset": preset,
        "color": _color(source.get("color"), str(defaults["color"])),
        "intensity": intensity,
        "speed": speed,
        "count": count,
        "seed": seed,
    }


def make_effect_properties(
    preset: str,
    *,
    color: str | None = None,
    intensity: float | None = None,
    speed: float | None = None,
    count: int | None = None,
    seed: int = 17,
) -> dict[str, Any]:
    values: dict[str, Any] = {"effect_preset": preset, "seed": seed}
    if color is not None:
        values["color"] = color
    if intensity is not None:
        values["intensity"] = intensity
    if speed is not None:
        values["speed"] = speed
    if count is not None:
        values["count"] = count
    return normalize_effect_properties(values)


def _nested_max(expressions: list[str]) -> str:
    if not expressions:
        return "0"
    result = expressions[0]
    for expression in expressions[1:]:
        result = f"max({result},{expression})"
    return result


def _spot_expression(
    index: int,
    *,
    seed: int,
    radius_ratio: float,
    speed: float,
    fps: float,
    moving: bool,
) -> str:
    # Stable pseudo-random coordinates are derived from the persisted seed. The
    # animation uses frame N rather than random(), making accurate preview and
    # final render deterministic for the same project snapshot.
    sx = (seed * 37 + index * 97 + 31) % 997
    sy = (seed * 53 + index * 71 + 17) % 991
    base_x = 0.08 + (sx / 997.0) * 0.84
    base_y = 0.08 + (sy / 991.0) * 0.84
    if moving and speed > 0:
        phase = ((seed + index * 19) % 360) * math.pi / 180.0
        x = f"W*({base_x:.6f}+0.045*sin(N*{speed:.6f}/{max(1.0, fps):.6f}+{phase:.6f}))"
        y = f"H*({base_y:.6f}+0.035*cos(N*{speed:.6f}/{max(1.0, fps):.6f}+{phase:.6f}))"
    else:
        x = f"W*{base_x:.6f}"
        y = f"H*{base_y:.6f}"
    radius = f"min(W,H)*{radius_ratio:.6f}"
    return f"max(0,1-hypot(X-({x}),Y-({y}))/({radius}))"


def effect_source_filter(
    properties: dict[str, Any],
    *,
    width: int,
    height: int,
    fps: float,
    duration: float,
    layer_opacity: float,
) -> str:
    """Return a bounded transparent RGBA source for one decorative layer.

    It intentionally uses a fixed upper element count and deterministic GEQ
    expressions. No per-frame Python loop or unbounded particle allocation is
    introduced into long album renders.
    """

    props = normalize_effect_properties(properties)
    preset = props["effect_preset"]
    red, green, blue = _rgb(props["color"])
    alpha = max(0.0, min(1.0, float(layer_opacity))) * props["intensity"]
    if alpha <= 0:
        alpha_expr = "0"
    elif preset == "vignette":
        # Transparent center, darkened corners. Radius is normalized by the
        # canvas diagonal to remain stable across aspect ratios.
        alpha_expr = (
            f"255*{alpha:.8f}*min(1,max(0,"
            "(hypot(X-W/2,Y-H/2)/(hypot(W/2,H/2)*0.72)-0.25)/0.75))"
        )
    elif preset in {"glow", "light_leak"}:
        count = min(3, props["count"])
        expressions = [
            _spot_expression(
                index,
                seed=props["seed"],
                radius_ratio=0.42 if preset == "light_leak" else 0.34,
                speed=props["speed"],
                fps=fps,
                moving=True,
            )
            for index in range(count)
        ]
        alpha_expr = f"255*{alpha:.8f}*({_nested_max(expressions)})"
    elif preset == "bokeh":
        expressions = [
            _spot_expression(
                index,
                seed=props["seed"],
                radius_ratio=0.07 + (index % 3) * 0.018,
                speed=props["speed"] * (0.75 + 0.08 * index),
                fps=fps,
                moving=True,
            )
            for index in range(props["count"])
        ]
        # Squaring the radial falloff keeps the bokeh centers visible while
        # preserving soft transparent edges.
        alpha_expr = f"255*{alpha:.8f}*pow({_nested_max(expressions)},2)"
    elif preset == "particles":
        expressions = [
            _spot_expression(
                index,
                seed=props["seed"],
                radius_ratio=0.012 + (index % 3) * 0.004,
                speed=props["speed"] * (1.0 + index * 0.04),
                fps=fps,
                moving=True,
            )
            for index in range(props["count"])
        ]
        alpha_expr = f"255*{alpha:.8f}*({_nested_max(expressions)})"
    elif preset == "film_grain":
        threshold = max(1, round(1 + alpha * 6))
        alpha_expr = (
            f"255*{alpha:.8f}*if(lt(mod(X*13+Y*17+N*19+{props['seed']},31),{threshold}),1,0)"
        )
    elif preset == "vhs_noise":
        drift = props["speed"] * 2.0
        alpha_expr = (
            f"255*{alpha:.8f}*if(lt(mod(Y+floor(N*{drift:.6f})+{props['seed']},11),1),1,0)"
        )
    else:  # defensive; normalize_effect_properties already rejects unknown ids.
        raise ValueError(f"Effect overlay belum didukung: {preset}")

    return (
        f"nullsrc=s={int(width)}x{int(height)}:r={fps:g}:d={duration:.6f},"
        "format=rgba,"
        f"geq=r='{red}':g='{green}':b='{blue}':a='{alpha_expr}'"
    )
