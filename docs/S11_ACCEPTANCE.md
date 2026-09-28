# S11 Acceptance — Free Timeline dan Opsi Lanjutan Terpisah

S11 mengikuti MASTER PLAN: mode rapat/packed tetap menjadi default dan validator lama tidak dimatikan. Free Timeline adalah mode opt-in dengan kontrak timing audio sendiri.

## Kontrak mode

### Packed

- perilaku S01–S10 tetap: lagu aktif disusun rapat sesuai urutan playlist;
- `crossfade_in_tick` tidak boleh aktif;
- compiler memakai graph concat lama agar regresi audio packed mudah dideteksi.

### Free

- setiap lagu aktif memiliki `free_start_tick` eksplisit;
- gap diizinkan dan dirender sebagai silence nyata;
- durasi album adalah `max(end_tick)` dari lagu aktif, bukan jumlah durasi lagu;
- overlap tanpa crossfade eksplisit ditolak;
- `crossfade_in_tick` harus sama persis dengan panjang overlap menuju lagu tersebut;
- crossfade harus lebih pendek dari kedua lagu;
- triple/ambiguous overlap ditolak.

## Conversion mode

- Packed -> Free mempertahankan posisi packed saat ini satu per satu, jadi mengaktifkan Free tidak mengubah suara/timing dengan sendirinya.
- Free -> Packed adalah compact conversion eksplisit: `free_start_tick` dan crossfade dibersihkan, kemudian lagu kembali rapat sesuai urutan playlist.
- Kedua arah merupakan command undoable; Undo harus mengembalikan timing sebelumnya.

## Render

`S11FFmpegCompiler` mempertahankan compiler S10 untuk visual. Pada Packed, graph S10 dikembalikan tanpa perubahan. Pada Free, hanya album-audio graph yang diganti:

- segmen audio diposisikan menurut start timeline;
- silent base finite menutup initial/internal gap;
- gain diterapkan per lagu;
- fade-in/fade-out hanya dibuat dari kontrak crossfade yang sudah lolos resolver;
- `amix` menghasilkan satu `album_audio` dengan durasi timeline;
- final audio dan spectrum memakai `album_audio` yang sama.

Preview Akurat, final render, spectrum, dan actual-render template thumbnail menggunakan compiler S11 yang sama.

## UI

- card S11 menyediakan pilihan `Packed` / `Free`;
- start dan crossfade lagu hanya editable pada Free;
- klik blok audio atau baris playlist memilih lagu;
- blok audio hanya dapat di-drag pada Free;
- drag yang membuat overlap tidak sah ditolak dan meminta crossfade;
- Snap tetap tersedia dan mengabaikan boundary lagu yang sedang digeser.

Gemini S09 tidak otomatis diberi tool timing-free pada S11. UI menyatakan ini secara eksplisit; tidak ada kemampuan AI palsu.

## Gate CI

- packed resolver tetap contiguous;
- Packed -> Free mempertahankan posisi;
- Free -> Packed compact dan Undo mengembalikan timing free;
- gap free valid dan memperpanjang album;
- overlap tanpa crossfade ditolak;
- mismatch crossfade ditolak;
- crossfade valid lolos;
- triple overlap ditolak;
- free timing/crossfade survive project roundtrip;
- real FFmpeg gap render mengandung silence pada area gap;
- real FFmpeg crossfade render berdurasi `max(end)`, bukan jumlah lagu;
- Packed compiler tetap mengandung concat graph lama;
- UI S11 default Packed dan timing control hanya aktif pada Free;
- seluruh regression S01–S10 tetap hijau;
- Windows PyInstaller onedir + portable ZIP tetap hijau.