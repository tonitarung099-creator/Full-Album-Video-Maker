from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .editor_commands import EditorCommand
from .editor_models import ProjectDocument


class RevisionConflict(RuntimeError):
    pass


@dataclass
class HistoryTransaction:
    commands: tuple[EditorCommand, ...]
    inverse_commands: tuple[EditorCommand, ...]


class EditorController:
    def __init__(
        self,
        document: ProjectDocument,
        *,
        history_limit: int = 100,
        mark_saved: bool = True,
    ) -> None:
        document.validate()
        self._document = document.clone()
        self._history: list[HistoryTransaction] = []
        self._redo: list[HistoryTransaction] = []
        self._history_limit = max(1, int(history_limit))
        self._saved_signature = (
            self._document.content_signature() if mark_saved else None
        )

    @property
    def revision(self) -> int:
        return self._document.revision

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def is_dirty(self) -> bool:
        return self._document.content_signature() != self._saved_signature

    def snapshot(self) -> ProjectDocument:
        return self._document.clone()

    def mark_saved(self) -> None:
        self._saved_signature = self._document.content_signature()

    @staticmethod
    def _apply_transaction(document: ProjectDocument, commands: Iterable[EditorCommand]) -> tuple[ProjectDocument, tuple[EditorCommand, ...]]:
        clone = document.clone()
        inverses: list[EditorCommand] = []
        for command in commands:
            inverse = command.apply(clone)
            inverses.insert(0, inverse)
        clone.validate()
        return clone, tuple(inverses)

    def dispatch(self, command: EditorCommand | Iterable[EditorCommand], *, expected_revision: int | None = None) -> ProjectDocument:
        if expected_revision is not None and expected_revision != self._document.revision:
            raise RevisionConflict(
                f"Revision stale: expected {expected_revision}, current {self._document.revision}."
            )
        commands = (command,) if isinstance(command, EditorCommand) else tuple(command)
        if not commands:
            return self.snapshot()
        updated, inverses = self._apply_transaction(self._document, commands)
        updated.revision = self._document.revision + 1
        self._document = updated
        self._history.append(HistoryTransaction(tuple(commands), inverses))
        if len(self._history) > self._history_limit:
            del self._history[0 : len(self._history) - self._history_limit]
        self._redo.clear()
        return self.snapshot()

    def undo(self) -> ProjectDocument:
        if not self._history:
            return self.snapshot()
        entry = self._history.pop()
        updated, redo_inverses = self._apply_transaction(self._document, entry.inverse_commands)
        updated.revision = self._document.revision + 1
        self._document = updated
        self._redo.append(HistoryTransaction(redo_inverses, entry.inverse_commands))
        return self.snapshot()

    def redo(self) -> ProjectDocument:
        if not self._redo:
            return self.snapshot()
        entry = self._redo.pop()
        updated, inverses = self._apply_transaction(self._document, entry.commands)
        updated.revision = self._document.revision + 1
        self._document = updated
        self._history.append(HistoryTransaction(entry.commands, inverses))
        return self.snapshot()