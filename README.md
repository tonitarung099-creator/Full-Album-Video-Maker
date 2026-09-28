# Full Album Maker

Aplikasi Windows portable untuk membuat video **full album YouTube** dari banyak file audio dan elemen visual, dengan editor timeline, template, spectrum, render FFmpeg, serta Agen AI Gemini opsional.

> Status: **Release Candidate** setelah milestone S01–S12. Build Windows portable diuji dengan regression suite, proyek 200 lagu / 3 jam pada resolver+render graph, real FFmpeg render, dan smoke ZIP hasil ekstrak tanpa Python/FFmpeg global atau API key.

## Fitur utama

- Import banyak MP3/WAV/FLAC dan susun playlist.
- Timeline **Packed** dan **Free Timeline**, termasuk gap/silence dan crossfade eksplisit.
- Editor layer visual dengan Undo/Redo, Snap, Preview Akurat, dan inspector.
- 10 template built-in: Spotify Clean, Cafe Acoustic, Viral Full Album, Vinyl Nostalgia, Neon Spectrum, Romantic Bokeh, Dark Cinematic, Photo Album, Cassette Retro, dan Music Channel Pro.
- Spectrum/waveform dan overlay procedural seperti bokeh, glow, light leak, grain, VHS noise, vignette, dan particles.
- Render H.264/H.265 melalui FFmpeg serta YouTube chapters, tracklist, dan timeline sidecar.
- Custom template portabel untuk layout/effect yang tidak bergantung pada asset project eksternal.
- Gemini Agent untuk memahami perintah bahasa manusia pada operasi editor yang sudah didukung; edit tetap divalidasi dan dieksekusi engine lokal.
- Pool hingga 100 API key Gemini dengan failover/cooldown; penggunaan AI tetap opsional.
- Tetap dapat dipakai manual dan merender tanpa AI/internet.
- Distribusi utama: **ZIP portable multi-file**, tanpa installer dan tanpa hak admin.

## Portable Windows

Artifact release berisi EXE onedir, runtime/DLL PySide6, FFmpeg + ffprobe, fallback Noto Sans, assets, notices, `CAPABILITIES.json`, folder `data`, `temp`, dan `output`.

Untuk build lokal yang mengikuti gate release, jalankan dari PowerShell Windows:

```powershell
.\build\build_portable.ps1
```

Script ini memakai dependency build terkunci, memverifikasi SHA-256 FFmpeg, menjalankan seluruh test, membuat ZIP, lalu mengekstrak dan melakukan `--portable-smoke` tanpa Python/FFmpeg global dan tanpa API key.

## Keamanan API key

API key **tidak pernah disimpan di source code atau GitHub**. Pada Windows, key disimpan lokal menggunakan Windows DPAPI. Render manual tidak membutuhkan Gemini/API key.

## Catatan kemampuan

- Circular Spectrum masih ditunda sampai spike teknis packaging/performa/parity/cancel memenuhi gate yang ditentukan.
- Stress 3 jam di CI menguji model, resolver, render plan/graph, dan keamanan command-line; CI tidak melakukan full encode video selama 3 jam.
- Detail kemampuan artifact portable tersedia di `CAPABILITIES.json`.

## Lisensi

MIT untuk kode Full Album Maker. Dependensi dan asset pihak ketiga mengikuti lisensinya masing-masing; lihat `THIRD_PARTY_NOTICES.md` pada source dan artifact portable.