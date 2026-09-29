# Full Album Maker v1.0.1

Patch maintenance untuk rilis stabil Full Album Maker v1.0.0.

## Perubahan

- Menghapus penggunaan constructor `QMouseEvent` yang deprecated pada regression test preview Editor V2 agar suite tetap bersih pada PySide6 6.11.x dan lebih siap terhadap versi Qt/PySide berikutnya.
- Build Windows sekarang menghasilkan `SHA256SUMS.txt` berdasarkan ZIP portable yang benar-benar baru dibuat.
- Build lokal dan GitHub Actions memverifikasi isi `SHA256SUMS.txt` sebelum release dilanjutkan.
- Artifact GitHub Actions membawa ZIP portable dan file checksum.
- GitHub Release membawa dua asset resmi: ZIP portable dan `SHA256SUMS.txt`.
- README menambahkan cara verifikasi checksum di PowerShell.

## Portable Windows

Paket resmi:

`Full-Album-Maker-v1.0.1-Windows-Portable.zip`

File integritas:

`SHA256SUMS.txt`

Pengguna dapat menghitung checksum dengan:

```powershell
Get-FileHash .\Full-Album-Maker-v1.0.1-Windows-Portable.zip -Algorithm SHA256
```

Nilai hasil harus sama dengan nilai di `SHA256SUMS.txt` untuk nama ZIP tersebut.

## Validasi release

Release hanya dipublikasikan setelah workflow Windows pada `main` lulus seluruh gate yang sama dengan v1.0.0, ditambah gate checksum:

- regression suite lengkap;
- real FFmpeg render tests;
- stress resolver/render graph 200 lagu × 54 detik = 3 jam;
- PyInstaller Windows onedir;
- pinned FFmpeg/font validation;
- pembuatan ZIP portable versi;
- pembuatan dan verifikasi `SHA256SUMS.txt`;
- isolated portable smoke tanpa Python/FFmpeg global dan tanpa Gemini/Google API key;
- verifikasi output audio + video;
- verifikasi title GUI frozen sesuai versi release.

## Kompatibilitas

Tidak ada perubahan format project, timeline, template, atau workflow pengguna dibanding v1.0.0. v1.0.1 adalah patch maintenance dan release-integrity hardening.

## Batasan yang diketahui

- Circular Spectrum tetap ditunda sampai gate packaging, performa, preview/render parity, dan cancel memenuhi standar release.
- CI tidak melakukan full encode album tiga jam; stress 3 jam tetap dilakukan pada model/resolver/render-plan/graph dan encoder diverifikasi dengan real FFmpeg render yang lebih pendek.
- Aksi Gemini memerlukan API key; editing manual, template, preview, dan render tetap dapat digunakan tanpa AI.

## Lisensi

Kode Full Album Maker menggunakan lisensi MIT. Dependensi dan asset pihak ketiga mengikuti lisensi masing-masing; lihat `THIRD_PARTY_NOTICES.md`.
