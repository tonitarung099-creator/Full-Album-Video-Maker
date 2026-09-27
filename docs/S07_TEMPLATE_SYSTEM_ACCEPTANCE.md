# S07 — Template System Acceptance

S07 dinyatakan selesai hanya jika seluruh poin ini hijau pada head PR yang sama.

## Fitur

- Tersedia empat template awal: Spotify Clean, Vinyl Nostalgia, Minimal Spectrum, Viral Full Album.
- Satu klik template membuat cover dinamis, vinyl, playlist visual, spectrum, judul lagu dinamis, progress, dan waktu.
- Semua hasil template tetap berupa Layer biasa dan dapat diedit setelah diterapkan.
- Mengganti template hanya mengganti layer `origin=template`; layer manual tidak dihapus atau diubah.
- Penerapan template adalah satu transaksi undo/redo.
- ProjectDocument menyimpan `editor_defaults.template_id` dan setiap layer template menyimpan `properties.template_id`.
- Preview Akurat dan final render tetap memakai compiler FFmpeg yang sama.

## Gate otomatis

- Catalog/factory test untuk semua template dan semua tipe layer.
- Preserve manual layer + replace previous template + single-undo test.
- UI selector test pada `ResponsiveEditorWorkspace`.
- Real FFmpeg render untuk keempat template, termasuk stream video + audio.
- Seluruh regression S01–S06 tetap hijau.
- Windows PyInstaller onedir, bundled FFmpeg, portable ZIP, dan artifact upload hijau.

## Batas S07

- S07 adalah preset layout editable, bukan format proyek baru.
- Template kustom buatan pengguna/export-import template dapat ditambahkan pada tahap berikutnya.
- Assignment massal cover per lagu tetap pekerjaan terpisah dari template layout.
