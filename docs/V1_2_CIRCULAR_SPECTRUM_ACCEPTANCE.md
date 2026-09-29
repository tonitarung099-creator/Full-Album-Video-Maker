# Full Album Maker v1.2.0 — Circular Spectrum Acceptance

## Tujuan

v1.2.0 mengaktifkan Circular Spectrum yang sejak S05 sengaja ditunda sampai renderer, preview/render parity, performa, packaging, dan cancel safety dapat dibuktikan.

## Kontrak fitur

1. Circular Spectrum tetap menggunakan layer canonical `type="spectrum"`; tidak dibuat layer type baru.
2. Style ID resmi: `circular_spectrum` dengan preset `circular_neon`.
3. Sumber audio tetap memakai branch audio visualizer hasil `asplit`; sensitivity/gain Circular Spectrum tidak boleh mengubah master audio `[aout]`.
4. Renderer memakai FFmpeg `showfreqs` sebagai sumber energi frekuensi, lalu remap polar `geq` berbasis `atan2/hypot`.
5. Area tengah ring harus transparan dan ukuran radial dikontrol oleh `inner_ratio` 0.15..0.85.
6. Transform, opacity, rotation, color, frequency scale, amplitude scale, dan sensitivity tetap mengikuti layer spectrum biasa.
7. Preview Akurat wajib memakai `FFmpegV2Compiler` yang sama dengan final render.
8. Canvas editor boleh memakai proxy radial ringan; proxy tidak menjadi sumber final output.
9. Biaya polar remap dibatasi maksimal 512×512 pixel internal sebelum hasil di-scale/pad ke box layer. Layer 1080p/4K tidak boleh memaksa `geq` berjalan pada ukuran final penuh.
10. Cancel sebelum publish harus tetap mempertahankan output lama byte-for-byte melalui transactional render service yang sudah ada.
11. Tidak ada schema migration baru; properties Circular Spectrum tersimpan dalam `Layer.properties` schema v2 yang sudah fleksibel.

## Gate regression

- registry style/preset dan validasi `inner_ratio`;
- unsupported future spectrum style tetap fail-closed;
- bounded internal polar resolution untuk layer besar;
- compiler graph memuat `showfreqs`, `atan2`, `hypot`, `geq`, transparency, rotation, dan audio split tanpa gain pada `[aout]`;
- Property Inspector hanya menampilkan kontrol `Radius Dalam` untuk Circular Spectrum;
- real FFmpeg render Circular Spectrum pada background terang;
- area tengah frame preview tetap background, sedangkan ring memiliki pixel warna visualizer;
- Preview Akurat vs frame final pada timestamp sama memenuhi gate PSNR;
- cancel safety mempertahankan output lama;
- seluruh regression v1.1.0 tetap hijau.

## Gate release

PR hanya boleh merge bila exact head lulus seluruh pytest + real FFmpeg, PyInstaller Windows onedir, versioned portable ZIP, `SHA256SUMS.txt`, isolated portable smoke, dan upload artifact. Push `main` harus mengulang gate yang sama sebelum GitHub Release `v1.2.0` dipublikasikan.
