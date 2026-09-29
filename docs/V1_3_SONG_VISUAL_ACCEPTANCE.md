# Full Album Maker v1.3.0 — Song Visual + Transition Acceptance

## Tujuan

v1.3.0 mengaktifkan `SongInstance.visual_asset_id` yang sudah ada sejak schema v2 menjadi workflow editor yang nyata: setiap lagu dapat memiliki foto/video sendiri, dengan motion foto dan transisi visual yang mengikuti timeline audio.

## Kontrak

1. Schema project tetap `2`; tidak ada migrasi baru.
2. Identitas assignment memakai stable `song_id` + `asset_id`.
3. Visual lagu hanya boleh berupa `image` atau `video`.
4. Tab `Visual Lagu` mendukung multi-select, assign, clear, dan auto-match exact-normalized.
5. Auto-match tidak melakukan fuzzy/AI guessing; duplicate song/visual key menjadi ambigu dan tidak diterapkan.
6. Layer dinamis `song_visual` memakai binding album dan full-canvas default, tetapi tetap layer biasa yang dapat hidup bersama background, cover, spectrum, title, playlist, dan overlay.
7. Foto mendukung motion: static, zoom in/out, pan left/right.
8. Video mendukung loop atau freeze frame.
9. Transisi: cut, fade, slide kiri, slide kanan; durasi 0..5 detik dan tidak boleh melebihi setengah durasi visual aktif.
10. Preview Akurat dan final render memakai `V13FFmpegCompiler` yang sama.
11. Existing S10/S11 visual/audio graph dikompilasi lebih dulu; Song Visual disisipkan sesudah base canvas dan sebelum overlay existing supaya spectrum/title/cover tetap di atas footage.
12. Free Timeline memakai event audio yang sudah resolved; gap tetap memperlihatkan background jika tidak ada visual aktif.
13. Final render melakukan preflight terhadap file `visual_asset_id` aktif, sehingga media hilang gagal sebelum FFmpeg publish output.

## Gate regression

- property validation dan batas transition;
- bulk assignment satu revision/satu Undo;
- exact auto-match + ambiguity fail-closed;
- graph slide/fade hadir di compiler tanpa menghapus audio graph;
- real FFmpeg dua foto berubah sesuai pergantian lagu;
- Preview Akurat pada lagu kedua menghasilkan visual yang sama secara semantik;
- real FFmpeg video loop berhasil dan freeze menggunakan frame tunggal;
- tab `Visual Lagu` tersedia di workspace produksi;
- seluruh regression v1.2.0 tetap hijau.

## Gate release Windows

PR hanya boleh merge jika exact head lulus seluruh pytest, real FFmpeg, PyInstaller onedir, versioned ZIP + SHA256SUMS, isolated portable smoke, dan artifact upload. GitHub Release v1.3.0 hanya boleh dipublikasikan setelah push `main` mengulang gate yang sama dengan sukses.
