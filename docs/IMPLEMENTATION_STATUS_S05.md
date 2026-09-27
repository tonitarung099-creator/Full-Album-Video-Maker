# S05 — Spectrum Core + Dynamic Song Title

Status: implementasi selesai pada PR #23; gate Windows PR hijau dan siap merge.

## Yang diimplementasikan

- `spectrum_feature.py`: capability registry, preset release, normalisasi properties, factory layer spectrum dan dynamic title.
- `render_graph.py`: spectrum/waveform audio-driven via FFmpeg, audio `asplit`, alpha colorkey, visual-only gain, dynamic song title per `song_id`, background loop/freeze dan zoom/pan.
- `preview_scene.py`: proxy spectrum ringan pada canvas editor dan dynamic title berdasarkan lagu aktif; Preview Akurat tetap memakai compiler final.
- `property_inspector.py`: properties spectrum, preset, sensitivity, scale, mirror, dynamic title template, background playback/motion; unsupported frequency controls disembunyikan untuk style yang tidak mendukung.
- `responsive_workspace.py`: tombol manual `+ Spectrum` dan `+ Judul Lagu`, preset diterapkan sebagai satu batch command/undo transaction.
- `editor_session.py`: add spectrum/title melalui command stack dan binding album yang stabil.
- regression S02 diperbarui: fail-closed sekarang memakai circular/unsupported spectrum, bukan spectrum release yang sudah sah di S05.
- workflow Windows menambahkan FFmpeg/FFprobe bundled ke `PATH` sebelum pytest, sehingga regression render nyata tidak lagi lolos karena tool tidak ditemukan.

## Bukti gate PR

Workflow **Build Windows Portable #125**, run `36304662789`, head `23169fbcf4171b1fa7f6d5cbbecfe40375391cef`:

- FFmpeg bundled yang diuji: `n9.0.2-10-g51c4a23d74-20260926`.
- **207 passed, 0 skipped**, 2 warning deprecation PySide6 test-only.
- Real FFmpeg spectrum tests untuk Bars, Spectrum Line, Waveform dan Stereo Waveform ikut berjalan.
- Silence + Accurate Preview smoke ikut berjalan.
- PyInstaller Windows **onedir** sukses.
- FFmpeg + notices bundling sukses.
- Portable ZIP sukses dan ter-upload.
- Artifact: `Full-Album-Maker-Windows-Portable`.
- Artifact ID: `10926488833`.
- Size: `182532924` bytes.
- SHA-256: `e8997b07b69c37d3a20b36d11871c7578bf3e90e90856b6647a619572df18e01`.

## Catatan gate

Run awal menemukan satu mismatch pesan regression rotasi text dan juga menunjukkan FFmpeg belum tersedia di PATH pytest. Keduanya diperbaiki tanpa menurunkan kriteria: assertion tetap fail-closed dan workflow sekarang memaksa real FFmpeg test aktif.