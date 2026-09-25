from __future__ import annotations

import json
from pathlib import Path

from .project import Project


def save_project(path: str, project: Project) -> str:
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target)


def load_project(path: str) -> Project:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Format file proyek tidak valid.")
    return Project.from_dict(data)
