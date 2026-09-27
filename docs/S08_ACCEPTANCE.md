# S08 Acceptance — Custom Template Builder

## Tujuan

Pengguna dapat menyusun layout di canvas, menyimpannya sebagai template kustom, lalu menerapkan layout itu di project lain tanpa membawa referensi project yang stale.

## Format dan penyimpanan

- Format file: `full-album-maker-custom-template`, version `1`.
- Ekstensi ekspor: `.famtpl.json`.
- Penyimpanan lokal portable: `data/templates/custom/` relatif ke folder aplikasi.
- Nama file internal memakai UUID template, bukan nama yang diberikan pengguna.
- Save lokal memakai temp file + `os.replace` agar atomic.
- Import dengan ID yang sudah ada tidak boleh overwrite diam-diam; dibuat copy dengan UUID baru.
- Satu file corrupt di folder template tidak boleh membuat template valid lain gagal dimuat.

## Portabilitas

Template menyimpan layout/properties, bukan asset project.

- Layer yang didukung: background solid, text, spectrum, song_title, song_cover, vinyl, playlist_visual, progress, song_time.
- `layer_id`, `track_id`, `asset_refs`, `song_id`, absolute timing, dan fallback asset ID project sumber tidak dibawa ke target.
- Semua layer target mendapat UUID baru dan binding `album`.
- `song_cover.fallback_asset_id` di-resolve ulang ke image pertama project target.
- `font_path` text/title dibuang agar tidak membawa path mesin sumber.
- Background image/video atau layer dengan asset refs eksternal harus fail-closed saat capture, bukan tersimpan sebagai template rusak.

## Apply dan Undo

- Hasil custom template tetap normal `Layer` dengan `origin=template` dan editable penuh.
- Apply custom mengganti layer template sebelumnya, tetapi mempertahankan layer manual target yang tidak berasal dari capture project yang sama.
- Jika template diterapkan kembali pada project sumber yang sama, layer manual yang menjadi sumber capture diganti, bukan diduplikasi.
- Layer sumber yang terkunci membuat apply fail-closed.
- Apply custom adalah satu history transaction: satu Undo mengembalikan template sebelumnya, canvas background, marker template, dan source manual layer yang diganti.
- Apply built-in setelah custom harus membersihkan marker custom dalam transaksi undo yang sama.

## UI

Toolbar compact menyediakan:

- selector built-in + custom,
- Terapkan Template,
- Simpan Kustom,
- Impor Template,
- Ekspor Template,
- Hapus Kustom.

Ekspor/Hapus hanya aktif saat item custom dipilih. Katalog custom direfresh setelah save/import/delete.

## Gate

- Capture sanitization test.
- Fresh UUID + fallback relink test.
- Same-project no-duplicate + single-undo test.
- Cross-project manual-layer preservation test.
- Built-in/custom marker transition test.
- Store roundtrip, export/import collision, corrupt-file isolation.
- Unsupported asset-backed background fail-closed.
- ResponsiveEditorWorkspace catalog/apply test.
- Real FFmpeg video+audio render setelah custom template diterapkan ke project lain.
- Seluruh regression S01–S07 tetap hijau.
- Windows PyInstaller onedir, bundled FFmpeg, portable ZIP, artifact upload tetap wajib hijau.
