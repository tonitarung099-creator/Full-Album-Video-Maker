from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .controller import ProjectController
from .key_pool import GeminiKeyPool


SYSTEM = """Kamu adalah Gemini Agent di aplikasi Full Album Maker.
Bahasa utama: Indonesia.

Tujuanmu adalah membantu pengguna membuat video full album YouTube dari footage video + banyak lagu.
Kamu BUKAN editor kreatif umum. Jangan mengaku melihat isi visual footage karena tool saat ini hanya memberi nama file, durasi, urutan, dan setting proyek.

Aturan:
- Sebelum memberi rekomendasi yang bergantung pada proyek, gunakan project_summary atau validate_project.
- Utamakan hasil stabil dan sederhana: H.264, 30 fps, audio AAC berkualitas tinggi, auto-speed, minimum slowmo 0.5x, loop otomatis bila footage kurang.
- Jangan memperlambat di bawah 0.35x kecuali pengguna meminta eksplisit.
- Audio tidak pernah ikut slow-motion.
- Jangan mengubah urutan lagu kecuali pengguna meminta.
- Jika pengguna meminta "optimalkan", gunakan optimize_youtube lalu jelaskan hasilnya.
- Jika ada error validasi, jelaskan yang harus diperbaiki sebelum render.
- Jangan mengarang file, nama lagu, durasi, visual, atau hasil render.
- Setelah tool selesai, ringkas perubahan yang benar-benar diterapkan.
"""

TOOLS = [
    {
        "name": "project_summary",
        "description": "Membaca kondisi proyek lengkap: footage, tracklist, durasi, speed, loop, setting, dan validasi.",
    },
    {
        "name": "validate_project",
        "description": "Memeriksa error dan warning proyek sebelum render.",
    },
    {
        "name": "optimize_youtube",
        "description": "Menerapkan profil aman untuk full album YouTube: kualitas output, H.264, 30 fps, audio 320k, auto speed min 0.5x, loop otomatis.",
        "parameters": {
            "type": "object",
            "properties": {
                "quality": {
                    "type": "string",
                    "enum": ["1080p", "1440p", "4k"],
                }
            },
        },
    },
    {
        "name": "set_slowmo",
        "description": "Atur speed footage manual. 0.5 berarti setengah kecepatan.",
        "parameters": {
            "type": "object",
            "properties": {"speed": {"type": "number"}},
            "required": ["speed"],
        },
    },
    {
        "name": "set_auto_speed",
        "description": "Aktifkan pencocokan slow-motion otomatis; min_speed adalah batas slowmo terendah.",
        "parameters": {
            "type": "object",
            "properties": {"min_speed": {"type": "number"}},
        },
    },
    {
        "name": "set_loop_mode",
        "description": "Pilih cara memperpanjang footage bila durasinya kurang.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["auto", "loop", "pingpong", "none"],
                }
            },
            "required": ["mode"],
        },
    },
    {
        "name": "set_resolution",
        "description": "Atur resolusi output secara manual.",
        "parameters": {
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["width", "height"],
        },
    },
    {
        "name": "set_fps",
        "description": "Atur FPS output.",
        "parameters": {
            "type": "object",
            "properties": {
                "fps": {"type": "integer", "enum": [24, 25, 30, 50, 60]}
            },
            "required": ["fps"],
        },
    },
    {
        "name": "set_codec",
        "description": "Atur codec video.",
        "parameters": {
            "type": "object",
            "properties": {
                "codec": {"type": "string", "enum": ["h264", "h265"]}
            },
            "required": ["codec"],
        },
    },
    {
        "name": "set_quality",
        "description": "Atur bitrate video dan audio.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_bitrate": {
                    "type": "string",
                    "enum": ["6M", "8M", "12M", "20M", "30M", "45M", "60M"],
                },
                "audio_bitrate": {
                    "type": "string",
                    "enum": ["128k", "192k", "256k", "320k"],
                },
            },
        },
    },
    {
        "name": "sort_audio_by_name",
        "description": "Urutkan semua lagu berdasarkan nama file.",
    },
    {
        "name": "move_audio",
        "description": "Pindahkan lagu dari satu posisi ke posisi lain. Posisi dimulai dari 1.",
        "parameters": {
            "type": "object",
            "properties": {
                "from_position": {"type": "integer", "minimum": 1},
                "to_position": {"type": "integer", "minimum": 1},
            },
            "required": ["from_position", "to_position"],
        },
    },
]


class GeminiAgent:
    def __init__(
        self,
        pool: GeminiKeyPool,
        controller: ProjectController,
        model: str = "gemini-3.8-flash",
    ) -> None:
        self.pool = pool
        self.controller = controller
        self.model = model
        self.history: list[dict[str, Any]] = []

    def _url(self) -> str:
        model = quote(self.model.strip(), safe="-_.")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def reset(self) -> None:
        self.history.clear()

    def ask(self, text: str) -> str:
        history_start = len(self.history)
        self.history.append({"role": "user", "parts": [{"text": text}]})
        try:
            return self._run_turn()
        except Exception:
            del self.history[history_start:]
            raise

    def _run_turn(self) -> str:
        for _ in range(10):
            payload = {
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": self.history,
                "tools": [{"functionDeclarations": TOOLS}],
            }
            response = self.pool.request_json(self._url(), payload)
            candidates = response.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini tidak mengembalikan candidate.")

            content = candidates[0].get(
                "content",
                {"role": "model", "parts": []},
            )
            self.history.append(content)
            parts = content.get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]

            if not calls:
                texts = [p.get("text", "") for p in parts if p.get("text")]
                return "\n".join(texts).strip() or "Perubahan selesai."

            responses = []
            for call in calls:
                name = call.get("name", "")
                args = call.get("args") or {}
                try:
                    result = self.controller.execute(name, args)
                    body = {"ok": True, "result": result}
                except Exception as exc:
                    body = {"ok": False, "error": str(exc)}

                part = {
                    "functionResponse": {
                        "name": name,
                        "response": body,
                    }
                }
                if call.get("id"):
                    part["functionResponse"]["id"] = call["id"]
                responses.append(part)

            self.history.append({"role": "user", "parts": responses})

        raise RuntimeError("Gemini mencapai batas langkah tool untuk satu perintah.")
