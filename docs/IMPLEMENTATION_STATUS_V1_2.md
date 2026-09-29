# Implementasi v1.2.0 — Circular Spectrum

Status branch: kandidat release `sol/v1.2.0-circular-spectrum`.

## Implementasi

- `circular_spectrum.py`: polar mapper bounded berbasis `showfreqs + geq`, maksimal 512×512 internal, inner radius tervalidasi.
- `spectrum_feature.py`: style `circular_spectrum`, capability `supports_inner_ratio`, preset `circular_neon`.
- `render_graph.py`: Circular Spectrum memakai branch audio spectrum yang sama, gain visual-only, transform/opacity/rotation, dan satu compiler untuk final render + Preview Akurat.
- `property_inspector.py`: kontrol `Radius Dalam` hanya tampil untuk Circular Spectrum.
- `preview_scene.py`: proxy radial ringan untuk interaksi editor.
- regression: registry/preset, bounded polar cost, compiler graph, inspector visibility, real FFmpeg render, transparent center, Preview Akurat parity, cancel safety.
- release identity: v1.2.0 + README, capability report, acceptance, dan release notes.

## Gate

Branch belum boleh merge sebelum workflow Windows exact head lulus seluruh pytest, real FFmpeg, PyInstaller onedir, versioned ZIP + SHA256SUMS, isolated portable smoke, dan upload artifact. GitHub Release hanya boleh dibuat oleh push `main` yang lulus gate yang sama.
