# Full Album Maker v1.4.0

Feature release di atas v1.3.0. Fokus utama: **Gemini AI parity** dengan fitur editor terbaru tanpa mengubah provider, key pool, schema project, atau renderer.

## Gemini AI parity

Panel Gemini sekarang dapat menerjemahkan bahasa manusia menjadi intent lokal untuk:

- tambah/ubah Circular Spectrum;
- pasang/hapus cover ke satu atau banyak lagu;
- auto-match cover berdasarkan exact-normalized nama lokal;
- pasang/hapus foto/video Visual Lagu;
- auto-match Visual Lagu;
- atur fit, motion foto, playback video, transisi, dan durasi transisi Visual Lagu;
- ubah Packed/Free Timeline;
- atur posisi lagu dan crossfade Free Timeline.

Semua intent baru memakai engine yang sama dengan UI manual. Tidak ada renderer/state AI kedua.

## Context dan privasi

Context Gemini v1.4 menambah kandidat media (`asset_id`, tipe, nama file aman), assignment cover/visual per lagu, timing Free Timeline, serta ringkasan layer spectrum/Visual Lagu.

Locator/path media, API key, waveform/cache, dan raw metadata tidak dikirim ke Gemini.

## Safety/transaction contract

- stable `song_id`, `layer_id`, dan `asset_id` tetap canonical;
- exact asset query yang ambigu dihentikan, tidak ditebak;
- auto-match hanya berjalan bila intent auto-match eksplisit;
- timing Free hanya diubah ketika pengguna meminta timing/gap/crossfade/mode;
- seluruh aksi dalam satu respons AI tetap satu revision + satu Undo;
- invalid overlap/crossfade, stale revision, unknown ID, atau ambiguity menghasilkan 0 mutasi;
- render tetap hanya terjadi bila pengguna meminta render eksplisit.

## Kompatibilitas

- Project schema tetap versi 2.
- Project v1.0–v1.3 tetap dapat dibuka tanpa migrasi baru.
- Cover Manager, Circular Spectrum, Free Timeline, dan Visual Lagu tetap dapat digunakan manual tanpa Gemini/API key.
- Renderer dan Preview Akurat tidak berubah jalur hanya karena edit berasal dari AI.

## Gate release

v1.4.0 hanya boleh dipublikasikan setelah seluruh regression v1.3 + test AI parity, real FFmpeg, PyInstaller Windows onedir, ZIP + SHA256SUMS, isolated portable smoke yang membangun jendela v1.4, dan post-merge `main` gate semuanya lulus.
