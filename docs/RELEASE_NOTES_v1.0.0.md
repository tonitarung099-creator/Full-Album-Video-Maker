# Full Album Maker v1.0.0

Rilis stabil pertama Full Album Maker untuk Windows portable.

## Sorotan

- Editor V2 dengan layer visual, Undo/Redo, Snap, inspector, Preview Akurat, dan final render FFmpeg.
- Playlist audio dengan mode Packed dan Free Timeline, termasuk gap/silence serta crossfade eksplisit.
- 10 template built-in: Spotify Clean, Cafe Acoustic, Viral Full Album, Vinyl Nostalgia, Neon Spectrum, Romantic Bokeh, Dark Cinematic, Photo Album, Cassette Retro, dan Music Channel Pro.
- Spectrum/waveform nyata serta overlay procedural seperti bokeh, glow, light leak, grain, VHS noise, vignette, dan particles.
- Gemini Agent opsional untuk memahami perintah bahasa manusia; mutasi tetap divalidasi dan dijalankan engine lokal.
- Pool hingga 100 API key Gemini dengan failover/cooldown.
- Render H.264/H.265, YouTube chapters, tracklist, dan timeline sidecar.
- ZIP portable multi-file tanpa installer dan tanpa hak admin.

## Portable Windows

Paket resmi:

`Full-Album-Maker-v1.0.0-Windows-Portable.zip`

Isi utama mencakup `Full Album Maker.exe`, runtime/DLL PySide6, FFmpeg, ffprobe, Noto Sans fallback, assets, notices, `CAPABILITIES.json`, serta folder `data`, `temp`, dan `output`.

Aplikasi dapat menjalankan workflow manual, preview, template, dan render tanpa Gemini/API key. AI hanya dibutuhkan saat fitur Agen AI digunakan.

## Validasi release

Release hanya dipublikasikan setelah workflow Windows pada commit `main` lulus seluruh gate berikut:

- regression suite lengkap;
- real FFmpeg render tests;
- stress resolver/render graph 200 lagu × 54 detik = 3 jam;
- PyInstaller Windows onedir;
- validasi FFmpeg pinned SHA-256 dan font fallback;
- pembuatan ZIP portable versi;
- ekstraksi ZIP pada path dengan spasi, Unicode, dan apostrof;
- smoke tanpa Python global, FFmpeg global, Gemini key, atau Google API key;
- verifikasi output smoke memiliki stream audio + video;
- konstruksi GUI frozen dan verifikasi title versi release.

## Perbaikan menuju stabil

- Output Editor V2 tanpa ekstensi otomatis menjadi `.mp4`; ekstensi non-MP4 ditolak jelas.
- Dirty-state editor dan proyek legacy diperketat agar perubahan belum disimpan tidak hilang.
- Path save proyek legacy mengikuti file `.json` aktual yang dibuat.
- Build lokal dan CI memakai kontrak release yang sama.
- Paket release menggunakan nama versi dan `CAPABILITIES.json` mencatat versi aplikasi/tag release.

## Batasan yang diketahui

- Circular Spectrum masih ditunda sampai gate packaging, performa, preview/render parity, dan cancel memenuhi standar release.
- CI tidak full-encode album tiga jam; proyek 3 jam dipakai untuk stress model/resolver/render-plan/graph, sedangkan encoder diverifikasi dengan render FFmpeg nyata yang lebih pendek.
- Font custom yang dipilih pengguna tetap menjadi tanggung jawab pengguna; paket portable menyediakan Noto Sans sebagai fallback deterministik.
- Aksi Gemini tidak tersedia tanpa API key, tetapi editing manual, template, preview, dan render tetap tersedia offline.

## Lisensi

Kode Full Album Maker menggunakan lisensi MIT. Dependensi dan asset pihak ketiga mengikuti lisensi masing-masing; lihat `THIRD_PARTY_NOTICES.md` pada source dan paket portable.
