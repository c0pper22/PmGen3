import hashlib
import zipfile
from pathlib import Path

from pmgen.updater import updater
from pmgen.updater import run_update


def test_parse_checksum_text_accepts_common_formats():
    assert (
        updater._parse_checksum_text(
            "d2d2f9f172f5f1f30d7e8c42639d3235f5f6c6e79f1f8d06ec3f438f0f5b31aa  PmGen.zip"
        )
        == "d2d2f9f172f5f1f30d7e8c42639d3235f5f6c6e79f1f8d06ec3f438f0f5b31aa"
    )
    assert (
        updater._parse_checksum_text(
            "SHA256: D2D2F9F172F5F1F30D7E8C42639D3235F5F6C6E79F1F8D06EC3F438F0F5B31AA"
        )
        == "d2d2f9f172f5f1f30d7e8c42639d3235f5f6c6e79f1f8d06ec3f438f0f5b31aa"
    )


def test_parse_checksum_text_returns_none_when_missing_hash():
    assert updater._parse_checksum_text("no hash here") is None


def test_safe_extract_zip_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "update.zip"
    with zipfile.ZipFile(zip_path, "w") as handle:
        handle.writestr("../escape.txt", "bad")

    output_dir = tmp_path / "extract"
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as handle:
        try:
            updater._safe_extract_zip(handle, output_dir, lambda _: None)
            assert False, "Expected ValueError for unsafe zip member path"
        except ValueError as exc:
            assert "Unsafe path" in str(exc)


def test_download_update_emits_zip_path_after_checksum_validation(tmp_path, monkeypatch):
    payload = b"fake zip bytes"
    expected_checksum = hashlib.sha256(payload).hexdigest()
    session_dir = tmp_path / "session"

    class FakeResponse:
        def __init__(self, body: bytes = b"", text: str = ""):
            self.body = body
            self.text = text
            self.headers = {"content-length": str(len(body))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield self.body

    def fake_get(url, **_kwargs):
        if url.endswith(updater.CHECKSUM_SUFFIX):
            return FakeResponse(text=f"{expected_checksum}  {updater.ASSET_NAME}")
        return FakeResponse(body=payload)

    def fake_session_dir():
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    monkeypatch.setattr(updater, "_new_update_session_dir", fake_session_dir)
    monkeypatch.setattr(updater.requests, "get", fake_get)

    worker = updater.UpdateWorker()
    finished = []
    errors = []
    progress = []
    worker.download_finished.connect(finished.append)
    worker.error_occurred.connect(errors.append)
    worker.download_progress.connect(progress.append)

    worker.download_update("https://example.test/PmGen.zip")

    zip_path = session_dir / updater.ASSET_NAME
    assert finished == [str(zip_path)]
    assert errors == []
    assert progress == [100]
    assert zip_path.read_bytes() == payload


def test_resolve_payload_root_finds_nested_target(tmp_path):
    src_root = tmp_path / "source"
    nested = src_root / "PmGen-2.0" / "bin"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "PmGen.exe").write_text("exe", encoding="utf-8")
    (nested / "_internal").mkdir(parents=True, exist_ok=True)

    resolved = run_update.resolve_payload_root(str(src_root), "PmGen.exe")
    assert Path(resolved).resolve() == nested.resolve()


def test_resolve_payload_root_prefers_candidate_with_internal(tmp_path):
    src_root = tmp_path / "source"
    bad = src_root / "A" / "bin"
    good = src_root / "B" / "bin"

    bad.mkdir(parents=True, exist_ok=True)
    good.mkdir(parents=True, exist_ok=True)

    (bad / "PmGen.exe").write_text("exe-bad", encoding="utf-8")
    (good / "PmGen.exe").write_text("exe-good", encoding="utf-8")
    (good / "_internal").mkdir(parents=True, exist_ok=True)

    resolved = run_update.resolve_payload_root(str(src_root), "PmGen.exe")
    assert Path(resolved).resolve() == good.resolve()


