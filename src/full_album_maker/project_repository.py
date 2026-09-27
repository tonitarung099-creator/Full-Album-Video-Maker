from __future__ import annotations

import json
from pathlib import Path

from .atomic_io import atomic_write_text
from .editor_models import ProjectDocument, ProjectSchemaError
from .project_migrations import detect_project_payload, migrate_project_v1


def save_project_document(path: str, project: ProjectDocument) -> str:
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(target, payload, encoding="utf-8")


def load_project_document(path: str, *, migrate_legacy: bool = True) -> ProjectDocument:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    kind = detect_project_payload(data)
    if kind == "project_v2":
        return ProjectDocument.from_dict(data)
    if kind == "project_v1" and migrate_legacy:
        return migrate_project_v1(data, name=source.stem)
    if kind == "timeline_v1":
        raise ProjectSchemaError("File ini TimelinePlan v1, bukan file Project yang dapat dibuka langsung.")
    if kind == "future_project":
        raise ProjectSchemaError("Versi proyek lebih baru belum didukung.")
    raise ProjectSchemaError("Format file proyek tidak didukung.")
