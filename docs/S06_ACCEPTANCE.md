# S06 Acceptance — Visual Album Lanjutan

## Scope

S06 menambahkan visual album lanjutan di atas state ProjectDocument v2 yang sama. Tidak ada schema paralel atau renderer kedua.

## Dynamic song cover

- Layer `song_cover` memakai `SongInstance.cover_asset_id` berdasarkan `song_id` aktif.
- Bila lagu tidak punya cover, layer boleh memakai `fallback_asset_id` image.
- Reorder playlist tidak boleh memutus hubungan cover dengan lagunya.
- Fit release: `fill` dan `fit`.
- Preview Akurat dan final render memakai pemilihan cover yang sama.
- Test real frame harus membuktikan cover berubah saat lagu aktif berganti, bukan hanya bahwa render tidak crash.

## Vinyl / disc

- Layer `vinyl` dibuat secara prosedural, tidak membutuhkan asset tambahan.
- Bentuk release: disc transparan di luar lingkaran, groove, label tengah, indikator rotasi.
- Kecepatan putar dapat diedit melalui `spin_seconds`.
- Warna disc/groove/label, opacity, transform dan rotation harus persist di project.

## Playlist visual

- Layer `playlist_visual` menampilkan urutan playlist yang sama dengan audio schedule.
- Mendukung jumlah item per halaman, numbering, artist opsional, warna normal/aktif, font size dan background opacity.
- Lagu aktif harus di-highlight berdasarkan `song_id` dan interval resolver.
- Untuk playlist lebih panjang dari `max_items`, halaman visual harus mengikuti kelompok lagu aktif; tidak boleh memotong urutan atau memakai index lama setelah reorder.

## Progress + duration

- Layer `progress` memiliki mode `song` dan `album`.
- Mode `song` reset pada awal setiap lagu dan mencapai akhir pada event lagu tersebut.
- Mode `album` bergerak dari 0 sampai durasi album.
- Layer `song_time` memiliki mode `song` dan `album`; mode song reset elapsed time saat lagu berganti.
- Progress/time tidak boleh memengaruhi audio master.

## Editor

- Tombol manual release: `+ Cover`, `+ Vinyl`, `+ Playlist`, `+ Progress`.
- `+ Progress` menambah progress bar + time sebagai satu transaksi undo.
- Cover/vinyl/playlist/progress dapat dipindah/resize/rotate pada canvas.
- Semua properti release yang benar-benar didukung renderer tersedia di inspector.
- Canvas biasa boleh memakai proxy ringan, tetapi Preview Akurat wajib memakai `FFmpegV2Compiler.compile_frame` yang sama dengan render final.

## Gate test

- Factory/property validation untuk seluruh type S06.
- Add layer + undo/redo transaction.
- Compiler graph berisi dynamic cover, vinyl, playlist, progress dan song-time.
- Real FFmpeg render dua lagu dengan dua cover berbeda.
- Accurate Preview frame lagu pertama vs kedua membuktikan cover mengikuti lagu aktif.
- Real render mode progress/time `song` dan `album`.
- Existing regression suite S01–S05 tetap hijau.
- Windows PyInstaller onedir + bundled FFmpeg + portable ZIP sukses pada PR head yang sama.

## Definition of Done

S06 hanya boleh merge jika full pytest, real FFmpeg render, Accurate Preview, Windows onedir build, bundling FFmpeg/notices, ZIP portable dan artifact upload lulus pada head PR yang sama.