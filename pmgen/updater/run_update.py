import sys
import os
import json
import shutil
import time
import subprocess
import logging
import logging.handlers
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.expanduser("~"), ".indybiz_pm")
LOG_FILE = os.path.join(LOG_DIR, "updater.log")
LOCK_FILE = ".pmgen_update.lock"
MAX_RETRIES = 12
INITIAL_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0
INTERNAL_REPLACE_RETRIES = 4
PARENT_WAIT_TIMEOUT = 120.0
PRESERVED_TOP_LEVEL_NAMES = {
    LOCK_FILE,
    "catalog_manager.db",
    "catalog_manager.db-wal",
    "catalog_manager.db-shm",
    "catalog_manager.db-journal",
}


def resolve_payload_root(src_dir: str, target_exe_name: str) -> str:
    """
    Finds the directory inside src_dir that contains the target executable and _internal.
    This handles ZIPs that may have an extra top-level folder.
    """
    src_path = Path(src_dir)

    def _is_valid_candidate(path: Path) -> bool:
        return (path / target_exe_name).is_file() and (path / "_internal").is_dir()

    if _is_valid_candidate(src_path):
        return str(src_path)

    candidates: list[Path] = []

    for root, dirs, files in os.walk(src_path):
        if target_exe_name not in files:
            continue

        root_path = Path(root)
        has_internal = "_internal" in dirs or (root_path / "_internal").is_dir()
        if has_internal and _is_valid_candidate(root_path):
            candidates.append(root_path)

    if candidates:
        candidates.sort(
            key=lambda candidate: (
                len(candidate.relative_to(src_path).parts),
                str(candidate).lower(),
            )
        )
        return str(candidates[0])

    return str(src_path)


def validate_payload_root(src_dir: Path, target_exe_name: str) -> tuple[bool, str]:
    target_exe = src_dir / target_exe_name
    if not target_exe.exists() or not target_exe.is_file():
        return False, f"Payload missing target executable: {target_exe}"

    payload_internal = src_dir / "_internal"
    if not payload_internal.exists() or not payload_internal.is_dir():
        return False, f"Payload missing required _internal directory: {payload_internal}"

    return True, "ok"


def _check_verified_update_metadata(extract_dir: Path) -> bool:
    """Check that .pmgen_verified_update.json exists and is valid.

    This is NOT a security boundary — it only catches programming mistakes.
    The real security boundary is signature verification + hash checking in updater.py.
    """
    metadata_path = extract_dir / ".pmgen_verified_update.json"
    if not metadata_path.exists():
        logger.warning("No verified update metadata found at %s", metadata_path)
        return False
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        logger.info("Verified update metadata: version=%s, sha256=%s",
                     data.get("version", "unknown"), data.get("sha256", "unknown")[:16])
        return True
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read verified update metadata: %s", e)
        return False


