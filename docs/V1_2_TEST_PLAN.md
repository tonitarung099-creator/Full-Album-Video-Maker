# v1.2.0 Circular Spectrum — Test Plan

Exact branch head harus melewati gate berikut sebelum merge:

1. unit/schema: style, preset, inner radius, unsupported style fail-closed;
2. compiler graph: audio asplit, visual gain only, polar atan2/hypot/geq, transparency, transform/rotation;
3. UI: kontrol Radius Dalam hanya untuk Circular Spectrum;
4. real FFmpeg: Circular render menghasilkan MP4 valid dan Preview Akurat menghasilkan PNG;
5. visual: pusat ring transparan pada background terang dan ring memiliki pixel cyan nyata;
6. parity: Preview Akurat vs frame final timestamp sama memenuhi PSNR minimum;
7. performance bound: layer 4K tetap memakai polar remap internal maksimal 512×512;
8. cancel: output lama tidak dipublikasikan/ditimpa bila render dibatalkan;
9. regression: seluruh test v1.1.0 tetap hijau;
10. Windows release: PyInstaller onedir, FFmpeg bundle, ZIP versi, SHA256SUMS, isolated portable smoke, artifact upload;
11. PR tidak boleh publish GitHub Release; hanya push main hijau yang boleh publish v1.2.0.
