from __future__ import annotations

from dataclasses import dataclass
import re


MIN_INTERNAL_SIDE = 64
MAX_INTERNAL_SIDE = 512
OUTER_RADIUS_RATIO = 0.48


@dataclass(frozen=True)
class CircularSpectrumGeometry:
    internal_side: int
    target_width: int
    target_height: int
    inner_ratio: float


def circular_internal_side(width: int, height: int) -> int:
    """Bound polar remap cost independently from the final layer size."""

    smallest = max(2, min(int(width), int(height)))
    return max(MIN_INTERNAL_SIDE, min(MAX_INTERNAL_SIDE, smallest))


def circular_geometry(width: int, height: int, inner_ratio: float) -> CircularSpectrumGeometry:
    width = int(width)
    height = int(height)
    if width < 2 or height < 2:
        raise ValueError("Ukuran Circular Spectrum minimal 2x2 pixel.")
    try:
        ratio = float(inner_ratio)
    except (TypeError, ValueError) as exc:
        raise ValueError("Radius dalam Circular Spectrum tidak valid.") from exc
    if not 0.15 <= ratio <= 0.85:
        raise ValueError("Radius dalam Circular Spectrum harus 0.15..0.85.")
    return CircularSpectrumGeometry(
        internal_side=circular_internal_side(width, height),
        target_width=width,
        target_height=height,
        inner_ratio=ratio,
    )


def _color_factors(color: str) -> tuple[float, float, float]:
    value = str(color or "").strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    elif value.startswith("#"):
        value = value[1:]
    if not re.fullmatch(r"[0-9a-f]{6}", value):
        raise ValueError("Warna Circular Spectrum harus #RRGGBB/0xRRGGBB.")
    return tuple(int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def circular_spectrum_filter(
    *,
    width: int,
    height: int,
    color: str,
    frequency_scale: str,
    amplitude_scale: str,
    inner_ratio: float,
) -> str:
    """Return a transparent audio visualizer chain that wraps showfreqs into a ring.

    The expensive atan2/hypot polar remap is intentionally capped at 512x512.
    The resulting square is then scaled with aspect preservation and padded into
    the requested transform box. This keeps a true circle even when the user
    gives the layer a rectangular box.

    The frequency image is intentionally converted to grayscale before polar
    sampling. FFmpeg's luma sampler is stable across the pinned Windows build and
    avoids RGB-plane sampling differences. After remapping, black is keyed to
    transparency and the white energy map is recolored to the user's spectrum
    color with colorchannelmixer.
    """

    geometry = circular_geometry(width, height, inner_ratio)
    side = geometry.internal_side
    inner = OUTER_RADIUS_RATIO * geometry.inner_ratio
    band = OUTER_RADIUS_RATIO - inner
    if band <= 0:
        raise ValueError("Radius Circular Spectrum menghasilkan ketebalan nol.")
    red, green, blue = _color_factors(color)

    radius = "hypot(X-W/2,Y-H/2)"
    angle_x = (
        "clip((atan2(Y-H/2,X-W/2)+PI)/(2*PI)*(W-1),0,W-1)"
    )
    source_y = (
        "clip(H-1-("
        + radius
        + f"-min(W,H)*{inner:.6f})/(min(W,H)*{band:.6f})*(H-1),0,H-1)"
    )
    radial_luma = (
        f"if(between({radius},min(W,H)*{inner:.6f},"
        f"min(W,H)*{OUTER_RADIUS_RATIO:.6f}),"
        f"lum({angle_x},{source_y}),0)"
    )

    return (
        f"showfreqs=s={side}x{side}:mode=bar:"
        f"fscale={frequency_scale}:ascale={amplitude_scale}:colors=white,"
        "format=gray,"
        f"geq=lum='{radial_luma}':interpolation=bilinear,"
        "format=rgba,colorkey=0x000000:0.02:0.0,"
        f"colorchannelmixer=rr={red:.6f}:gg={green:.6f}:bb={blue:.6f},"
        f"scale={geometry.target_width}:{geometry.target_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={geometry.target_width}:{geometry.target_height}:"
        "(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba"
    )