def setup_logging() -> None:
    """Sets up a standalone logger for the updater process."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        return

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(file_fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # In a windowed (console=False) PyInstaller build, sys.stdout is None.
    if sys.stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_fmt)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)


def _retry_delay(attempt: int) -> float:
    return min(MAX_RETRY_DELAY, INITIAL_RETRY_DELAY * (2 ** max(0, attempt)))


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if sys.platform == "win32":
        # NOTE: os.kill(pid, 0) on Windows calls TerminateProcess — it KILLS the
        # target instead of probing it. Use OpenProcess/GetExitCodeProcess instead.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def wait_for_parent_exit(parent_pid: int | None, timeout_sec: float = PARENT_WAIT_TIMEOUT) -> bool:
    if not parent_pid:
        return True

    logging.info(f"Waiting for parent process {parent_pid} to exit...")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not _is_process_running(parent_pid):
            logging.info("Parent process exited.")
            return True
        time.sleep(0.2)

    return not _is_process_running(parent_pid)


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        with open(lock_path, "r", encoding="utf-8") as lock_file:
            for line in lock_file:
                if line.startswith("pid="):
                    pid_value = line.split("=", 1)[1].strip()
                    return int(pid_value)
    except Exception:
        return None
    return None


def acquire_update_lock(dst_dir: Path, session_id: str) -> Path:
    lock_path = dst_dir / LOCK_FILE

    for attempt in range(MAX_RETRIES):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
                lock_file.write(f"pid={os.getpid()}\nsession={session_id}\nstarted={time.time()}\n")
            logging.info(f"Acquired update lock: {lock_path}")
            return lock_path
        except FileExistsError:
            owner_pid = _read_lock_pid(lock_path)
            if owner_pid is not None and not _is_process_running(owner_pid):
                logging.warning(f"Detected stale update lock from PID {owner_pid}; removing lock file.")
                try:
                    lock_path.unlink(missing_ok=True)
                    continue
                except Exception as exc:
                    logging.warning(f"Failed to remove stale lock {lock_path}: {exc}")
            wait = _retry_delay(attempt)
            logging.warning(
                f"Update lock already present ({lock_path}); retrying in {wait:.2f}s "
                f"({attempt + 1}/{MAX_RETRIES})"
            )
            time.sleep(wait)

    raise TimeoutError(f"Could not acquire update lock after {MAX_RETRIES} attempts")


def release_update_lock(lock_path: Path | None) -> None:
    if not lock_path:
        return
    try:
        if lock_path.exists():
            lock_path.unlink()
            logging.info(f"Released update lock: {lock_path}")
    except Exception as exc:
        logging.warning(f"Failed to release update lock {lock_path}: {exc}")


def _copy_with_updater_fallback(src_file: Path, dst_file: Path) -> None:
    try:
        shutil.copy2(src_file, dst_file)
    except PermissionError:
        if dst_file.name.lower() != "updater.exe" or not dst_file.exists():
            raise

        backup_path = dst_file.with_suffix(dst_file.suffix + ".old")
        if backup_path.exists():
            if backup_path.is_dir():
                shutil.rmtree(backup_path, ignore_errors=True)
            else:
                backup_path.unlink(missing_ok=True)
        os.replace(dst_file, backup_path)
        shutil.copy2(src_file, dst_file)


def _iter_source_files(src_dir: Path):
    for root, _, files in os.walk(src_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(src_dir)
        if rel_root.parts and rel_root.parts[0] == "_internal":
            continue
        for file_name in files:
            src_file = root_path / file_name
            rel_file = src_file.relative_to(src_dir)
            yield src_file, rel_file


def _is_preserved_rel_path(rel_path: Path) -> bool:
    if not rel_path.parts:
        return True

    head = rel_path.parts[0]
    if head in PRESERVED_TOP_LEVEL_NAMES:
        return True
    if head.startswith(".pmgen_backup_"):
        return True
    return False


def _collect_payload_entries(src_dir: Path) -> set[Path]:
    entries: set[Path] = set()
    for root, dirs, files in os.walk(src_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(src_dir)
        if rel_root.parts:
            entries.add(rel_root)

        for dir_name in dirs:
            entries.add((rel_root / dir_name) if rel_root.parts else Path(dir_name))

        for file_name in files:
            entries.add((rel_root / file_name) if rel_root.parts else Path(file_name))

    return entries


def _prune_stale_runtime_paths(
    src_dir: Path,
    dst_dir: Path,
    backup_dir: Path,
    created_paths: list[Path],
) -> int:
    payload_entries = _collect_payload_entries(src_dir)
    stale_files: list[tuple[Path, Path]] = []
    stale_dirs: list[tuple[Path, Path]] = []

    for root, dirs, files in os.walk(dst_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(dst_dir)

        for file_name in files:
            rel_file = (rel_root / file_name) if rel_root.parts else Path(file_name)
            if _is_preserved_rel_path(rel_file):
                continue
            if rel_file not in payload_entries:
                stale_files.append((root_path / file_name, rel_file))

        for dir_name in dirs:
            rel_dir = (rel_root / dir_name) if rel_root.parts else Path(dir_name)
            if _is_preserved_rel_path(rel_dir):
                continue
            if rel_dir not in payload_entries:
                stale_dirs.append((root_path / dir_name, rel_dir))

    deleted_backup_root = backup_dir / "deleted"
    deleted_count = 0

    for stale_abs, stale_rel in stale_files:
        backup_file = deleted_backup_root / stale_rel
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stale_abs, backup_file)
        stale_abs.unlink(missing_ok=True)
        deleted_count += 1

    for stale_abs, _ in sorted(stale_dirs, key=lambda item: len(str(item[1])), reverse=True):
        try:
            if stale_abs.exists() and stale_abs.is_dir() and not any(stale_abs.iterdir()):
                stale_abs.rmdir()
        except Exception:
            continue

    if deleted_count > 0:
        logging.info(f"Pruned {deleted_count} stale runtime files from destination.")

    return deleted_count


def _count_tree_files(root_dir: Path) -> int:
    file_count = 0
    for _, _, files in os.walk(root_dir):
        file_count += len(files)
    return file_count


def _replace_internal_tree(src_internal: Path, dst_internal: Path, backup_dir: Path) -> tuple[Path | None, int]:
    internal_backup = backup_dir / "_internal_prev"

    for attempt in range(INTERNAL_REPLACE_RETRIES):
        try:
            if internal_backup.exists():
                shutil.rmtree(internal_backup, ignore_errors=True)

            moved_old_internal = False
            if dst_internal.exists():
                os.replace(dst_internal, internal_backup)
                moved_old_internal = True

            shutil.copytree(src_internal, dst_internal)

            src_count = _count_tree_files(src_internal)
            dst_count = _count_tree_files(dst_internal)
            if src_count != dst_count:
                raise RuntimeError(
                    f"_internal file count mismatch after copy: src={src_count} dst={dst_count}"
                )

            return (internal_backup if moved_old_internal else None), dst_count

        except Exception as exc:
            wait = _retry_delay(attempt)
            logging.warning(
                f"Failed to replace _internal (attempt {attempt + 1}/{INTERNAL_REPLACE_RETRIES}): {exc}"
            )

            try:
                if dst_internal.exists():
                    shutil.rmtree(dst_internal, ignore_errors=True)
                if internal_backup.exists() and not dst_internal.exists():
                    os.replace(internal_backup, dst_internal)
            except Exception as restore_exc:
                logging.warning(f"Failed to restore previous _internal after copy failure: {restore_exc}")

            if attempt + 1 >= INTERNAL_REPLACE_RETRIES:
                raise RuntimeError("Unable to replace _internal after retries") from exc

            time.sleep(wait)

    raise RuntimeError("Unexpected _internal replacement flow")


def rollback_update(dst_dir: Path, backup_dir: Path, created_paths: list[Path], internal_backup: Path | None) -> None:
    logging.warning("Rolling back failed update...")

    if internal_backup is not None and internal_backup.exists():
        dst_internal = dst_dir / "_internal"
        logging.info("Rollback: restoring previous _internal directory.")
        if dst_internal.exists():
            shutil.rmtree(dst_internal, ignore_errors=True)
        os.replace(internal_backup, dst_internal)

    backup_files_root = backup_dir / "files"
    if backup_files_root.exists():
        logging.info("Rollback: restoring replaced runtime files.")
        for root, _, files in os.walk(backup_files_root):
            root_path = Path(root)
            for file_name in files:
                backup_file = root_path / file_name
                rel_file = backup_file.relative_to(backup_files_root)
                dst_file = dst_dir / rel_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dst_file)

    deleted_backup_root = backup_dir / "deleted"
    if deleted_backup_root.exists():
        logging.info("Rollback: restoring deleted stale runtime files.")
        for root, _, files in os.walk(deleted_backup_root):
            root_path = Path(root)
            for file_name in files:
                backup_file = root_path / file_name
                rel_file = backup_file.relative_to(deleted_backup_root)
                dst_file = dst_dir / rel_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dst_file)

    for created in sorted(created_paths, key=lambda p: len(str(p)), reverse=True):
        try:
            if created.is_file():
                created.unlink(missing_ok=True)
        except Exception:
            pass

    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        pass

    if not (dst_dir / "_internal").exists():
        logging.error("Rollback integrity check failed: destination _internal is missing.")


def install_update(src_dir: Path, dst_dir: Path, session_id: str) -> tuple[bool, str]:
    """
    Copies update files with rollback support.
    Returns (success: bool, message: str)
    """
    if not src_dir.exists():
        return False, f"Source directory does not exist: {src_dir}"

    logging.info(f"Starting copy from '{src_dir}' to '{dst_dir}'")

    backup_dir = dst_dir / f".pmgen_backup_{session_id}"
    files_backup_dir = backup_dir / "files"
    created_paths: list[Path] = []
    internal_backup: Path | None = None
    files_copied = 0

    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        files_backup_dir.mkdir(parents=True, exist_ok=True)

        _prune_stale_runtime_paths(src_dir, dst_dir, backup_dir, created_paths)

        src_internal = src_dir / "_internal"
        dst_internal = dst_dir / "_internal"
        if src_internal.exists():
            internal_backup, copied_internal_count = _replace_internal_tree(src_internal, dst_internal, backup_dir)
            files_copied += copied_internal_count

        for src_file, rel_file in _iter_source_files(src_dir):
            dst_file = dst_dir / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if dst_file.exists():
                backup_file = files_backup_dir / rel_file
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst_file, backup_file)
            else:
                created_paths.append(dst_file)

            _copy_with_updater_fallback(src_file, dst_file)
            files_copied += 1

        shutil.rmtree(backup_dir, ignore_errors=True)
        return True, f"Successfully copied {files_copied} files."

    except Exception as exc:
        try:
            rollback_update(dst_dir, backup_dir, created_paths, internal_backup)
        except Exception as rollback_exc:
            logging.error(f"Rollback failed: {rollback_exc}")
        return False, f"Copy failed: {exc}\n{traceback.format_exc()}"


def _cleanup_session_paths(src_dir_arg: Path) -> None:
    logging.info("Cleaning up temp files...")
    candidates = [src_dir_arg]

    parent = src_dir_arg.parent
    if parent.name.startswith("session_"):
        candidates.append(parent)

    for path in candidates:
        try:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        except Exception as exc:
            logging.warning(f"Failed to remove temp path {path}: {exc}")


def _relaunch_app(dst_dir: Path, target_exe_name: str) -> None:
    """Best-effort relaunch of the application (new version or rolled-back previous one)."""
    target_exe_path = dst_dir / target_exe_name
    if not target_exe_path.exists():
        logging.error(f"Target executable not found for relaunch: {target_exe_path}")
        return
    try:
        subprocess.Popen([str(target_exe_path)], cwd=str(dst_dir), close_fds=True)
        logging.info("Relaunch successful.")
    except Exception as exc:
        logging.error(f"Failed to relaunch app: {exc}")


def main() -> None:
    setup_logging()
    logging.info("=" * 60)
    logging.info(f"Updater Started. PID: {os.getpid()}")
    logging.info(f"Arguments: {sys.argv}")

    # Expected: [script_path, src_dir, dst_dir, exe_name, parent_pid?, session_id?]
    if len(sys.argv) < 4:
        logging.error("Not enough arguments provided. Exiting.")
        logging.error(f"Received: {sys.argv}")
        return

    src_dir_arg = Path(sys.argv[1]).resolve()
    dst_dir = Path(sys.argv[2]).resolve()
    target_exe_name = sys.argv[3]

    parent_pid = None
    if len(sys.argv) >= 5:
        try:
            parent_pid = int(sys.argv[4])
        except (TypeError, ValueError):
            parent_pid = None

    session_id = sys.argv[5] if len(sys.argv) >= 6 and sys.argv[5] else str(int(time.time()))

    # Wait for the parent to exit BEFORE validating, so every failure path below
    # can safely relaunch the app without creating a duplicate instance.
    if not wait_for_parent_exit(parent_pid):
        logging.error("Parent process did not exit within timeout; aborting update.")
        return

    resolved_src_dir = Path(resolve_payload_root(str(src_dir_arg), target_exe_name)).resolve()
    logging.info(f"Resolved payload source directory: {resolved_src_dir}")

    payload_ok, payload_msg = validate_payload_root(resolved_src_dir, target_exe_name)
    if not payload_ok:
        logging.error(f"Invalid update payload: {payload_msg}")
        _relaunch_app(dst_dir, target_exe_name)
        return

    if not _check_verified_update_metadata(resolved_src_dir):
        logger.warning("Verified update metadata check failed; continuing install anyway")

    lock_path = None
    should_relaunch = True
    try:
        try:
            lock_path = acquire_update_lock(dst_dir, session_id)
        except TimeoutError as exc:
            # Another live updater owns this install; let it handle the relaunch.
            logging.critical(f"Could not acquire update lock: {exc}")
            should_relaunch = False
            return

        success = False
        for attempt in range(MAX_RETRIES):
            logging.info(f"Attempt {attempt + 1}/{MAX_RETRIES} to install update...")
            success, msg = install_update(resolved_src_dir, dst_dir, session_id)
            if success:
                logging.info(msg)
                break

            wait = _retry_delay(attempt)
            logging.warning(f"Attempt failed: {msg}")
            logging.info(f"Waiting {wait:.2f}s for files to unlock...")
            time.sleep(wait)

        if success:
            _cleanup_session_paths(src_dir_arg)
        else:
            logging.critical("Update failed after all retries; relaunching previous version.")
    finally:
        release_update_lock(lock_path)
        if should_relaunch:
            _relaunch_app(dst_dir, target_exe_name)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if os.path.exists(LOG_DIR):
            with open(LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(f"\nCRITICAL CRASH: {exc}\n{traceback.format_exc()}\n")
