# Status Implementasi S04

Tahap: S04 — Timeline Interaktif dan Preview Canvas.

Baseline S04: `main` @ `3ec5b93debe5c9bfcd8de7c6332f852a5d436aec`.

Implementasi branch ini memindahkan surface tengah aplikasi ke editor v2 eksplisit (`EditorMainWindow` + `EditorWorkspace`) sambil mempertahankan panel Media dan AI legacy yang sudah terbukti. Media legacy disinkronkan ke library v2 dengan ID stabil; edit timeline/layer selanjutnya memakai `ProjectDocument` v2 dan command stack S01.

Komponen utama:

- `editor_interaction_commands.py`: transform, opacity, visible/lock, start/duration, track visible/lock yang undoable.
- `editor_session.py`: selection/playhead/zoom/snap sebagai state editor non-persisted, command dispatch dan snap boundaries.
- `timeline_editor.py`: ruler, lanes, scroll, zoom, playhead, select/move/trim, show/lock track.
- `preview_scene.py`: canvas interaktif dan selection/transform gesture.
- `property_inspector.py`: properties berbasis command dan capability UI sesuai parity render.
- `editor_workspace.py`: integrasi timeline, preview, inspector, playlist, undo/redo, shortcut, visual playback, accurate preview dan render v2.
- `legacy_sync_v2.py`: sinkron Media legacy ke v2 tanpa menghapus edit/playlist v2.
- `editor_window.py`: main window eksplisit; panel AI tetap di kanan, tanpa monkey patch editor baru.
- `render_graph.py`: background x/y/size/rotation/opacity mengikuti ProjectDocument saat preview akurat/final render.

Workflow Windows diubah agar berjalan pada pull request ke `main`, sehingga S04 harus lolos pytest, real FFmpeg render, PyInstaller onedir, bundling dan portable ZIP sebelum merge.

Status final S04 hanya akan dinyatakan selesai setelah workflow PR berhasil. Spectrum/dynamic title/cover/playlist visual/progress bukan bagian S04 dan tetap masuk S05/S06.
