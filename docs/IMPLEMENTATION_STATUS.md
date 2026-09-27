# Implementasi MASTER PLAN Astra — Status SOL

## Baseline S00

- Baseline awal: `main` @ `6ac77f197a4161cd108678d936c84f983e53e1ba`.
- Bootstrap aktif masih memakai urutan patch runtime dari `main.py`: playlist, Gemini schema compatibility, playlist hardening, visual feature, engine hardening, source integrity, UI hardening, atomic bundle, render lifecycle, dirty state, async import.
- Tidak ditemukan bukti workflow CI untuk commit baseline melalui GitHub Actions, sehingga status suite lama **tidak diklaim pass** pada tahap ini.
- Build Windows belum dapat dijalankan dari lingkungan SOL ini; verifikasi portable tetap gate S12.
- Keputusan: editor v2 dibangun sebagai modul domain eksplisit tanpa monkey patch baru. Jalur legacy tidak diganti sebelum slice v2 terbukti.

## S01 — Domain v2 / migrasi / command stack

Status: selesai sebagai fondasi dan telah digabung ke `main` melalui PR #19.

Yang ditambahkan:

- `editor_models.py`: ProjectDocument schema v2, UUID stabil, tick integer 240000/s, asset/song/track/layer/time binding.
- `project_migrations.py`: deteksi Project v1 / TimelinePlan v1 / Project v2 dan migrasi Project v1 tanpa menimpa file lama.
- `editor_commands.py`: command domain dan inverse command untuk undo/redo.
- `editor_controller.py`: transaksi atomik, expected revision, undo/redo, dirty checkpoint berbasis content signature.
- `timeline_resolver.py`: playlist packed dan binding absolute/album/song/song_range.
- `project_repository.py`: repository load/save v2 atomik + dispatch format terpisah agar UI legacy tidak diubah sebelum slice v2 siap.
- `tests/test_editor_v2_domain.py`: round-trip kosong, future schema, migrasi duplicate song, semantics active playlist legacy, rollback batch, revision stale, undo clean, song-range setelah reorder.

Bukti lokal S01: 10 test domain v2 lulus dan modul baru lolos `py_compile`.

## S02 — Background + text + real render + accurate preview

Status: slice render nyata telah diimplementasikan; integrasi UI legacy belum diaktifkan.

Yang ditambahkan:

- `render_plan.py`: snapshot RenderPlan v2 immutable terpisah dari ProjectDocument.
- `render_graph.py`: compiler FFmpeg murni untuk canvas solid, background solid/image/video, text timed, z-order, dan audio master 48 kHz stereo dari playlist packed.
- `render_service_v2.py`: snapshot render, subprocess cancellable, sidecar chapter/tracklist/Timeline_Final, dan publikasi memakai transactional bundle existing.
- `preview_service.py`: Preview Akurat satu frame menggunakan compiler komposisi yang sama dengan final render.
- `tests/test_editor_v2_render.py`: real FFmpeg smoke, preview parity, unsupported-layer fail-closed, serta proteksi output lama saat compile gagal/cancel.

Bukti lokal S02:

- total suite fondasi + S02: **15 passed**.
- real render: 2 WAV sintetis × 0,6 detik -> MP4 1,2 detik dengan stream video+audio.
- background solid + timed text benar-benar masuk hasil FFmpeg.
- Preview Akurat pada t=0,4 s dibanding frame final menghasilkan PSNR sekitar 55 dB (gate test minimum 40 dB).
- compile failure dan cancel sebelum publish mempertahankan output lama byte-for-byte.

Batas tahap ini:

- UI utama masih memakai jalur legacy; ProjectDocument v2 belum menjadi state aktif MainWindow.
- Text S02 memakai FFmpeg `drawtext` + `textfile`; font packaging/parity Windows akan diperketat sebelum rilis.
- Background image/video sudah dikompilasi tetapi smoke lokal utama tahap ini memakai background solid.
- Spectrum/cover/playlist visual/progress belum diaktifkan pada compiler v2; active layer yang belum didukung ditolak, bukan diabaikan.
- Timeline free mode belum diaktifkan.
- TimelinePlan v1 dikenali tetapi belum diimpor menjadi dokumen editor v2.
- Pengujian Windows portable belum dilakukan; tetap gate S12.
