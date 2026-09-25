# Arsitektur Full Album Maker

## Lapisan utama

1. UI desktop PySide6: impor footage/audio, pengaturan, log, dan panel Gemini Agent.
2. ProjectController: satu pintu perubahan state, dipakai tombol manual maupun Gemini.
3. Gemini Agent: function calling ke tool internal; tidak mengeksekusi shell bebas.
4. GeminiKeyPool: hingga 100 key, round-robin, cooldown 429/5xx, disable 401/403.
5. Windows DPAPI Vault: key disimpan terenkripsi untuk user Windows yang sama.
6. FFmpegRenderer: concat audio, normalisasi footage, slowmo, loop/ping-pong, render akhir.
7. Portable build: PyInstaller one-folder + ffmpeg/ffprobe di tools/ffmpeg.

## Prinsip keamanan

- Tidak ada API key di repository.
- Agent hanya boleh memanggil tool yang dideklarasikan.
- Agent tidak mendapat tool shell atau file-delete.
- Render manual tetap tersedia tanpa Gemini.
- Project state menjadi sumber kebenaran bersama UI dan agent.
