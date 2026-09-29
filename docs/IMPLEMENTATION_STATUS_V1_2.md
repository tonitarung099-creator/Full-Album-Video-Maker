# Implementasi v1.2.0 — Circular Spectrum

Status branch: **PR gate hijau, siap squash-merge exact head**.

## Implementasi

- `circular_spectrum.py`: polar mapper bounded berbasis `showfreqs + geq`, maksimal 512×512 internal, inner radius tervalidasi.
- `spectrum_feature.py`: style `circular_spectrum`, capability `supports_inner_ratio`, preset `circular_neon`.
- `render_graph.py`: Circular Spectrum memakai branch audio spectrum yang sama, gain visual-only, transform/opacity/rotation, dan satu compiler untuk final render + Preview Akurat.
- `property_inspector.py`: kontrol `Radius Dalam` hanya tampil untuk Circular Spectrum.
- `preview_scene.py`: proxy radial ringan untuk interaksi editor.
- regression: registry/preset, bounded polar cost, compiler graph, inspector visibility, real FFmpeg render, transparent center, Preview Akurat parity, cancel safety.
- release identity: v1.2.0 + README, capability report, acceptance, dan release notes.
- schema project tetap v2; project v1.1.0 tidak memerlukan migrasi.

## Gate final PR #36

Exact head sebelum dokumentasi gate: `75ec3abfa97a66f5f100469eeb2936d16d4de0d0`.
Workflow **Build Windows Portable #184**, run `36527034174`, selesai `success`:

- **303 passed, 0 failed** dalam `65.43s`;
- pinned FFmpeg/ffprobe Windows sukses;
- real Circular Spectrum + Preview Akurat parity sukses;
- PyInstaller Windows onedir sukses;
- capability bundle sukses;
- versioned ZIP + `SHA256SUMS.txt` sukses;
- isolated portable smoke sukses tanpa Python/FFmpeg global dan tanpa Gemini/Google API key;
- smoke menghasilkan stream `audio` + `video`, GUI title `Full Album Maker v1.2.0 • Editor V2`;
- upload artifact sukses: artifact ID `11014967212`, wrapper size `183879881` bytes, wrapper SHA-256 `1320b5b99ad18aad3b0584135ea88504e3e72bf4112e0d60c40a2205d8b654ee`;
- step Publish stable GitHub Release **skipped**, sesuai kontrak PR.

## Riwayat spike

Run awal #179–#181 menemukan incompatibility/regression pada pendekatan alpha/warm-up awal. Perubahan tersebut tidak pernah dirilis. Implementasi final menjaga semantics preview lama dan memakai grayscale polar chain yang portable pada pinned Windows FFmpeg.

Baseline: v1.1.0 / `81437e24edfbc77ba0b7308490a877fe5644754b`.
