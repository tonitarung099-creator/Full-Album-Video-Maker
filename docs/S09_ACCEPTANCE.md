# S09 Acceptance — Integrasi AI Editor

S09 mengikuti kontrak MASTER PLAN Astra bagian 16. Gemini tetap hanya penerjemah bahasa manusia menjadi intent; seluruh validasi dan mutasi dilakukan engine lokal.

## Kontrak

- Gemini/key pool existing dipertahankan; tidak menambah provider berbayar atau key di repo.
- Context editor-v2 bounded: ringkasan proyek, selected layer, kandidat lagu/layer/template. Locator/path media, API key, waveform dan cache tidak dikirim.
- Intent editor membawa envelope lokal: `project_id`, `expected_revision`, `action_id` idempotency.
- UUID target harus berasal dari context atau hasil resolusi lokal; unknown/stale ID gagal tanpa mutasi.
- Query nama yang cocok ke lebih dari satu song/layer menghasilkan ambiguity candidates dan tidak boleh ditebak.
- Semua edit dalam satu respons AI disimulasikan pada clone lalu di-dispatch sebagai satu transaksi `EditorController`: satu respons edit = satu Undo.
- Respons duplikat dengan action id yang sama tidak diterapkan dua kali.
- `save_template` adalah side effect setelah desain commit. Jika penyimpanan gagal, desain valid tetap ada dan status harus menjelaskan kegagalan side effect.
- `render_project` hanya boleh muncul bila pengguna eksplisit meminta render. Render dipanggil setelah edit berhasil commit.
- Workflow manual, template lokal, preview dan render tidak bergantung pada internet/API key.

## Intent S09

- `add_text`, `edit_text`, `move_layer`, `resize_layer`, `delete_layer`, `duplicate_layer`
- `add_spectrum`, `set_spectrum_style`, `set_spectrum_range`
- `add_playlist_visual`, `set_playlist_style`
- `add_cover`, `set_cover_style`, `add_progress_bar`
- `apply_template`, `save_template`
- `move_song`, `reorder_playlist`, `remove_song`
- `set_background`, `show_layer`, `hide_layer`
- `render_project` sebagai side effect eksplisit pasca-commit

## Gate

- Mock Gemini deterministic; tidak membutuhkan live key pada CI.
- Context tidak mengandung locator/path rahasia dan terpotong pada proyek besar.
- Salah `project_id` atau stale revision: 0 mutasi.
- Invalid style/range/size/ID: 0 mutasi termasuk aksi valid yang mendahuluinya pada batch sama.
- Ambiguity nama lagu/layer: tampil kandidat, 0 mutasi.
- Multi-action sukses menaikkan revision sekali dan Undo sekali mengembalikan state sebelum batch.
- Duplicate response idempotent.
- Render hanya explicit.
- Save-template failure tidak rollback desain yang sudah valid.
- Real FFmpeg render tetap berjalan tanpa membuat/menyediakan Gemini key.
- Seluruh regression S01–S08, PyInstaller onedir dan ZIP portable harus tetap hijau.