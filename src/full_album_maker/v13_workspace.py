from __future__ import annotations

from .editor_commands import AddLayer, SetLayerProperty
from .editor_models import ProjectDocument
from .s11_workspace import S11EditorWorkspace
from .song_visuals import (
    SongVisualAssignmentService,
    SongVisualManagerPanel,
    make_song_visual_layer,
    normalize_song_visual_properties,
)


class V13EditorWorkspace(S11EditorWorkspace):
    """v1.2 workspace plus per-song photo/video assignment and transitions."""

    def __init__(
        self,
        document: ProjectDocument | None = None,
        parent=None,
        *,
        custom_template_root=None,
        template_preview_enabled: bool = True,
    ) -> None:
        super().__init__(
            document,
            parent,
            custom_template_root=custom_template_root,
            template_preview_enabled=template_preview_enabled,
        )
        self.song_visual_manager_v13 = SongVisualManagerPanel(self)
        self.tabs.addTab(self.song_visual_manager_v13, "Visual Lagu")
        self.song_visual_manager_v13.assignRequested.connect(
            self._assign_song_visuals_v13
        )
        self.song_visual_manager_v13.clearRequested.connect(
            self._clear_song_visuals_v13
        )
        self.song_visual_manager_v13.autoMatchRequested.connect(
            self._auto_match_song_visuals_v13
        )
        self.song_visual_manager_v13.styleRequested.connect(
            self._apply_song_visual_style_v13
        )
        self.song_visual_manager_v13.set_document(self.session.snapshot())

    def set_document(
        self,
        document: ProjectDocument,
        *,
        current_path: str = "",
    ) -> None:
        super().set_document(document, current_path=current_path)
        if hasattr(self, "song_visual_manager_v13"):
            self.song_visual_manager_v13.set_document(self.session.snapshot())

    def _after_edit(self) -> None:
        super()._after_edit()
        if hasattr(self, "song_visual_manager_v13"):
            self.song_visual_manager_v13.set_document(self.session.snapshot())

    @staticmethod
    def _song_visual_layer(document: ProjectDocument):
        return next(
            (layer for layer in document.layers if layer.type == "song_visual"),
            None,
        )

    @staticmethod
    def _make_song_visual_layer_for(document: ProjectDocument):
        track = next(
            (item for item in document.tracks if item.kind == "visual" and item.enabled),
            None,
        )
        if track is None:
            track = next(
                (item for item in document.tracks if item.kind == "visual"),
                None,
            )
        if track is None:
            raise ValueError("Track visual tidak tersedia.")
        layer = make_song_visual_layer(track.track_id, 5)
        existing_orders = {item.order for item in document.layers}
        while layer.order in existing_orders:
            layer.order += 1
        return layer

    def _assign_song_visuals_v13(self, song_ids, asset_id: str) -> None:
        try:
            doc = self.session.snapshot()
            commands = SongVisualAssignmentService.bulk_commands(
                doc,
                list(song_ids),
                asset_id,
            )
            if not commands:
                self._set_status("Visual tersebut sudah terpasang pada semua lagu terpilih.")
                return
            if self._song_visual_layer(doc) is None:
                commands.insert(0, AddLayer(self._make_song_visual_layer_for(doc)))
            self.session.controller.dispatch(commands)
            count = sum(1 for command in commands if command.__class__.__name__ == "SetSongVisual")
            self._after_edit()
            self._set_status(
                f"Visual lagu dipasang ke {count} lagu sebagai satu transaksi Undo."
            )
        except Exception as exc:
            self._set_status(f"Pasang Visual Lagu gagal: {exc}")

    def _clear_song_visuals_v13(self, song_ids) -> None:
        try:
            commands = SongVisualAssignmentService.bulk_commands(
                self.session.snapshot(),
                list(song_ids),
                None,
            )
            if not commands:
                self._set_status("Lagu terpilih sudah tidak memiliki visual khusus.")
                return
            self.session.controller.dispatch(commands)
            self._after_edit()
            self._set_status(
                f"Visual khusus dihapus dari {len(commands)} lagu sebagai satu transaksi Undo."
            )
        except Exception as exc:
            self._set_status(f"Hapus Visual Lagu gagal: {exc}")

    def _auto_match_song_visuals_v13(self, only_empty: bool) -> None:
        try:
            doc = self.session.snapshot()
            commands, report = SongVisualAssignmentService.auto_match_commands(
                doc,
                only_empty=bool(only_empty),
            )
            if commands and self._song_visual_layer(doc) is None:
                commands.insert(0, AddLayer(self._make_song_visual_layer_for(doc)))
            assignment_count = sum(
                1 for command in commands if command.__class__.__name__ == "SetSongVisual"
            )
            if commands:
                self.session.controller.dispatch(commands)
                self._after_edit()
            self._set_status(
                "Cocokkan Visual Lagu selesai: "
                f"{assignment_count} dipasang, "
                f"{len(report.unmatched_song_ids)} tidak cocok, "
                f"{len(report.ambiguous_song_ids)} ambigu, "
                f"{len(report.skipped_existing_song_ids)} visual lama dipertahankan."
            )
        except Exception as exc:
            self._set_status(f"Cocokkan Visual Lagu gagal: {exc}")

    def _apply_song_visual_style_v13(self, properties) -> None:
        try:
            props = normalize_song_visual_properties(dict(properties))
            doc = self.session.snapshot()
            layer = self._song_visual_layer(doc)
            commands = []
            if layer is None:
                layer = self._make_song_visual_layer_for(doc)
                layer.properties = dict(props)
                commands.append(AddLayer(layer))
            else:
                for key, value in props.items():
                    if layer.properties.get(key) != value:
                        commands.append(SetLayerProperty(layer.layer_id, key, value))
            if not commands:
                self._set_status("Gaya Visual Lagu tidak berubah.")
                return
            self.session.controller.dispatch(commands)
            self._after_edit()
            self._set_status(
                "Gaya Visual Lagu diterapkan: "
                f"{props['image_motion']} / {props['transition']} {props['transition_seconds']:.2f} dtk."
            )
        except Exception as exc:
            self._set_status(f"Gaya Visual Lagu ditolak: {exc}")
