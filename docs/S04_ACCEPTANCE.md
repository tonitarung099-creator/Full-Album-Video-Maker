# S04 — Timeline Interaktif dan Preview Canvas

Baseline: `main` @ `3ec5b93debe5c9bfcd8de7c6332f852a5d436aec`.

## Perilaku yang diimplementasikan

- Editor v2 menjadi surface tengah aplikasi lewat `EditorMainWindow`, tanpa monkey patch editor baru.
- Panel Media legacy dan panel AI kanan tetap tersedia; media baru disinkronkan ke library `ProjectDocument` v2 dengan asset ID stabil.
- Timeline v2 memiliki lane track, ruler, scroll horizontal, zoom, snap, playhead, seleksi, move, trim, duplicate, delete, track show/lock dan layer lock/show.
- Gesture timeline menyimpan skala waktu pada mouse-down dan baru membuat satu command pada mouse-release, sehingga satu drag = satu undo dan perubahan zoom di tengah gesture tidak mengubah delta waktunya.
- Preview canvas memiliki seleksi dan transform langsung. Background visual mendukung move/resize/rotate; text mendukung posisi dan properti yang memiliki parity render.
- Inspector mengedit transform yang didukung, opacity, waktu, visibilitas, lock, teks dan warna melalui command stack yang sama.
- Playback/seek editor menggunakan playhead lokal; Space play/pause, panah seek, Ctrl+Z/Y undo/redo, Ctrl+D duplicate, Delete/Backspace delete. Shortcut edit dinonaktifkan saat fokus ada di input teks/spinbox.
- `Preview Akurat` tetap memakai compiler FFmpeg yang sama dengan final render.
- Background transform posisi/ukuran/rotasi/opacity sekarang masuk compiler FFmpeg S04. Unsupported layer/transform tetap fail-closed.
- Open/save project v2 menggunakan repository atomik yang sama dengan S01.

## Gate S04

Test baru mencakup:

- konversi pixel/tick dan gesture-scale yang stabil terhadap perubahan zoom;
- move/trim/transform sebagai satu transaksi undo;
- duplicate/delete dan undo/redo;
- track/layer show-lock;
- snap ke batas lagu/layer;
- save/load state setelah edit;
- compiler FFmpeg memuat background position/size/rotation/opacity;
- text rotation fail-closed sampai parity render tersedia;
- workspace/inspector/timeline/preview offscreen;
- jendela utama pada 1366x768 dan panel AI tetap tersedia;
- zoom UI tidak memutasi waktu ProjectDocument.

Workflow Windows sekarang juga berjalan pada pull request agar gate diuji sebelum merge: seluruh pytest, real FFmpeg render, PyInstaller onedir, bundle dan ZIP portable.

## Batas tahap

- Playback S04 adalah scrub/playhead visual; audio monitoring real-time belum dijadikan gate tahap ini.
- Rotasi/resize text belum ditawarkan karena compiler S04 belum memiliki parity untuk transform tersebut.
- Spectrum, dynamic song title, cover/vinyl, playlist visual dan progress tetap S05/S06.
- Free timeline audio gap/crossfade tetap S11.
