# Full Album Maker v1.4.0 — Gemini AI Parity Acceptance

## Tujuan

v1.4.0 menyamakan kemampuan panel Gemini dengan fitur manual yang sudah stabil pada v1.1–v1.3 tanpa mengganti provider, key pool, schema project, atau renderer.

Gemini tetap hanya menerjemahkan bahasa manusia menjadi intent. Seluruh mutasi, validasi, ambiguity handling, revision guard, Undo/Redo, Preview Akurat, dan render tetap dilakukan engine lokal.

## Fitur AI baru

- Tambah Circular Spectrum dengan preset Circular Neon.
- Ubah spectrum existing menjadi Circular Spectrum dan atur radius dalam/color/gain.
- Pasang/hapus cover ke satu atau banyak lagu berdasarkan stable `song_id`.
- Auto-match cover lokal dengan exact-normalized matcher yang sama dengan Cover Manager.
- Pasang/hapus foto/video Visual Lagu ke satu atau banyak lagu.
- Auto-match Visual Lagu lokal dengan matcher fail-closed v1.3.
- Atur style Visual Lagu: fit, motion foto, playback video, transisi, durasi transisi.
- Ubah Timeline Audio Packed/Free.
- Atur start lagu dan crossfade; Free Timeline diaktifkan otomatis hanya ketika intent timing eksplisit dikirim.

## Context AI

Context v1.4 menambah:

- `playlist_mode`;
- `cover_asset_id` dan `visual_asset_id` per kandidat lagu;
- free start/crossfade per kandidat lagu;
- `media_candidates` berupa `asset_id`, `kind`, dan nama file aman;
- ringkasan spectrum layer dan Song Visual layer.

Context **tidak** memuat locator/path media, API key, waveform/cache, atau raw metadata project.

## Kontrak keselamatan

1. Asset assignment harus memakai `asset_id` yang tersedia di project atau exact-normalized `asset_query` lokal.
2. Duplicate asset/query ambiguity tidak boleh ditebak; executor mengembalikan `AIEditorAmbiguity` dan 0 mutasi.
3. `song_ids` dan `layer_id` yang tidak ada pada revision saat ini ditolak sebelum commit.
4. Auto-match hanya dijalankan melalui tool auto-match eksplisit.
5. Free Timeline hanya diubah melalui tool timing/mode eksplisit.
6. Circular Spectrum menggunakan renderer canonical v1.2; tidak ada renderer AI khusus.
7. Visual Lagu menggunakan data canonical `SongInstance.visual_asset_id` dan layer `song_visual`; tidak ada state AI kedua.
8. Seluruh function call dalam satu respons Gemini tetap disimulasikan pada clone dan di-commit sebagai satu transaction/revision/Undo.
9. Duplicate action ID tetap idempotent.
10. Render tetap hanya dipanggil jika intent `render_project` eksplisit ada setelah commit edit sukses.

## Gate regression

- Registry v1.4 tetap memuat semua tool S09 dan tool baru tanpa nama duplikat.
- Context media aman: ID + basename saja, tanpa path rahasia.
- Bulk cover + visual dalam satu respons = satu revision + satu Undo.
- Ambiguous asset query = exception + 0 mutasi.
- Auto-match `only_empty` mempertahankan assignment lama.
- Circular Spectrum + Visual Lagu style dapat dibuat dalam satu batch dan Undo mengembalikan state awal.
- Timing eksplisit dapat mengubah Packed → Free + crossfade valid dalam satu transaction.
- Overlap tanpa crossfade valid harus rollback seluruh conversion/timing.
- Portable smoke harus membangun `V14EditorMainWindow` dan memastikan context builder v1.4 aktif pada frozen EXE.
- Seluruh regression v1.3, real FFmpeg, PyInstaller onedir, ZIP + SHA256SUMS, isolated smoke dan artifact upload wajib tetap hijau.
