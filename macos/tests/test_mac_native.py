import errno
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/python"))
from dashboard_sync_server import SyncJobs, _safe_relative
from mac_app_backend import validate_roots


class MacNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.local, self.nas = self.root / "local", self.root / "nas"
        self.local.mkdir(); self.nas.mkdir()
        self.jobs = SyncJobs(self.local, self.nas, self.root / "cache/dashboard.html")

    def test_unsafe_paths_rejected(self):
        for value in ("/tmp/file", "../outside", "C:\\Users\\x", "08_Indexes/a", ".git/config", "\\\\server\\share"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _safe_relative(value)

    def test_overlapping_roots_rejected(self):
        for nas in (self.local, self.local / "sub", self.root):
            with self.assertRaises(ValueError):
                validate_roots(str(self.local), str(nas))

    def test_safe_copy_never_overwrites(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_text("new"); target.write_text("existing")
        with self.assertRaises(RuntimeError):
            self.jobs._copy_one({"source": source, "target": target}, "safe")
        self.assertEqual(target.read_text(), "existing")

    def test_safe_copy_detects_concurrent_target(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_bytes(b"a" * 100)
        def race(_delta):
            target.write_text("concurrent")
        with self.assertRaises(RuntimeError):
            self.jobs._copy_one({"source": source, "target": target}, "safe", race)
        self.assertEqual(target.read_text(), "concurrent")

    def test_overwrite_rejects_changed_source(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_text("new"); target.write_text("keep")
        def change(_delta):
            source.write_text("source changed")
        with self.assertRaises(RuntimeError):
            self.jobs._copy_one({"source": source, "target": target}, "overwrite", change)
        self.assertEqual(target.read_text(), "keep")

    def test_smb_metadata_failure_does_not_lose_content(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_text("content")
        with patch("dashboard_sync_server.shutil.copystat", side_effect=OSError(errno.ENOTSUP, "SMB")):
            self.jobs._copy_one({"source": source, "target": target}, "safe")
        self.assertEqual(target.read_text(), "content")

    def test_link_parent_cannot_escape(self):
        outside = self.root / "outside"; outside.mkdir()
        (self.nas / "link").symlink_to(outside, target_is_directory=True)
        source = self.local / "a"; source.write_text("x")
        with self.assertRaises(RuntimeError):
            self.jobs._copy_one({"source": source, "target": self.nas / "link/a"}, "safe")
        self.assertFalse((outside / "a").exists())

    def test_local_diary_preserved_before_nas_pull(self):
        relative = "09_System/SystemLog/WorkspaceOS/day.log"
        local, nas = self.local / relative, self.nas / relative
        local.parent.mkdir(parents=True); nas.parent.mkdir(parents=True)
        local.write_text("local unique notes"); nas.write_text("NAS authoritative")
        self.jobs._pull_obsidian_log_to_local(str(nas))
        self.assertEqual(local.read_text(), nas.read_text())
        self.assertEqual(Path(self.jobs.last_preserved_log).read_text(), "local unique notes")

    def test_sync_log_uses_systemlog_not_obsidian(self):
        path = Path(self.jobs._append_obsidian_sync_log({"direction": "to_nas"}, ["example.txt"]))
        self.assertEqual(path.parent, self.nas / "09_System/SystemLog/WorkspaceOS")
        self.assertEqual(path.suffix, ".log")
        first = path.read_bytes()
        self.jobs._append_obsidian_sync_log({"direction": "to_nas"}, ["second.txt"])
        self.assertTrue(path.read_bytes().startswith(first))
        local = Path(self.jobs._pull_obsidian_log_to_local(str(path)))
        self.assertEqual(local.parent, self.local / "09_System/SystemLog/WorkspaceOS")
        self.assertFalse((self.local / "02_Knowledge").exists())
        self.assertFalse((self.nas / "02_Knowledge").exists())

    def test_file_open_uses_mac_parent(self):
        source = self.local / "a"; source.write_text("x")
        with patch("dashboard_sync_server.subprocess.Popen") as opener:
            self.jobs.open_folder("computer", "a")
            self.assertEqual(opener.call_args.args[0], ["open", str(self.local)])

    def test_jobs_survive_restart_as_interrupted(self):
        self.jobs.jobs["test"] = {"id": "test", "status": "running"}
        with self.jobs.lock:
            self.jobs._persist_jobs_locked(force=True)
        reloaded = SyncJobs(self.local, self.nas, self.jobs.dashboard)
        self.assertEqual(reloaded.status("test")["status"], "interrupted")

    def test_smb_fallback_preserves_concurrent_existing_file(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_text("new")
        def unsupported(*args, **kwargs):
            target.write_text("other writer")
            raise OSError(errno.ENOTSUP, "SMB")
        with patch("dashboard_sync_server.ctypes.CDLL", side_effect=OSError("unsupported")), \
             patch("dashboard_sync_server.os.link", side_effect=unsupported):
            with self.assertRaises(FileExistsError):
                self.jobs._copy_one({"source": source, "target": target}, "safe")
        self.assertEqual(target.read_text(), "other writer")

    def test_smb_fallback_copy_and_failure_cleanup(self):
        source, target = self.local / "a", self.nas / "a"
        source.write_text("verified")
        with patch("dashboard_sync_server.ctypes.CDLL", side_effect=OSError("unsupported")), \
             patch("dashboard_sync_server.os.link", side_effect=OSError(errno.ENOTSUP, "SMB")):
            self.jobs._copy_one({"source": source, "target": target}, "safe")
            self.assertEqual(target.read_text(), "verified")
            failed = self.nas / "failure"
            with patch("dashboard_sync_server.shutil.copyfileobj", side_effect=OSError("disconnected")):
                with self.assertRaises(OSError):
                    self.jobs._copy_one({"source": source, "target": failed}, "safe")
            self.assertFalse(failed.exists())

    def test_finder_metadata_is_not_a_user_conflict(self):
        from location_snapshot import build_location_snapshot
        (self.local / ".DS_Store").write_text("Mac Finder data")
        (self.nas / ".DS_Store").write_text("other device")
        snapshot = build_location_snapshot(self.local, self.nas)
        self.assertFalse(any(f["relative"] == ".DS_Store" for f in snapshot["files"]))

    def test_explicit_refresh_publishes_both_dashboards(self):
        result = self.jobs.refresh_snapshot(live_nas=True)
        self.assertTrue(result["published"])
        self.assertEqual((self.local / "08_Indexes/file-locations.html").read_bytes(),
                         (self.nas / "08_Indexes/file-locations.html").read_bytes())
