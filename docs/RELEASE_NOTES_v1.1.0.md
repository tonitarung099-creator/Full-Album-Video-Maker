# Full Album Maker v1.1.0

Feature release pertama setelah stable v1.0.x. Format project tetap kompatibel dengan v1.0.2; tidak ada schema migration.

## Fitur baru — Cover Manager

Editor V2 sekarang memiliki tab **Cover** khusus untuk pengelolaan cover per lagu:

- pilih beberapa lagu lalu pasang satu cover ke semuanya;
- hapus cover khusus dari beberapa lagu sekaligus;
- `Cocokkan Nama` untuk memasangkan cover image berdasarkan judul/nama file;
- opsi **Hanya yang kosong** aktif secara default agar cover lama tidak tertimpa;
- pencocokan otomatis bersifat exact-normalized, bukan fuzzy guessing;
- duplicate/ambiguous match tidak diterapkan dan dilaporkan sebagai ambigu;
- seluruh aksi massal menjadi satu transaksi Undo/Redo.

## Keamanan data dan kompatibilitas

- Assignment memakai `song_id` dan `asset_id` yang stabil.
- Asset non-image ditolak sebagai cover.
- Project schema tetap `2` dan `SongInstance.cover_asset_id` yang sudah ada tetap menjadi sumber data canonical.
- Renderer dan Preview Akurat tetap memakai jalur S06 yang sama; tidak ada renderer alternatif khusus Cover Manager.
- Existing project v1.0.x tetap dapat dibuka tanpa migrasi cover baru.

## Pipeline Windows

v1.1.0 mempertahankan hardening release v1.0.2:

- Windows portable multi-file / PyInstaller onedir;
- GitHub Actions berbasis Node 24 dipin full commit SHA;
- FFmpeg dipin melalui immutable release asset ID + SHA-256;
- seluruh regression + real FFmpeg test wajib lulus;
- ZIP versi dan `SHA256SUMS.txt` wajib dibuat;
- isolated portable smoke dijalankan tanpa Python/FFmpeg global dan tanpa API key;
- GitHub Release hanya dipublikasikan setelah gate push `main` sukses.

## Batasan yang tetap berlaku

- Circular Spectrum masih ditunda sampai packaging/performance/preview-render parity/cancel gate terpenuhi.
- Auto-match Cover Manager tidak mencoba pencarian web, fuzzy match, atau AI guess. Kasus ambigu sengaja dibiarkan untuk dipilih pengguna.
- CI tidak melakukan full encode album tiga jam; stress tiga jam tetap menguji model/resolver/render graph dan real FFmpeg diuji dengan render lebih pendek.
