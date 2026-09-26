from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

from . import visual_feature as visual_feature_module
from .atomic_io import atomic_write_text
from .paths import output_dir, temp_dir
from .project import Project
from .renderer import FFmpegRenderer, RenderError
from .timeline import save_timeline

_installed = False
_originals: dict[str, Any] = {}

JOURNAL_PREFIX = ".fam-bundle-"
JOURNAL_SUFFIX = ".json"


def _replace_file(source: Path, target: Path) -> None:
    os.replace(source, target)


def _backup_file(source: Path, backup: Path) -> None:
    """Preserve an existing final without moving it out of place.

    NTFS hard links make this O(1) for normal portable Windows use. Filesystems
    without hard-link support fall back to copy2. The original final remains
    visible until the new bundle is ready to replace it.
    """

    try:
        os.link(source, backup)
    except OSError:
        shutil.copy2(source, backup)


def _journal_payload(state: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "state": state,
        "entries": entries,
    }


def _write_journal(path: Path, state: str, entries: list[dict[str, Any]]) -> None:
    atomic_write_text(
        path,
        json.dumps(
            _journal_payload(state, entries),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_journal(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RenderError(
            f"Journal render tidak dapat dibaca: {path.name}. "
            "Jangan hapus file backup sebelum diperiksa."
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise RenderError(f"Journal render tidak valid: {path.name}")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise RenderError(f"Journal render tidak valid: {path.name}")
    return payload


def _cleanup_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _rollback_entries(entries: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for entry in entries:
        target = Path(str(entry["target"]))
        backup_raw = str(entry.get("backup") or "")
        backup = Path(backup_raw) if backup_raw else None
        had_original = bool(entry.get("had_original"))
        try:
            if had_original:
                if backup is None or not backup.exists():
                    # If no backup exists, publication cannot have started for
                    # this entry in a valid transaction. Leave target untouched.
                    continue
                _replace_file(backup, target)
            else:
                target.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{target.name}: {exc}")
    return failures


def _cleanup_transaction_files(entries: list[dict[str, Any]], journal: Path) -> None:
    for entry in entries:
        backup_raw = str(entry.get("backup") or "")
        stage_raw = str(entry.get("stage") or "")
        if backup_raw:
            _cleanup_path(Path(backup_raw))
        if stage_raw:
            _cleanup_path(Path(stage_raw))
    _cleanup_path(journal)


def recover_interrupted_bundles(directory: Path) -> None:
    """Recover a previous crash during the tiny multi-file publish phase.

    A committed journal means every target was already replaced and only hidden
    backups/journal cleanup was interrupted. Any other state rolls back to the
    previous bundle, preferring consistency over keeping a possibly partial new
    render.
    """

    directory = Path(directory)
    if not directory.exists():
        return
    for journal in sorted(directory.glob(f"{JOURNAL_PREFIX}*{JOURNAL_SUFFIX}")):
        payload = _read_journal(journal)
        entries = payload["entries"]
        state = str(payload.get("state") or "")
        if state == "committed":
            _cleanup_transaction_files(entries, journal)
            continue

        failures = _rollback_entries(entries)
        if failures:
            raise RenderError(
                "Gagal memulihkan transaksi render sebelumnya:\n• "
                + "\n• ".join(failures)
            )
        _cleanup_transaction_files(entries, journal)


def publish_bundle_transactional(
    pairs: Iterable[tuple[Path, Path]],
) -> None:
    """Publish staged files as a rollback-capable bundle.

    Multi-file replacement cannot be a single filesystem syscall. This function
    therefore guarantees a stronger application-level transaction: all new files
    must exist first; all old finals are backed up while staying visible; any
    replacement failure restores every previous final. A journal supports recovery
    after process loss during publication.
    """

    normalized = [(Path(stage), Path(target)) for stage, target in pairs]
    if not normalized:
        raise RenderError("Bundle render kosong.")

    directories = {target.parent.resolve() for _, target in normalized}
    if len(directories) != 1:
        raise RenderError("Semua file bundle render harus berada dalam satu folder.")
    directory = next(iter(directories))
    directory.mkdir(parents=True, exist_ok=True)

    recover_interrupted_bundles(directory)

    seen_targets: set[str] = set()
    for stage, target in normalized:
        if not stage.exists():
            raise RenderError(f"File staging belum tersedia: {stage.name}")
        key = str(target.resolve()).casefold()
        if key in seen_targets:
            raise RenderError(f"Target bundle duplikat: {target.name}")
        seen_targets.add(key)

    bundle_id = uuid.uuid4().hex
    journal = directory / f"{JOURNAL_PREFIX}{bundle_id}{JOURNAL_SUFFIX}"
    entries: list[dict[str, Any]] = []
    for stage, target in normalized:
        had_original = target.exists()
        backup = (
            directory / f".{target.name}.fam-backup-{bundle_id}"
            if had_original
            else None
        )
        entries.append(
            {
                "stage": str(stage.resolve()),
                "target": str(target.resolve()),
                "backup": str(backup.resolve()) if backup is not None else "",
                "had_original": had_original,
            }
        )

    _write_journal(journal, "preparing", entries)
    try:
        for entry in entries:
            if not entry["had_original"]:
                continue
            source = Path(entry["target"])
            backup = Path(entry["backup"])
            _backup_file(source, backup)

        _write_journal(journal, "publishing", entries)
        for entry in entries:
            _replace_file(Path(entry["stage"]), Path(entry["target"]))

        # Mark committed before deleting backups. If the process dies after this
        # point, recovery keeps the complete new bundle and only removes debris.
        _write_journal(journal, "committed", entries)
    except Exception as exc:
        failures = _rollback_entries(entries)
        if not failures:
            _cleanup_transaction_files(entries, journal)
            raise RenderError(f"Publikasi bundle render gagal; output lama dipulihkan: {exc}") from exc
        raise RenderError(
            "Publikasi bundle render gagal dan rollback tidak lengkap. "
            "Backup/journal sengaja dipertahankan untuk recovery:\n• "
            + "\n• ".join(failures)
        ) from exc
    else:
        _cleanup_transaction_files(entries, journal)


def _stage_path(target: Path, role: str) -> Path:
    fd, name = tempfile.mkstemp(
        prefix=f".{target.stem}.{role}.",
        suffix=target.suffix or ".tmp",
        dir=str(target.parent),
    )
    os.close(fd)
    path = Path(name)
    path.unlink(missing_ok=True)
    return path


def _check_cancel(renderer: FFmpegRenderer) -> None:
    event = getattr(renderer, "_fam_cancel_event", None)
    if event is not None and event.is_set():
        from .render_lifecycle import CANCEL_TOKEN, RenderCancelled

        raise RenderCancelled(CANCEL_TOKEN + "Render dibatalkan oleh pengguna.")


def _bundle_render(
    self: FFmpegRenderer,
    destination: str | None = None,
    log=None,
) -> str:
    vf = visual_feature_module
    plan = self.timeline
    errors = vf.validate_visual_timeline(plan, self.project)
    if errors:
        raise RenderError(
            "Timeline berubah/tidak valid sebelum render:\n• " + "\n• ".join(errors)
        )

    vf._ensure_project(self.project)
    protected_paths = [
        Path(item.path).resolve()
        for item in [
            *self.project.videos,
            *self.project.audios,
            *vf.images(self.project),
        ]
    ]
    active_paths = {
        Path(clip.source).resolve()
        for clip in [*plan.video_clips, *plan.audio_clips]
    }
    missing = [str(path) for path in active_paths if not path.exists()]
    if missing:
        preview = "\n".join(f"• {value}" for value in missing[:8])
        raise RenderError(f"File sumber timeline tidak ditemukan:\n{preview}")

    self._ensure_encoder()
    destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
    dest_path = Path(destination).resolve()
    sidecars = [
        dest_path.with_name(f"{dest_path.stem}_YouTube_Chapter.txt"),
        dest_path.with_name(f"{dest_path.stem}_Tracklist.txt"),
        dest_path.with_name(f"{dest_path.stem}_Timeline_Final.json"),
    ]
    targets = [dest_path, *sidecars]
    for target in targets:
        if any(vf._same_file(target, source) for source in protected_paths):
            raise RenderError(
                "Lokasi output/sidecar tidak boleh menimpa file sumber proyek."
            )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    recover_interrupted_bundles(dest_path.parent)
    stages = [
        _stage_path(dest_path, "video-rendering"),
        _stage_path(sidecars[0], "chapters-rendering"),
        _stage_path(sidecars[1], "tracklist-rendering"),
        _stage_path(sidecars[2], "timeline-rendering"),
    ]

    root = temp_dir()
    try:
        with tempfile.TemporaryDirectory(prefix="fam_render_", dir=root) as work_dir:
            work = Path(work_dir)
            album_audio = work / "timeline_audio.m4a"
            timeline_video = work / "timeline_video.mp4"
            self._build_audio_from_timeline(album_audio, log)
            self._build_video_from_timeline(timeline_video, work, log)
            self._build_final(timeline_video, album_audio, str(stages[0]), log)

        _check_cancel(self)
        self._write_chapters(stages[1])
        self._write_tracklist(stages[2])
        save_timeline(str(stages[3]), self.timeline)
        _check_cancel(self)

        publish_bundle_transactional(zip(stages, targets))
    finally:
        for stage in stages:
            _cleanup_path(stage)

    if log:
        log(
            "Render selesai dan MP4 + chapter + tracklist + timeline "
            "dipublikasikan sebagai satu bundle transaksional."
        )
    return str(dest_path)


def install_atomic_bundle() -> None:
    global _installed
    if _installed:
        return
    _originals["renderer_render"] = FFmpegRenderer.render
    FFmpegRenderer.render = _bundle_render
    _installed = True


def uninstall_atomic_bundle() -> None:
    global _installed
    if not _installed:
        return
    FFmpegRenderer.render = _originals["renderer_render"]
    _originals.clear()
    _installed = False
