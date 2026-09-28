from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .editor_commands import CommandError, DeleteLayer, EditorCommand, SetCanvasBackground
from .editor_models import Layer, ProjectDocument, TimeBinding, Transform, new_id
from .overlay_effects import normalize_effect_properties
from .paths import data_dir
from .template_system import ReplaceTemplateLayers, current_template_id

CUSTOM_TEMPLATE_FORMAT = "full-album-maker-custom-template"
CUSTOM_TEMPLATE_VERSION = 1
CUSTOM_TEMPLATE_PREFIX = "custom:"
CUSTOM_TEMPLATE_SUFFIX = ".famtpl.json"

PORTABLE_TEMPLATE_LAYER_TYPES = {
    "background",
    "text",
    "spectrum",
    "song_title",
    "song_cover",
    "vinyl",
    "playlist_visual",
    "progress",
    "song_time",
}


class CustomTemplateError(ValueError):
    pass


def _custom_uuid(template_id: str) -> str:
    value = str(template_id or "")
    if not value.startswith(CUSTOM_TEMPLATE_PREFIX):
        raise CustomTemplateError("ID template kustom tidak valid.")
    raw = value[len(CUSTOM_TEMPLATE_PREFIX) :]
    try:
        UUID(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise CustomTemplateError("ID template kustom tidak valid.") from exc
    return raw


def is_custom_template_id(template_id: str) -> bool:
    try:
        _custom_uuid(template_id)
        return True
    except CustomTemplateError:
        return False


def new_custom_template_id() -> str:
    return CUSTOM_TEMPLATE_PREFIX + str(uuid4())


def _json_safe_copy(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise CustomTemplateError(f"{label} tidak dapat disimpan ke template.") from exc


def _clean_label(value: str) -> str:
    label = " ".join(str(value or "").split()).strip()
    if not 1 <= len(label) <= 80:
        raise CustomTemplateError("Nama template harus 1..80 karakter.")
    return label


def _clean_description(value: str) -> str:
    description = str(value or "").strip()
    if len(description) > 500:
        raise CustomTemplateError("Deskripsi template maksimal 500 karakter.")
    return description


def _portable_properties(layer: Layer) -> dict[str, Any]:
    props = _json_safe_copy(layer.properties, "Properties layer")
    props.pop("template_id", None)
    if layer.type == "song_cover":
        # Asset ID hanya valid di project sumber. Target akan resolve image fallback baru.
        props["fallback_asset_id"] = ""
    if layer.type == "text":
        # Path font absolut tidak portabel. Font default renderer dipakai di target.
        props.pop("font_path", None)
    if layer.type == "song_title":
        props.pop("font_path", None)
    if layer.type == "background":
        mode = str(props.get("mode", "solid"))
        if mode == "asset":
            raise CustomTemplateError(
                f"Layer '{layer.name}' memakai background image/video. "
                "Template portabel tidak menyimpan referensi asset project."
            )
        if mode == "effect":
            try:
                normalized = normalize_effect_properties(props)
            except ValueError as exc:
                raise CustomTemplateError(
                    f"Effect procedural '{layer.name}' tidak valid: {exc}"
                ) from exc
            normalized["mode"] = "effect"
            props = normalized
        elif mode != "solid":
            raise CustomTemplateError(
                f"Mode background '{mode}' belum portabel untuk template kustom."
            )
        # Solid/effect tidak membutuhkan asset id atau path project.
        props.pop("asset_id", None)
    return props


def _portable_layer_spec(layer: Layer) -> dict[str, Any]:
    if layer.type not in PORTABLE_TEMPLATE_LAYER_TYPES:
        raise CustomTemplateError(
            f"Tipe layer belum portabel untuk template: {layer.type}"
        )
    if layer.asset_refs and layer.type != "song_cover":
        raise CustomTemplateError(
            f"Layer '{layer.name}' masih bergantung asset project. "
            "Gunakan elemen dinamis/solid/procedural sebelum menyimpan template portabel."
        )
    transform = {
        "x": float(layer.transform.x),
        "y": float(layer.transform.y),
        "width": float(layer.transform.width),
        "height": float(layer.transform.height),
        "rotation": float(layer.transform.rotation),
        "pivot_x": float(layer.transform.pivot_x),
        "pivot_y": float(layer.transform.pivot_y),
    }
    # Template layout berlaku sepanjang album. Binding song_id/absolute tidak dibawa
    # agar template dapat dipakai di playlist berbeda tanpa referensi stale.
    return {
        "type": layer.type,
        "name": str(layer.name),
        "enabled": bool(layer.enabled),
        "locked": bool(layer.locked),
        "opacity": float(layer.opacity),
        "order": int(layer.order),
        "transform": transform,
        "properties": _portable_properties(layer),
        "animation": _json_safe_copy(layer.animation, "Animation layer"),
    }


@dataclass(frozen=True)
class CustomTemplate:
    template_id: str
    label: str
    description: str = ""
    canvas_background_color: str = "#101114"
    layers: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    source_project_id: str = ""
    source_layer_ids: tuple[str, ...] = field(default_factory=tuple)
    format: str = CUSTOM_TEMPLATE_FORMAT
    version: int = CUSTOM_TEMPLATE_VERSION

    def validate(self) -> None:
        if self.format != CUSTOM_TEMPLATE_FORMAT:
            raise CustomTemplateError("Format template kustom tidak didukung.")
        if self.version != CUSTOM_TEMPLATE_VERSION:
            raise CustomTemplateError("Versi template kustom tidak didukung.")
        _custom_uuid(self.template_id)
        _clean_label(self.label)
        _clean_description(self.description)
        if (
            not isinstance(self.canvas_background_color, str)
            or not self.canvas_background_color.strip()
        ):
            raise CustomTemplateError("Warna background template tidak valid.")
        if not self.layers:
            raise CustomTemplateError("Template kustom tidak memiliki layer.")
        if len(self.layers) > 100:
            raise CustomTemplateError("Template kustom maksimal 100 layer.")
        for spec in self.layers:
            _validate_layer_spec(spec)
        if self.source_project_id:
            try:
                UUID(self.source_project_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise CustomTemplateError(
                    "source_project_id template tidak valid."
                ) from exc
        for layer_id in self.source_layer_ids:
            try:
                UUID(layer_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise CustomTemplateError(
                    "source_layer_ids template tidak valid."
                ) from exc

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "format": self.format,
            "version": self.version,
            "template_id": self.template_id,
            "label": self.label,
            "description": self.description,
            "canvas_background_color": self.canvas_background_color,
            "layers": [deepcopy(item) for item in self.layers],
            "source_project_id": self.source_project_id,
            "source_layer_ids": list(self.source_layer_ids),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CustomTemplate":
        if not isinstance(data, dict):
            raise CustomTemplateError("Isi template kustom tidak valid.")
        layers = data.get("layers", [])
        if not isinstance(layers, list):
            raise CustomTemplateError("Daftar layer template tidak valid.")
        source_layer_ids = data.get("source_layer_ids", [])
        if not isinstance(source_layer_ids, list):
            raise CustomTemplateError("source_layer_ids template tidak valid.")
        item = cls(
            format=str(data.get("format", "")),
            version=int(data.get("version", 0)),
            template_id=str(data.get("template_id", "")),
            label=str(data.get("label", "")),
            description=str(data.get("description", "") or ""),
            canvas_background_color=str(
                data.get("canvas_background_color", "#101114")
            ),
            layers=tuple(
                _json_safe_copy(layer, "Layer template") for layer in layers
            ),
            source_project_id=str(data.get("source_project_id", "") or ""),
            source_layer_ids=tuple(str(value) for value in source_layer_ids),
        )
        item.validate()
        return item


def _validate_layer_spec(spec: Any) -> None:
    if not isinstance(spec, dict):
        raise CustomTemplateError("Spec layer template tidak valid.")
    layer_type = str(spec.get("type", ""))
    if layer_type not in PORTABLE_TEMPLATE_LAYER_TYPES:
        raise CustomTemplateError(
            f"Tipe layer template tidak didukung: {layer_type}"
        )
    transform_data = spec.get("transform", {})
    if not isinstance(transform_data, dict):
        raise CustomTemplateError("Transform template tidak valid.")
    try:
        transform = Transform.from_dict(transform_data)
    except Exception as exc:
        raise CustomTemplateError(
            f"Transform template tidak valid: {exc}"
        ) from exc
    if (
        not 0.02 <= transform.width <= 3.0
        or not 0.02 <= transform.height <= 3.0
    ):
        raise CustomTemplateError("Ukuran layer template harus 0.02..3.0.")
    opacity = float(spec.get("opacity", 1.0))
    if not 0.0 <= opacity <= 1.0:
        raise CustomTemplateError("Opacity layer template harus 0..1.")
    order = int(spec.get("order", 0))
    if order < 0:
        raise CustomTemplateError("Order layer template tidak valid.")
    properties = spec.get("properties", {})
    animation = spec.get("animation", {})
    if not isinstance(properties, dict) or not isinstance(animation, dict):
        raise CustomTemplateError(
            "Properties/animation template tidak valid."
        )
    if layer_type == "background":
        mode = str(properties.get("mode", "solid"))
        if mode == "asset":
            raise CustomTemplateError(
                "Background asset tidak boleh ada di template portabel."
            )
        if mode == "effect":
            try:
                normalize_effect_properties(properties)
            except ValueError as exc:
                raise CustomTemplateError(
                    f"Effect procedural template tidak valid: {exc}"
                ) from exc
        elif mode != "solid":
            raise CustomTemplateError(
                f"Mode background template tidak didukung: {mode}"
            )
    _json_safe_copy(properties, "Properties template")
    _json_safe_copy(animation, "Animation template")


def capture_custom_template(
    document: ProjectDocument,
    label: str,
    description: str = "",
    *,
    template_id: str | None = None,
) -> CustomTemplate:
    document.validate()
    visual_tracks = {
        track.track_id for track in document.tracks if track.kind == "visual"
    }
    candidates = [
        layer
        for layer in sorted(document.layers, key=lambda item: item.order)
        if layer.track_id in visual_tracks
        and layer.type in PORTABLE_TEMPLATE_LAYER_TYPES
    ]
    if not candidates:
        raise CustomTemplateError(
            "Tidak ada layer visual portabel yang bisa disimpan sebagai template."
        )
    specs = tuple(_portable_layer_spec(layer) for layer in candidates)
    item = CustomTemplate(
        template_id=template_id or new_custom_template_id(),
        label=_clean_label(label),
        description=_clean_description(description),
        canvas_background_color=document.canvas.background_color,
        layers=specs,
        source_project_id=document.project_id,
        source_layer_ids=tuple(layer.layer_id for layer in candidates),
    )
    item.validate()
    return item


def _first_image_asset_id(document: ProjectDocument) -> str:
    return next(
        (asset.asset_id for asset in document.media if asset.kind == "image"),
        "",
    )


def build_custom_template_layers(
    document: ProjectDocument,
    template: CustomTemplate,
) -> list[Layer]:
    document.validate()
    template.validate()
    track = next(
        (
            item
            for item in document.tracks
            if item.kind == "visual" and item.enabled
        ),
        None,
    )
    if track is None:
        track = next(
            (item for item in document.tracks if item.kind == "visual"),
            None,
        )
    if track is None:
        raise CustomTemplateError(
            "Template kustom membutuhkan track visual."
        )
    fallback_image = _first_image_asset_id(document)
    result: list[Layer] = []
    for spec in sorted(
        template.layers,
        key=lambda item: int(item.get("order", 0)),
    ):
        _validate_layer_spec(spec)
        properties = deepcopy(spec.get("properties", {}))
        if str(spec.get("type")) == "song_cover":
            properties["fallback_asset_id"] = fallback_image
        properties["template_id"] = template.template_id
        layer = Layer(
            layer_id=new_id(),
            track_id=track.track_id,
            type=str(spec["type"]),
            name=str(spec.get("name", spec["type"])),
            enabled=bool(spec.get("enabled", True)),
            locked=bool(spec.get("locked", False)),
            opacity=float(spec.get("opacity", 1.0)),
            order=int(spec.get("order", 0)),
            time_binding=TimeBinding(kind="album"),
            transform=Transform.from_dict(spec.get("transform", {})),
            properties=properties,
            animation=deepcopy(spec.get("animation", {})),
            asset_refs=[],
            origin="template",
        )
        layer.validate()
        result.append(layer)
    return result


@dataclass
class SetCustomTemplateMarker(EditorCommand):
    template_id: str = ""

    def apply(self, document: ProjectDocument) -> EditorCommand:
        old = str(
            document.editor_defaults.get("custom_template_id", "") or ""
        )
        if self.template_id:
            if not is_custom_template_id(self.template_id):
                raise CommandError("ID template kustom tidak valid.")
            document.editor_defaults["custom_template_id"] = self.template_id
        else:
            document.editor_defaults.pop("custom_template_id", None)
        return SetCustomTemplateMarker(old)


def current_custom_template_id(document: ProjectDocument) -> str:
    value = str(
        document.editor_defaults.get("custom_template_id", "") or ""
    )
    return value if is_custom_template_id(value) else ""


def current_template_reference(document: ProjectDocument) -> str:
    built_in = current_template_id(document)
    return built_in or current_custom_template_id(document)


def apply_custom_template_commands(
    document: ProjectDocument,
    template: CustomTemplate,
) -> tuple[EditorCommand, ...]:
    layers = build_custom_template_layers(document, template)
    commands: list[EditorCommand] = []

    # Jika template dibuat dari project yang sama, layer manual sumber yang ikut
    # disimpan dihapus saat re-apply agar tidak muncul duplikat. Di project lain
    # tidak ada layer manual yang disentuh.
    if (
        template.source_project_id
        and template.source_project_id == document.project_id
    ):
        layer_map = document.layer_map()
        for layer_id in template.source_layer_ids:
            layer = layer_map.get(layer_id)
            if layer is None or layer.origin == "template":
                continue
            if layer.locked:
                raise CustomTemplateError(
                    f"Layer sumber '{layer.name}' terkunci. Buka lock sebelum menerapkan template kustom."
                )
            commands.append(DeleteLayer(layer_id))

    commands.extend(
        [
            ReplaceTemplateLayers(layers, ""),
            SetCanvasBackground(template.canvas_background_color),
            SetCustomTemplateMarker(template.template_id),
        ]
    )
    return tuple(commands)


def apply_builtin_template_commands(
    document: ProjectDocument,
    command: EditorCommand,
) -> tuple[EditorCommand, ...]:
    # Built-in template harus membersihkan marker custom dalam transaksi undo yang sama.
    return (command, SetCustomTemplateMarker(""))


class CustomTemplateStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (
            Path(root)
            if root is not None
            else data_dir() / "templates" / "custom"
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for_id(self, template_id: str) -> Path:
        raw = _custom_uuid(template_id)
        return self.root / f"{raw}{CUSTOM_TEMPLATE_SUFFIX}"

    @staticmethod
    def _read_path(path: Path) -> CustomTemplate:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CustomTemplateError(
                f"Template tidak dapat dibaca: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise CustomTemplateError("JSON template kustom rusak.") from exc
        return CustomTemplate.from_dict(raw)

    @staticmethod
    def _atomic_write(path: Path, template: CustomTemplate) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                template.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temp = path.with_name(path.name + f".{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def save(self, template: CustomTemplate) -> Path:
        template.validate()
        path = self._path_for_id(template.template_id)
        self._atomic_write(path, template)
        return path

    def create_from_document(
        self,
        document: ProjectDocument,
        label: str,
        description: str = "",
    ) -> CustomTemplate:
        template = capture_custom_template(document, label, description)
        self.save(template)
        return template

    def load(self, template_id: str) -> CustomTemplate:
        path = self._path_for_id(template_id)
        if not path.exists():
            raise CustomTemplateError("Template kustom tidak ditemukan.")
        item = self._read_path(path)
        if item.template_id != template_id:
            raise CustomTemplateError(
                "ID file template tidak cocok dengan nama penyimpanan."
            )
        return item

    def scan(self) -> tuple[list[CustomTemplate], list[str]]:
        templates: list[CustomTemplate] = []
        errors: list[str] = []
        for path in sorted(self.root.glob(f"*{CUSTOM_TEMPLATE_SUFFIX}")):
            try:
                templates.append(self._read_path(path))
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        templates.sort(
            key=lambda item: (item.label.casefold(), item.template_id)
        )
        return templates, errors

    def delete(self, template_id: str) -> None:
        path = self._path_for_id(template_id)
        if not path.exists():
            raise CustomTemplateError("Template kustom tidak ditemukan.")
        path.unlink()

    def export_template(
        self,
        template_id: str,
        destination: str | Path,
    ) -> Path:
        template = self.load(template_id)
        path = Path(destination)
        if not path.name.lower().endswith(CUSTOM_TEMPLATE_SUFFIX):
            path = path.with_name(path.name + CUSTOM_TEMPLATE_SUFFIX)
        self._atomic_write(path, template)
        return path

    def import_template(self, source: str | Path) -> CustomTemplate:
        source_path = Path(source)
        template = self._read_path(source_path)
        destination = self._path_for_id(template.template_id)
        if destination.exists():
            # Jangan overwrite template lokal secara diam-diam. Impor menjadi copy baru.
            template = CustomTemplate(
                template_id=new_custom_template_id(),
                label=template.label,
                description=template.description,
                canvas_background_color=template.canvas_background_color,
                layers=template.layers,
                source_project_id=template.source_project_id,
                source_layer_ids=template.source_layer_ids,
            )
        self.save(template)
        return template
