# S05 Acceptance — Spectrum Core + Dynamic Song Title

## Scope

S05 berdiri di atas S02–S04 dan menambahkan visual audio nyata, judul/artist dinamis, serta motion/playback background tanpa membuat jalur state/render kedua.

## Spectrum core

- Style rilis aktif: `bars`, `spectrum_line`, `waveform`, `stereo_waveform`.
- `circular_spectrum` belum boleh selectable sampai ada proof-of-concept terpisah.
- Preset rilis: Minimal Bars, Neon Bars, Bass Bars, Thin Line, Mirror.
- Properties yang punya parity: transform, opacity, color, sensitivity/gain visual, frequency scale bila didukung, amplitude scale, mirror.
- Kontrol yang tidak didukung style harus disembunyikan, bukan dibiarkan aktif palsu.
- Banyak layer spectrum boleh aktif bersamaan; audio harus di-split untuk visualizer, bukan mengganti master audio.
- Sensitivity/gain visual tidak boleh mengubah audio final.
- Alpha visualizer harus memakai transparansi sehingga background terang/gelap tidak mendapat kotak hitam.

## Dynamic song title

- Layer `song_title` memakai metadata `SongInstance` berdasarkan `song_id`, bukan indeks playlist yang rapuh.
- Default template: `{title}\n{artist}`.
- Reorder playlist harus otomatis mengubah urutan judul tanpa membuat layer title baru.
- Binding album/song tetap diselesaikan oleh `TimelineResolver`.
- Preview Akurat dan final render harus memakai compiler yang sama.

## Background S05

- `playback`: `loop` atau `freeze` untuk background video.
- `motion`: `static`, `zoom_in`, `zoom_out`, `pan_left`, `pan_right`.
- Nilai unsupported harus fail-closed pada compiler.

## Preview

- Canvas editor boleh memakai proxy spectrum ringan agar interaksi tetap responsif.
- Tombol Preview Akurat wajib menjalankan `FFmpegV2Compiler.compile_frame` yang sama dengan render final.
- Accurate preview untuk spectrum harus tetap membutuhkan sumber audio nyata.

## Gate test

- Registry/preset dan unsupported circular style.
- Add spectrum/title + undo/redo + project persistence melalui schema v2.
- Dynamic title menghasilkan text file per `song_id`/event aktif.
- Audio split memastikan visual gain tidak diterapkan ke `[aout]`.
- `colorkey`/alpha chain hadir untuk visualizer.
- Real FFmpeg render: Bars, Spectrum Line, Waveform, Stereo Waveform.
- Real silence input tidak crash dan Accurate Preview tetap berhasil.
- Existing regression suite S01–S04 tetap hijau.
- Windows PyInstaller onedir + portable ZIP tetap berhasil.

## Definition of Done

S05 hanya boleh merge bila seluruh pytest, real FFmpeg render, PyInstaller onedir, bundling FFmpeg/notices, ZIP portable dan artifact upload lulus pada PR head yang sama.