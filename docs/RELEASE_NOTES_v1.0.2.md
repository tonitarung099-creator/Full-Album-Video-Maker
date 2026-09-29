# Full Album Maker v1.0.2

Patch maintenance untuk Full Album Maker v1.0.1. Tidak ada perubahan format project, timeline, template, atau workflow editing pengguna.

## Perubahan

- GitHub Actions release pipeline dipindahkan dari action berbasis Node.js 20 ke action resmi berbasis Node.js 24.
- `actions/checkout` diperbarui ke v7.0.1 dan dipin ke full commit SHA `3d3c42e5aac5ba805825da76410c181273ba90b1`.
- `actions/setup-python` diperbarui ke v7.0.0 dan dipin ke full commit SHA `5fda3b95a4ea91299a34e894583c3862153e4b97`.
- `actions/upload-artifact` diperbarui ke v7.0.1 dan dipin ke full commit SHA `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.
- Regression gate baru memastikan workflow tidak kembali menggunakan tiga SHA action lama berbasis Node.js 20.
- Pin FFmpeg immutable, SHA-256 ZIP release, isolated portable smoke, dan seluruh gate v1.0.1 tetap dipertahankan.

## Alasan patch

Workflow v1.0.1 masih mengeluarkan peringatan bahwa action berbasis Node.js 20 sudah deprecated dan dipaksa berjalan pada Node.js 24 oleh runner GitHub. v1.0.2 menghilangkan ketergantungan pada compatibility fallback tersebut dengan memakai release action resmi yang memang mendeklarasikan runtime Node.js 24.

## Portable Windows

Paket resmi setelah gate `main` lulus:

`Full-Album-Maker-v1.0.2-Windows-Portable.zip`

File integritas:

`SHA256SUMS.txt`

Verifikasi di PowerShell:

```powershell
Get-FileHash .\Full-Album-Maker-v1.0.2-Windows-Portable.zip -Algorithm SHA256
```

Nilai hasil harus sama dengan nilai yang tercatat di `SHA256SUMS.txt`.

## Kompatibilitas

v1.0.2 hanya melakukan release-pipeline hardening. Perilaku aplikasi, schema project, timeline, template, renderer, preview, AI editor, dan format output tetap kompatibel dengan v1.0.1.

## Batasan yang tetap berlaku

- Circular Spectrum tetap ditunda sampai gate packaging, performa, preview/render parity, dan cancel memenuhi standar release.
- CI tidak melakukan full encode album tiga jam; stress tiga jam tetap dilakukan pada model/resolver/render-plan/graph, sedangkan encoder diverifikasi dengan real FFmpeg render yang lebih pendek.
- Aksi Gemini memerlukan API key; editing manual, template, preview, dan render tetap dapat digunakan tanpa AI.
