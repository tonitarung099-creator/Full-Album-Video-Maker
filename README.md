# Full Album Maker

Aplikasi Windows portable untuk membuat video **full album YouTube** dari banyak file audio dan elemen visual, dengan editor timeline, template, spectrum, render FFmpeg, serta Agen AI Gemini opsional.

> Status: **Stable v1.4.0 candidate**. Fitur manual v1.1–v1.3 (Cover Manager, Circular Spectrum, Free Timeline, dan Visual Lagu) sekarang juga tersedia melalui intent Gemini yang tetap divalidasi engine lokal. Build Windows portable tetap wajib melewati regression suite, real FFmpeg render, dan smoke ZIP hasil ekstrak tanpa Python/FFmpeg global atau API key sebelum release dipublikasikan.

## Fitur utama

- Import banyak MP3/WAV/FLAC dan susun playlist.
- Timeline **Packed** dan **Free Timeline**, termasuk gap/silence dan crossfade eksplisit.
- Editor layer visual dengan Undo/Redo, Snap, Preview Akurat, dan inspector.
- Tab **Cover** untuk memasang/menghapus cover ke banyak lagu sekaligus serta pencocokan nama otomatis yang deterministik dan fail-closed bila ambigu.
- Tab **Visual Lagu** untuk memasang foto/video per lagu, auto-match nama, motion foto (zoom/pan), playback video loop/freeze, dan transisi cut/fade/slide yang mengikuti pergantian lagu.
- 10 template built-in: Spotify Clean, Cafe Acoustic, Viral Full Album, Vinyl Nostalgia, Neon Spectrum, Romantic Bokeh, Dark Cinematic, Photo Album, Cassette Retro, dan Music Channel Pro.
- Spectrum/waveform: Bars, Spectrum Line, Waveform, Stereo Waveform, serta **Circular Spectrum** dengan preset Circular Neon dan radius dalam yang dapat diatur.
- Circular Spectrum memakai audio visualizer nyata + polar mapping FFmpeg, Preview Akurat/final render satu compiler, dan remap internal dibatasi maksimal 512×512 sebelum di-scale ke box layer agar biaya render tetap bounded.
- Overlay procedural seperti bokeh, glow, light leak, grain, VHS noise, vignette, dan particles.
- Render H.264/H.265 melalui FFmpeg serta YouTube chapters, tracklist, dan timeline sidecar.
- Custom template portabel untuk layout/effect yang tidak bergantung pada asset project eksternal.
- **Gemini AI parity v1.4**: bahasa manusia dapat mengatur Cover, Visual Lagu, Circular Spectrum, serta Free Timeline/crossfade. Gemini hanya menerjemahkan intent; stable ID, ambiguity, revision, validasi, Undo, dan render tetap dikerjakan lokal.
- Context AI tidak mengirim locator/path media atau API key; media hanya diekspos sebagai ID stabil + nama file aman.
- Pool hingga 100 API key Gemini dengan failover/cooldown; penggunaan AI tetap opsional.
- Tetap dapat dipakai manual dan merender tanpa AI/internet.
- Distribusi utama: **ZIP portable multi-file**, tanpa installer dan tanpa hak admin.

## Portable Windows

Paket v1.4.0 bernama `Full-Album-Maker-v1.4.0-Windows-Portable.zip` dan berisi EXE onedir, runtime/DLL PySide6, FFmpeg + ffprobe, fallback Noto Sans, assets, notices, `CAPABILITIES.json`, folder `data`, `temp`, dan `output`.

Setiap GitHub Release juga menyertakan `SHA256SUMS.txt`. Di PowerShell Windows, checksum ZIP dapat diverifikasi dengan:

```powershell
Get-FileHash .\Full-Album-Maker-v1.4.0-Windows-Portable.zip -Algorithm SHA256
```

Nilai SHA-256 harus sama dengan nilai untuk nama ZIP tersebut di `SHA256SUMS.txt`.

Untuk build lokal yang mengikuti gate release, jalankan dari PowerShell Windows:

```powershell
.\build\build_portable.ps1
```

Script ini memakai dependency build terkunci, memverifikasi SHA-256 FFmpeg, menjalankan seluruh test, membuat ZIP versi + `SHA256SUMS.txt`, memverifikasi checksum, lalu mengekstrak dan melakukan `--portable-smoke` tanpa Python/FFmpeg global dan tanpa API key.

Pada push `main`, workflow Windows hanya mempublikasikan GitHub Release untuk versi aplikasi setelah regression, real FFmpeg, PyInstaller, ZIP, checksum, dan isolated portable smoke selesai sukses.

## Keamanan API key dan AI

API key **tidak pernah disimpan di source code atau GitHub**. Pada Windows, key disimpan lokal menggunakan Windows DPAPI. Render manual tidak membutuhkan Gemini/API key.

Gemini tidak menerima path media mentah. Untuk assignment Cover/Visual Lagu, context hanya memuat `asset_id`, tipe media, dan nama file aman. Query nama fallback memakai exact-normalized match lokal; kasus ambigu dihentikan dan meminta pilihan eksplisit.

## Catatan kemampuan

- Schema project tetap versi 2; v1.4.0 tidak menambah migrasi format project.
- Gemini v1.4 dapat memasang/menghapus cover atau visual per lagu, auto-match lokal, mengatur style Visual Lagu, menambah/mengubah Circular Spectrum, dan mengatur mode/timing Free Timeline.
- Satu respons AI tetap disimulasikan pada clone lalu di-commit sebagai satu transaksi Undo; stale revision/ID tidak dikenal/ambiguity tetap menghasilkan 0 mutasi.
- Visual Lagu memakai compiler final/Preview Akurat yang sama. Foto dapat slow zoom/pan, sedangkan video dapat loop atau freeze frame.
- Transisi visual: cut, fade, slide kiri, dan slide kanan.
- Stress 3 jam di CI menguji model, resolver, render plan/graph, dan keamanan command-line; CI tidak melakukan full encode video selama 3 jam.
- Detail kemampuan artifact portable tersedia di `CAPABILITIES.json`.
- Release notes v1.4.0 tersedia di `docs/RELEASE_NOTES_v1.4.0.md`.

## Lisensi

MIT untuk kode Full Album Maker. Dependensi dan asset pihak ketiga mengikuti lisensinya masing-masing; lihat `THIRD_PARTY_NOTICES.md` pada source dan artifact portable.
