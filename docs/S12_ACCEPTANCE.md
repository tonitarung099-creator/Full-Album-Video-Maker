# S12 — Performa Panjang, Regresi, dan Windows Portable

S12 adalah gate rilis, bukan milestone fitur visual baru. Tujuannya memastikan
fitur S01–S11 tetap benar pada proyek panjang dan hasil Windows portable benar-
benar mandiri setelah ZIP diekstrak.

## Kontrak performa panjang

Gate sintetis utama memakai **200 lagu x 54 detik = 10.800 detik (3 jam)**.
Yang wajib dibuktikan untuk mode Packed dan Free:

- `ProjectDocument` valid dan resolver menghasilkan tepat 200 lagu;
- durasi resolved tepat 3 jam;
- resolver Free tidak kembali ke scan overlap O(n²);
- render plan/graph dapat dikompilasi tanpa membuat output 3 jam;
- filter graph panjang dipindahkan ke file melalui sintaks FFmpeg `-/filter_complex`;
- command line Windows hasil compile berada di bawah guard S12;
- Packed masih memakai concat audio rapat;
- Free masih memakai silence base + explicit mix/crossfade contract S11.

Batas performa test resolver sengaja longgar (`< 2 s`) agar menjadi regression
guard, bukan benchmark hardware CI yang rapuh.

## Real FFmpeg gates

Selain stress compile 3 jam, suite wajib melakukan render pendek dengan FFmpeg
nyata untuk membuktikan:

- sintaks option-file `-/filter_complex` diterima oleh binary FFmpeg yang dipin;
- regression render S01–S11 tetap lulus;
- Free Timeline gap/silence/crossfade/spectrum parity tetap lulus.

**CI tidak melakukan full encode video 3 jam.** Itu akan membuang resource tanpa
menambah banyak bukti untuk struktur graph. Stress 3 jam dilakukan pada model,
resolver, render plan, graph, dan batas command line; correctness encoder diuji
melalui real render pendek.

## Reproducible Windows build inputs

Release workflow harus:

- memakai runner `windows-2025`;
- memakai Python `3.12.10`;
- memasang dependency build dari `build/requirements-windows.lock`;
- pin action GitHub ke commit SHA;
- memverifikasi SHA-256 FFmpeg sebelum ekstraksi;
- mengambil Noto Sans dari commit Google Fonts immutable;
- menyertakan FFmpeg/ffprobe, font + OFL, license/notices, assets, data/temp/output,
  dan `CAPABILITIES.json` ke folder portable.

## Extracted ZIP smoke

Gate portable harus menjalankan **ZIP yang sudah dibuat**, bukan `dist/` mentah.
ZIP diekstrak ke path Windows yang mengandung spasi, Unicode, dan apostrof.
Sebelum menjalankan EXE:

- `GEMINI_API_KEY` dan `GOOGLE_API_KEY` dihapus;
- `PYTHONHOME` dan `PYTHONPATH` dihapus;
- `PATH` dibatasi ke direktori sistem Windows;
- global `python` dan `ffmpeg` wajib tidak ditemukan dari PATH.

`Full Album Maker.exe --portable-smoke` kemudian wajib:

1. menemukan FFmpeg/ffprobe di dalam folder portable;
2. membuat source audio pendek;
3. merender MP4 melalui compiler aplikasi;
4. memverifikasi dengan ffprobe bahwa output mempunyai **audio + video**;
5. membuat jendela utama Qt dan memproses event tanpa crash;
6. menulis `temp/portable-smoke.json` dengan `ok=true` dan tanpa API key.

## Capability report dan keterbatasan yang wajib jujur

`CAPABILITIES.json` harus menyatakan bahwa manual edit/template/preview/render
tidak memerlukan API key atau instalasi Python/FFmpeg global. AI tetap opsional
dan membutuhkan provider key hanya untuk aksi AI.

Keterbatasan rilis S12:

- full encode 3 jam tidak dijalankan di CI;
- custom `font_path` yang dipilih user tidak otomatis disalin/diembed; portable
  menyediakan Noto Sans sebagai fallback deterministic;
- performance gate 200 lagu mengukur resolve + compile safety, sedangkan real
  encoder correctness diverifikasi dengan render pendek.

## Definition of Done S12

S12 baru boleh merge bila exact head SHA PR memenuhi seluruh berikut:

- seluruh pytest hijau;
- gate 200 lagu/3 jam Packed + Free hijau;
- real FFmpeg option-file filter graph hijau;
- semua regression S01–S11 hijau;
- PyInstaller onedir hijau;
- portable ZIP berhasil dibuat;
- extracted-ZIP smoke tanpa Python/FFmpeg global dan tanpa API key hijau;
- audio + video output portable terverifikasi;
- artifact berhasil di-upload dan digest dicatat;
- commit hasil merge di `main` mengulang workflow yang sama dengan sukses.
