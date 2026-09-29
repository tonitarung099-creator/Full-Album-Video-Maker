# Full Album Maker v1.3.0

Feature release di atas v1.2.0. Fokus utama: **Visual Lagu per-song** dan transisi foto/video yang tersinkron dengan timeline audio.

## Visual Lagu

- Tab baru **Visual Lagu** di Editor V2.
- Pasang foto/video ke satu atau banyak lagu sekaligus.
- Hapus visual khusus secara massal dengan satu Undo.
- `Cocokkan Nama` exact-normalized berdasarkan judul/nama file; kasus ambigu tidak ditebak.
- Opsi `Hanya yang kosong` menjaga assignment lama agar tidak tertimpa otomatis.
- Assignment tetap memakai `SongInstance.visual_asset_id` canonical yang sudah ada di schema v2.

## Motion dan playback

Foto:
- Static
- Zoom In
- Zoom Out
- Pan Left
- Pan Right

Video:
- Loop
- Freeze Frame

## Transisi

- Cut
- Fade
- Slide Kiri
- Slide Kanan

Durasi transisi dapat diatur 0–5 detik dan dibatasi oleh durasi visual aktif. Incoming visual ditumpuk di atas outgoing visual agar fade/slide terjadi di sekitar pergantian lagu tanpa mengubah audio timeline.

## Renderer

`V13FFmpegCompiler` membangun graph S10/S11 yang sudah stabil terlebih dahulu, lalu menyisipkan footage per-song setelah base canvas dan sebelum overlay existing. Dengan ini:
- Free Timeline/crossfade audio tetap memakai resolver/graph lama;
- spectrum, cover, title, playlist, progress, overlay, dan Circular Spectrum tetap berada di atas footage;
- Preview Akurat dan final render tetap menggunakan compiler yang sama;
- media visual hilang ditolak saat preflight sebelum output dipublikasikan.

## Kompatibilitas

- Project schema tetap versi 2.
- Project v1.0–v1.2 tetap dapat dibuka tanpa migrasi baru.
- `visual_asset_id` yang sudah tersimpan sebelumnya langsung digunakan oleh layer Song Visual bila fitur diaktifkan.

## Gate release

v1.3.0 hanya dipublikasikan setelah regression suite, real FFmpeg foto/video, Preview Akurat, PyInstaller Windows onedir, ZIP + SHA256SUMS, isolated portable smoke, dan post-merge `main` gate semuanya lulus.
