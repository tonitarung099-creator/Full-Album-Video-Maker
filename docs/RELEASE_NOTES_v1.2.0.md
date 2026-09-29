# Full Album Maker v1.2.0

Feature release di atas stable v1.1.0. Fokus utama: mengaktifkan **Circular Spectrum** yang sejak S05 sengaja ditunda sampai renderer, parity, performa, cancel safety, dan packaging dapat dibuktikan.

## Fitur baru — Circular Spectrum

- style baru `circular_spectrum` pada layer Spectrum canonical;
- preset baru **Circular Neon**;
- kontrol **Radius Dalam** (`inner_ratio`) 0.15..0.85 di Property Inspector;
- renderer nyata memakai audio `showfreqs` lalu polar remap FFmpeg `geq` berbasis `atan2/hypot`;
- area tengah ring transparan sehingga cover/background tetap terlihat;
- color, sensitivity, frequency scale, amplitude scale, opacity, transform, dan rotation tetap editable;
- proxy radial ringan tersedia di canvas editor untuk interaksi cepat;
- Preview Akurat dan final render tetap memakai `FFmpegV2Compiler` yang sama.

## Performa dan keamanan render

Circular mapping tidak dijalankan pada resolusi akhir tanpa batas. Polar remap dibatasi maksimal **512×512** pixel internal, kemudian di-scale/pad ke ukuran box layer. Ini menjaga biaya `atan2/hypot` tetap bounded pada proyek 1080p/4K.

Sensitivity/gain Circular Spectrum hanya diterapkan pada branch audio visualizer hasil `asplit` dan tidak mengubah master audio final. Cancel sebelum publish tetap memakai transactional render service, sehingga output lama dipertahankan bila render dibatalkan.

## Kompatibilitas

- project schema tetap versi 2;
- tidak ada layer type baru—Circular Spectrum tetap `type="spectrum"` dengan style property baru;
- project v1.1.0 tetap dapat dibuka tanpa migrasi;
- seluruh template dan style spectrum lama tetap dipertahankan.

## Pipeline Windows

v1.2.0 mempertahankan hardening release sebelumnya:

- Windows portable multi-file / PyInstaller onedir;
- FFmpeg dipin melalui immutable release asset ID + SHA-256;
- GitHub Actions Node 24 dipin full commit SHA;
- regression + real FFmpeg wajib lulus;
- ZIP versi + `SHA256SUMS.txt` wajib dibuat dan diverifikasi;
- isolated portable smoke berjalan tanpa Python/FFmpeg global dan tanpa API key;
- GitHub Release hanya dipublikasikan setelah gate push `main` sukses.

## Batasan

- Circular Spectrum menggunakan satu ring frequency visualizer; multi-ring/3D shader belum termasuk v1.2.0.
- CI tidak melakukan full encode album tiga jam; stress 3 jam tetap menguji model/resolver/render graph dan real FFmpeg diuji melalui render pendek terukur.
