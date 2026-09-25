from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .controller import ProjectController
from .key_pool import GeminiKeyPool

SYSTEM = """Kamu adalah Gemini Agent di aplikasi Full Album Maker.
Bahasa utama: Indonesia. Tugasmu mengatur proyek full album melalui tools yang tersedia.
Jangan mengarang file atau durasi. Gunakan project_summary sebelum keputusan yang bergantung pada durasi.
Utamakan hasil video yang halus: jangan perlambat di bawah min_speed kecuali pengguna meminta eksplisit.
Audio tidak pernah di-slow-motion. Jelaskan perubahan dengan ringkas setelah tool selesai.
"""

TOOLS = [
    {"name": "project_summary", "description": "Membaca kondisi proyek, durasi, speed, dan setting saat ini."},
    {"name": "set_slowmo", "description": "Atur speed footage manual. 0.5 berarti setengah kecepatan.",
     "parameters": {"type":"object","properties":{"speed":{"type":"number"}},"required":["speed"]}},
    {"name": "set_auto_speed", "description": "Aktifkan pencocokan slow-motion otomatis; min_speed menjadi batas slowmo terendah.",
     "parameters":{"type":"object","properties":{"min_speed":{"type":"number"}}}},
    {"name": "set_loop_mode", "description": "Pilih cara memperpanjang video jika kurang.",
     "parameters":{"type":"object","properties":{"mode":{"type":"string","enum":["auto","loop","pingpong","none"]}},"required":["mode"]}},
    {"name": "set_resolution", "description": "Atur resolusi output.",
     "parameters":{"type":"object","properties":{"width":{"type":"integer"},"height":{"type":"integer"}},"required":["width","height"]}},
    {"name": "set_fps", "description": "Atur FPS output.",
     "parameters":{"type":"object","properties":{"fps":{"type":"integer","enum":[24,25,30,50,60]}},"required":["fps"]}},
    {"name": "set_codec", "description": "Atur codec video.",
     "parameters":{"type":"object","properties":{"codec":{"type":"string","enum":["h264","h265"]}},"required":["codec"]}},
    {"name": "sort_audio_by_name", "description": "Urutkan daftar lagu berdasarkan nama file."},
]

class GeminiAgent:
    def __init__(self, pool: GeminiKeyPool, controller: ProjectController, model: str = "gemini-3.6-flash") -> None:
        self.pool = pool
        self.controller = controller
        self.model = model
        self.history: list[dict[str, Any]] = []

    def _url(self) -> str:
        model = quote(self.model.strip(), safe="-_.")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def ask(self, text: str) -> str:
        self.history.append({"role":"user","parts":[{"text": text}]})
        for _ in range(8):
            payload = {
                "systemInstruction": {"parts":[{"text": SYSTEM}]},
                "contents": self.history,
                "tools": [{"functionDeclarations": TOOLS}],
            }
            response = self.pool.request_json(self._url(), payload)
            candidates = response.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini tidak mengembalikan candidate.")
            content = candidates[0].get("content", {"role":"model","parts":[]})
            self.history.append(content)
            parts = content.get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                texts = [p.get("text","") for p in parts if p.get("text")]
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
                part = {"functionResponse":{"name":name,"response":body}}
                if call.get("id"):
                    part["functionResponse"]["id"] = call["id"]
                responses.append(part)
            self.history.append({"role":"user","parts":responses})
        raise RuntimeError("Agent mencapai batas langkah tool.")
