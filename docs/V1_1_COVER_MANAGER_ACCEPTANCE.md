# Full Album Maker v1.1.0 — Cover Manager Acceptance

## Tujuan

v1.1.0 menutup gap UI dari S06: model dan renderer sudah mendukung `SongInstance.cover_asset_id`, tetapi pengguna belum memiliki alur khusus untuk memasang cover ke banyak lagu secara efisien.

## Kontrak fitur

1. Editor V2 memiliki tab `Cover` yang terpisah dari drag/drop Playlist.
2. Satu image asset dapat dipasang ke satu atau banyak lagu terpilih.
3. Cover khusus dapat dihapus dari satu atau banyak lagu terpilih.
4. Setiap aksi massal dikirim sebagai satu transaksi `EditorController`, sehingga satu Undo mengembalikan seluruh perubahan dalam aksi tersebut.
5. Identitas mutasi selalu memakai `song_id` dan `asset_id`, bukan nomor baris atau path sebagai identity.
6. Hanya `MediaAsset.kind == image` yang dapat dipasang sebagai cover.
7. Pencocokan otomatis bersifat deterministik dan konservatif:
   - Unicode dinormalisasi NFKC dan case-insensitive;
   - ekstensi media yang dikenal serta prefix nomor track filename dapat diabaikan;
   - separator/punctuation dinormalisasi;
   - tidak ada fuzzy/semantic guessing;
   - bila satu key mengarah ke lebih dari satu lagu atau lebih dari satu image, hasil dinyatakan ambigu dan tidak diterapkan.
8. Opsi `Hanya yang kosong` aktif secara default agar cover yang sudah dipilih pengguna tidak tertimpa.
9. Schema project tetap versi 2; tidak ada migrasi format project untuk fitur ini.
10. Renderer/Preview Akurat tidak memiliki jalur baru. Keduanya tetap membaca `cover_asset_id` melalui implementation S06 yang sudah diuji real FFmpeg.

## Gate regression

Test v1.1.0 harus mencakup:

- exact normalized matching;
- judul yang mengandung titik, Unicode, prefix nomor track, dan separator filename;
- fallback matching dari nama file audio ketika display title kosong;
- duplicate/ambiguous cover yang harus fail-closed;
- lagu tanpa pasangan cover;
- proteksi cover lama dengan `Hanya yang kosong`;
- validasi asset non-image dan song_id tidak dikenal;
- multi-selection UI berbasis stable song_id;
- satu revision dan satu Undo untuk bulk assignment;
- tab Cover tersedia pada workspace yang digunakan aplikasi.

## Gate release

PR hanya boleh merge bila Windows workflow pada exact head lulus seluruh regression lama + test v1.1.0, real FFmpeg, PyInstaller onedir, versioned portable ZIP, SHA256SUMS, isolated portable smoke, dan upload artifact. Setelah merge, push `main` harus mengulang gate yang sama sebelum release `v1.1.0` dipublikasikan.
