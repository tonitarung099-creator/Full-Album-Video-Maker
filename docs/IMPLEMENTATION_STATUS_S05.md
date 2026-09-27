# S05 — Spectrum Core + Dynamic Song Title

Status: implementasi branch `sol/s05-spectrum-dynamic-title`; menunggu gate Windows PR sebelum merge.

## Yang diimplementasikan

- `spectrum_feature.py`: capability registry, preset release, normalisasi properties, factory layer spectrum dan dynamic title.
- `render_graph.py`: spectrum/waveform audio-driven via FFmpeg, audio `asplit`, alpha colorkey, visual-only gain, dynamic song title per `song_id`, background loop/freeze dan zoom/pan.
- `preview_scene.py`: proxy spectrum ringan pada canvas editor dan dynamic title berdasarkan lagu aktif; Preview Akurat tetap memakai compiler final.
- `property_inspector.py`: properties spectrum, preset, sensitivity, scale, mirror, dynamic title template, background playback/motion; unsupported frequency controls disembunyikan untuk style yang tidak mendukung.
- `responsive_workspace.py`: tombol manual `+ Spectrum` dan `+ Judul Lagu`, preset diterapkan sebagai satu batch command/undo transaction.
- `editor_session.py`: add spectrum/title melalui command stack dan binding album yang stabil.
- regression S02 diperbarui: fail-closed sekarang memakai circular/unsupported spectrum, bukan spectrum release yang sudah sah di S05.

## Gate yang diminta

Lihat `docs/S05_ACCEPTANCE.md`. Bukti CI dan artifact akan ditambahkan setelah run PR hijau.