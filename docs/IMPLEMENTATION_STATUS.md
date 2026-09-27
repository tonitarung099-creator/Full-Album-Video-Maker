# Implementasi MASTER PLAN Astra — Status SOL

## Baseline S00

- Baseline: `main` @ `6ac77f197a4161cd108678d936c84f983e53e1ba`.
- Bootstrap aktif masih memakai urutan patch runtime dari `main.py`: playlist, Gemini schema compatibility, playlist hardening, visual feature, engine hardening, source integrity, UI hardening, atomic bundle, render lifecycle, dirty state, async import.
- Tidak ditemukan bukti workflow CI untuk commit baseline melalui GitHub Actions, sehingga status suite lama **tidak diklaim pass** pada tahap ini.
- Build Windows belum dapat dijalankan dari lingkungan SOL ini; verifikasi portable tetap gate S12.
- Keputusan: editor v2 dibangun sebagai modul domain eksplisit tanpa monkey patch baru. Jalur legacy tidak diganti pada S01.

## S01 — Domain v2 / migrasi / command stack

Status: implementasi fondasi.

Yang ditambahkan:

- `editor_models.py`: ProjectDocument schema v2, UUID stabil, tick integer 240000/s, asset/song/track/layer/time binding.
- `project_migrations.py`: deteksi Project v1 / TimelinePlan v1 / Project v2 dan migrasi Project v1 tanpa menimpa file lama.
- `editor_commands.py`: command domain dan inverse command untuk undo/redo.
- `editor_controller.py`: transaksi atomik, expected revision, undo/redo, dirty checkpoint berbasis content signature.
- `timeline_resolver.py`: playlist packed dan binding absolute/album/song/song_range.
- `project_repository.py`: repository load/save v2 atomik + dispatch format terpisah agar UI legacy belum berubah sebelum slice v2 siap.
- `tests/test_editor_v2_domain.py`: round-trip kosong, future schema, migrasi duplicate song, semantics active playlist legacy, rollback batch, revision stale, undo clean, song-range setelah reorder.

Batas tahap ini:

- UI legacy belum membuka ProjectDocument v2; integrasi UI dilakukan setelah slice S02 terbukti.
- Timeline free mode belum diaktifkan.
- TimelinePlan v1 dikenali tetapi belum diimpor menjadi dokumen editor v2.
- Renderer v2 belum dibuat; itu pekerjaan S02 berikutnya.
