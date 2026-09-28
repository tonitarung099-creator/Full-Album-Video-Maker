# S10 Acceptance — Preset Lanjutan dan 10 Template

S10 mengikuti MASTER PLAN editor/template/spectrum: lima preset spectrum wajib tetap nyata, dekorasi/overlay harus bounded dan transparan, 10 template final harus menghasilkan layer editable, thumbnail harus berasal dari compiler render aktual, dan Circular Spectrum tidak boleh dipalsukan sebelum spike teknis lulus.

## Katalog final

1. Spotify Clean
2. Cafe Acoustic
3. Viral Full Album
4. Vinyl Nostalgia
5. Neon Spectrum
6. Romantic Bokeh
7. Dark Cinematic
8. Photo Album
9. Cassette Retro
10. Music Channel Pro

`minimal_spectrum` dari S07 tetap load/apply compatible sebagai legacy ID, tetapi tidak muncul sebagai template publik ke-11.

## Preset spectrum yang wajib

- Mirror
- Neon Bars
- Minimal Bars
- Bass Bars
- Thin Line

Core tetap memakai FFmpeg `showfreqs` / `showwaves`; tidak ada kontrol FFT/circular palsu.

## Overlay/dekorasi S10

- vignette
- bokeh
- light leak
- particles
- film grain
- VHS noise
- glow

Semua effect memakai properties tervalidasi (`intensity`, `speed`, `count`, `seed`, `color`). `count` dibatasi maksimal 12 dan seed disimpan di project agar Preview Akurat dan final render deterministik. Effect memakai source RGBA transparan dan normal alpha overlay; tidak ada frame hitam sebagai pseudo-transparency.

Effect prosedural dengan `mode=effect` juga dianggap portabel oleh template kustom S08: properties dinormalisasi dan seed dipertahankan tanpa asset/path eksternal. Background `mode=asset` tetap ditolak agar ekspor template tidak membawa referensi project yang stale.

## Thumbnail dan preview card

`render_template_thumbnail()` membuat clone project, menerapkan template pada clone, memilih frame di tengah lagu pertama, lalu memakai `FFmpegV2Compiler.compile_frame()` yang sama dengan Preview Akurat/final render. Source project tidak boleh berubah.

`S10EditorWorkspace` menampilkan card preview 16:9 untuk template built-in yang sedang dipilih. Render card berjalan asynchronous, cache-key memakai content signature proyek + template ID, dan hasil thread yang stale diabaikan bila pilihan sudah berubah. Jika belum ada lagu, UI meminta pengguna menambahkan lagu; template kustom tetap memakai Preview Akurat setelah apply.

## Circular Spectrum

Status S10: **belum tersedia**. Circular baru boleh diaktifkan setelah spike FFT/circular yang terukur membuktikan:

- packaging portable aman,
- preview/render parity,
- performa panjang dapat diterima,
- cancel tidak bocor proses/resource.

Tidak ada preset bernama circular di registry aktif.

## Gate CI

- katalog publik tepat 10 template;
- `minimal_spectrum` legacy tetap dapat dibuka tetapi tersembunyi dari katalog;
- semua template schema/layer valid dan manual layer tetap dipertahankan saat apply/undo;
- semua 10 template real FFmpeg render menghasilkan video + audio;
- semua 10 template menghasilkan PNG thumbnail via compiler aktual;
- preview card S10 terpasang dan mengikuti template terpilih tanpa memaksa FFmpeg di UI unit test;
- glow/light leak/particles dirender pada canvas terang dan tidak boleh menjadi opaque black box;
- effect unknown/unbounded ditolak;
- procedural effect bertahan pada custom-template roundtrip tanpa asset eksternal;
- background image/video project-specific tetap ditolak dari template kustom portabel;
- Circular Spectrum explicit deferred;
- seluruh regression S01–S09 tetap hijau;
- Windows PyInstaller onedir + portable ZIP tetap hijau.