def test_install_update_rolls_back_when_copy_fails(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (src_dir / "_internal" / "runtime.txt").write_text("new-runtime", encoding="utf-8")

    (src_dir / "existing.txt").write_text("new-existing", encoding="utf-8")
    (src_dir / "newfile.txt").write_text("new-file", encoding="utf-8")

    (dst_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (dst_dir / "_internal" / "runtime.txt").write_text("old-runtime", encoding="utf-8")
    (dst_dir / "existing.txt").write_text("old-existing", encoding="utf-8")

    def fixed_iter_source_files(_src_dir):
        yield src_dir / "existing.txt", Path("existing.txt")
        yield src_dir / "newfile.txt", Path("newfile.txt")

    monkeypatch.setattr(run_update, "_iter_source_files", fixed_iter_source_files)

    original_copy = run_update._copy_with_updater_fallback
    copy_count = {"value": 0}

    def flaky_copy(src_file, dst_file):
        copy_count["value"] += 1
        if copy_count["value"] == 2:
            raise PermissionError("simulated lock")
        return original_copy(src_file, dst_file)

    monkeypatch.setattr(run_update, "_copy_with_updater_fallback", flaky_copy)

    success, _ = run_update.install_update(src_dir, dst_dir, "testsession")

    assert success is False
    assert (dst_dir / "existing.txt").read_text(encoding="utf-8") == "old-existing"
    assert not (dst_dir / "newfile.txt").exists()
    assert (dst_dir / "_internal" / "runtime.txt").read_text(encoding="utf-8") == "old-runtime"


def test_install_update_prunes_stale_runtime_files(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (src_dir / "_internal" / "runtime.txt").write_text("new-runtime", encoding="utf-8")
    (src_dir / "PmGen.exe").write_text("new-exe", encoding="utf-8")
    (src_dir / "current.txt").write_text("new-current", encoding="utf-8")

    (dst_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (dst_dir / "_internal" / "runtime.txt").write_text("old-runtime", encoding="utf-8")
    (dst_dir / "current.txt").write_text("old-current", encoding="utf-8")
    (dst_dir / "stale_old_module.py").write_text("stale", encoding="utf-8")
    (dst_dir / "catalog_manager.db").write_text("user-db", encoding="utf-8")

    success, _ = run_update.install_update(src_dir, dst_dir, "prune-session")

    assert success is True
    assert not (dst_dir / "stale_old_module.py").exists()
    assert (dst_dir / "catalog_manager.db").exists()
    assert (dst_dir / "current.txt").read_text(encoding="utf-8") == "new-current"


def test_install_update_rolls_back_when_internal_replace_fails(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (src_dir / "_internal" / "runtime.txt").write_text("new-runtime", encoding="utf-8")
    (src_dir / "PmGen.exe").write_text("new-exe", encoding="utf-8")

    (dst_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (dst_dir / "_internal" / "runtime.txt").write_text("old-runtime", encoding="utf-8")
    (dst_dir / "PmGen.exe").write_text("old-exe", encoding="utf-8")

    def always_fail_copytree(*_args, **_kwargs):
        raise PermissionError("simulated _internal lock")

    monkeypatch.setattr(run_update.shutil, "copytree", always_fail_copytree)

    success, _ = run_update.install_update(src_dir, dst_dir, "internal-fail")

    assert success is False
    assert (dst_dir / "_internal" / "runtime.txt").read_text(encoding="utf-8") == "old-runtime"
    assert (dst_dir / "PmGen.exe").read_text(encoding="utf-8") == "old-exe"


def test_validate_payload_root_requires_exe_and_internal(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir(parents=True, exist_ok=True)

    ok, _ = run_update.validate_payload_root(payload, "PmGen.exe")
    assert ok is False

    (payload / "PmGen.exe").write_text("exe", encoding="utf-8")
    ok, _ = run_update.validate_payload_root(payload, "PmGen.exe")
    assert ok is False

    (payload / "_internal").mkdir(parents=True, exist_ok=True)
    ok, _ = run_update.validate_payload_root(payload, "PmGen.exe")
    assert ok is True
