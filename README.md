# Full Album Maker

Aplikasi Windows portable untuk membuat video **full album YouTube** dari footage video + banyak file audio.

> Status: fase pengembangan awal. Fondasi desktop, FFmpeg render engine, dan Gemini Agent sedang dibangun.

## Target utama

- Import satu atau banyak footage video.
- Import banyak MP3/WAV/FLAC dan susun urutannya.
- Hitung otomatis durasi album.
- Slow motion manual atau otomatis agar footage mendekati durasi album.
- Loop / ping-pong bila footage masih kurang.
- Render H.264/H.265 1080p, 1440p, atau 4K melalui FFmpeg.
- Buat YouTube chapters / tracklist otomatis.
- Gemini Agent dengan pool hingga 100 auth/API key, failover, cooldown, dan health status.
- Tetap bisa dipakai manual tanpa AI/internet.
- Distribusi akhir: ZIP portable multi-file, tanpa installer dan tanpa hak admin.

## Keamanan API key

API key **tidak pernah disimpan di source code atau GitHub**. Pada Windows, key disimpan lokal menggunakan Windows DPAPI.

## Lisensi

MIT. Dependensi pihak ketiga tetap mengikuti lisensinya masing-masing.
