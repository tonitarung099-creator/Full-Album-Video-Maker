from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from .agent_actions import AgentAction, AgentDecision
from .key_pool import GeminiKeyPool


SYSTEM = """Kamu adalah Gemini Intent Agent di aplikasi Full Album Maker.
Bahasa utama: Indonesia.

PERANMU HANYA MEMAHAMI BAHASA MANUSIA DAN MENERJEMAHKANNYA MENJADI INTENT APLIKASI.
Kamu tidak menghitung timeline, tidak menentukan timestamp/frame, tidak menjalankan FFmpeg,
dan tidak merender video. Semua pekerjaan teknis dilakukan engine lokal aplikasi.

Pahami bahasa santai, singkatan, typo, dan perintah pendek. Contoh:
- "susun semua lagu dan video" -> auto_build_timeline
- "bikin auto" -> auto_build_timeline
- "pokoknya buat jadi full album" -> auto_build_timeline
- "slowmo 50 lalu susun" -> set_slowmo speed 0.5, lalu auto_build_timeline
- "jangan terlalu slow, minimal 0.6" -> set_auto_speed min_speed 0.6
- "kalau kurang loop aja" -> set_loop_mode loop
- "jangan loop, maju mundur" -> set_loop_mode pingpong
- "buat 4k lalu susun" -> optimize_youtube 4k, lalu auto_build_timeline
- "lagu 3 pindah ke awal" -> move_audio 3 ke 1
- "hapus video kedua" -> remove_video position 2
- "urutkan semua lagu" -> sort_audio_by_name
- "cek sudah siap belum" -> validate_project

Aturan keras:
1. Jangan pernah menghitung sendiri berapa detik Auto Cut/Loop/slowmo yang dibutuhkan.
2. Jangan pernah mengarang isi visual footage. Konteks hanya berisi nama, durasi, urutan, dan setting.
3. Audio adalah master timeline, tetapi keputusan teknis tetap milik engine lokal.
4. Jangan mengubah urutan lagu/video kecuali pengguna meminta.
5. Jika pengguna meminta beberapa aksi, keluarkan function call sesuai urutan logis.
   Setting harus diterapkan SEBELUM auto_build_timeline.
6. Tidak ada fungsi render. Jangan mengklaim render sudah dimulai/selesai.
7. Jika maksud pengguna cukup jelas, jangan bertanya ulang.
8. Jika pengguna hanya bertanya informasi, boleh jawab teks singkat tanpa function call.
9. Jika ada function call, teks pendamping hanya menyatakan pemahaman/niat, bukan klaim hasil.
10. "50 persen", "50%", atau "slowmo 50" berarti speed 0.50x bila konteksnya slow motion.
"""

TOOLS = [
    {
        "name": "auto_build_timeline",
        "description": "Menyuruh engine lokal aplikasi menyusun semua footage dan semua lagu menjadi TimelinePlan. Gunakan untuk 'susun semuanya', 'bikin auto', 'buat full album', atau 'auto timeline'.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "validate_project",
        "description": "Menyuruh aplikasi mengecek apakah proyek siap dan menampilkan error/warning.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "optimize_youtube",
        "description": "Menerapkan preset YouTube lokal. Tidak membuat timeline kecuali auto_build_timeline juga dipanggil.",
        "parameters": {
            "type": "object",
            "properties": {
                "quality": {"type": "string", "enum": ["1080p", "1440p", "4k"]}
            },
            "required": ["quality"],
        },
    },
    {
        "name": "set_slowmo",
        "description": "Kunci speed footage manual. Contoh 0.5 berarti 50% speed.",
        "parameters": {
            "type": "object",
            "properties": {"speed": {"type": "number"}},
            "required": ["speed"],
        },
    },
    {
        "name": "set_auto_speed",
        "description": "Aktifkan Auto Fit lokal. min_speed adalah batas slowmo terendah.",
        "parameters": {
            "type": "object",
            "properties": {"min_speed": {"type": "number"}},
        },
    },
    {
        "name": "set_loop_mode",
        "description": "Atur cara aplikasi mengisi kekurangan footage.",
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
        "description": "Atur resolusi output.",
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
        "description": "Atur codec video output.",
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
        "description": "Atur bitrate video/audio secara eksplisit.",
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
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "sort_video_by_name",
        "description": "Urutkan semua footage berdasarkan nama file.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "move_audio",
        "description": "Pindahkan lagu berdasarkan nomor posisi, dimulai dari 1.",
        "parameters": {
            "type": "object",
            "properties": {
                "from_position": {"type": "integer", "minimum": 1},
                "to_position": {"type": "integer", "minimum": 1},
            },
            "required": ["from_position", "to_position"],
        },
    },
    {
        "name": "move_video",
        "description": "Pindahkan footage berdasarkan nomor posisi, dimulai dari 1.",
        "parameters": {
            "type": "object",
            "properties": {
                "from_position": {"type": "integer", "minimum": 1},
                "to_position": {"type": "integer", "minimum": 1},
            },
            "required": ["from_position", "to_position"],
        },
    },
    {
        "name": "remove_audio",
        "description": "Hapus lagu dari proyek berdasarkan nomor posisi jika pengguna meminta eksplisit.",
        "parameters": {
            "type": "object",
            "properties": {"position": {"type": "integer", "minimum": 1}},
            "required": ["position"],
        },
    },
    {
        "name": "remove_video",
        "description": "Hapus footage dari proyek berdasarkan nomor posisi jika pengguna meminta eksplisit.",
        "parameters": {
            "type": "object",
            "properties": {"position": {"type": "integer", "minimum": 1}},
            "required": ["position"],
        },
    },
]


class GeminiAgent:
    def __init__(
        self,
        pool: GeminiKeyPool,
        model: str = "gemini-3.8-flash",
    ) -> None:
        self.pool = pool
        self.model = model
        self.history: list[dict[str, Any]] = []

    def _url(self) -> str:
        model = quote(self.model.strip(), safe="-_.")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def reset(self) -> None:
        self.history.clear()

    def interpret(
        self,
        text: str,
        project_context: dict[str, Any],
    ) -> AgentDecision:
        history_start = len(self.history)
        self.history.append({"role": "user", "parts": [{"text": text}]})

        try:
            context_text = json.dumps(
                project_context,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            payload = {
                "systemInstruction": {
                    "parts": [
                        {
                            "text": SYSTEM
                            + "\n\nKONTEKS PROYEK SAAT INI (jangan dihitung ulang):\n"
                            + context_text
                        }
                    ]
                },
                "contents": self.history[-16:],
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
            parts = content.get("parts", [])

            actions: list[AgentAction] = []
            texts: list[str] = []

            for part in parts:
                if part.get("text"):
                    texts.append(str(part["text"]).strip())
                call = part.get("functionCall")
                if call:
                    name = str(call.get("name", "")).strip()
                    args = call.get("args") or {}
                    if not isinstance(args, dict):
                        raise RuntimeError(f"Argumen intent {name} tidak valid.")
                    actions.append(AgentAction(name=name, args=dict(args)))

            message = "\n".join(x for x in texts if x).strip()
            if actions and not message:
                message = "Saya memahami perintahnya. Saya teruskan ke engine aplikasi."
            elif not actions and not message:
                message = "Saya belum menemukan aksi aplikasi yang perlu dijalankan."

            # Keep only safe conversational text in history. Raw function calls are not
            # stored because the app, not Gemini, executes them outside the API tool loop.
            self.history.append({"role": "model", "parts": [{"text": message}]})
            self.history = self.history[-16:]
            return AgentDecision(message=message, actions=actions)
        except Exception:
            del self.history[history_start:]
            raise
