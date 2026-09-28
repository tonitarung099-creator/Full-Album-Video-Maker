from __future__ import annotations

import json
from pathlib import Path

from .atomic_io import atomic_write_text
from .editor_models import ProjectDocument
from .project import Project


def save_project(path: str, project: Project) -> str:
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2)
    return atomic_write_text(target, payload, encoding="utf-8")


def load_project(path: str) -> Project:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Format file proyek tidak valid.")
    return Project.from_dict(data)


def dumps_project_document(project: ProjectDocument) -> str:
    """Serialize editor-v2 ProjectDocument without touching the filesystem."""
    project.validate()
    return json.dumps(project.to_dict(), ensure_ascii=False, sort_keys=True)


def loads_project_document(payload: str) -> ProjectDocument:
    """Deserialize an editor-v2 ProjectDocument from an in-memory JSON string."""
    data = json.loads(str(payload))
    if not isinstance(data, dict):
        raise ValueError("Format ProjectDocument tidak valid.")
    return ProjectDocument.from_dict(data)