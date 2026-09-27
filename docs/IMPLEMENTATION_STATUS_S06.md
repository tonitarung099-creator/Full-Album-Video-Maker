# S06 — Visual Album Lanjutan

Status: implementasi berada di branch `sol/s06-album-visuals`; menunggu gate Windows PR sebelum merge.

## Yang diimplementasikan

- `album_visuals.py`: factory dan validasi property untuk `song_cover`, `vinyl`, `playlist_visual`, `progress`, dan `song_time`.
- `editor_session.py`: command-backed add actions untuk seluruh visual S06; Progress + Song Time dibuat sebagai satu transaksi undo.
- `preview_scene.py`: proxy canvas untuk cover aktif, vinyl berputar, playlist highlight, progress, dan elapsed/total time.
- `render_graph.py`: render nyata dynamic cover by `song_id`, vinyl prosedural transparan, playlist visual paging/highlight, progress per-song/per-album, dan waktu lagu/album.
- `property_inspector.py`: kontrol editable untuk fit cover, kecepatan/warna vinyl, opsi playlist, serta mode/warna progress dan time.
- `responsive_workspace.py`: tombol `+ Cover`, `+ Vinyl`, `+ Playlist`, `+ Progress`.
- `tests/test_editor_v2_s06_album_visuals.py`: real FFmpeg render, Accurate Preview, album mode, dan pixel proof bahwa cover berubah mengikuti lagu aktif.

## Gate

Lihat `docs/S06_ACCEPTANCE.md`. Branch ini belum boleh merge sebelum full pytest, real FFmpeg, Windows PyInstaller onedir, portable ZIP, dan artifact upload hijau pada PR head yang sama.