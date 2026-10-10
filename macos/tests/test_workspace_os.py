from __future__ import annotations

import csv
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts" / "python"
sys.path.insert(0, str(TOOLS))

import backup as backup_module
from audit import audit_workspace
from alert_center import build_alert_center, save_alert_center
from backup import apply_retention, create_snapshot, restore_snapshot, set_snapshot_pin, verify_snapshot
from backup_media import export_snapshot_to_media, initialize_backup_media
from classifier import classify_file
from change_guard import run_change_guard
from config import load_config
from device_bundle import export_device_bundle, import_device_bundle, verify_device_bundle
from duplicate_finder import find_duplicates, sha256_file
from device_sync import (
    apply_source_only_handoff,
    build_device_manifest,
    build_sync_receipt,
    compare_device_manifests,
    load_device_manifest,
    save_json_atomic,
)
from dashboard_sync_server import SyncJobs
from distribution import build_distribution, verify_distribution
from evidence_chain import append_evidence_record, verify_evidence_chain
from health import save_health, workspace_health
from graph_builder import build_workspace_graph, save_workspace_graph
from index_builder import build_index
from location_snapshot import build_location_snapshot, save_location_snapshot
from maintenance_audit import audit_maintenance_tasks, save_maintenance_audit
from macos_package import build as build_macos_package, verify as verify_macos_package
from notification_center import build_notification_bundle
from operations_drill import run_operations_history_drill
from operations_history import append_operations_record, verify_operations_history
from recovery_readiness import build_recovery_readiness, save_recovery_readiness
from recovery_kit import apply_recovery_kit_retention, build_recovery_kit, verify_recovery_kit
from release_verify import latest_pointer_check, package_content_check, python_compile_check
from portable_package import verify as verify_portable_package
from restore_drill import run_restore_drill
from release_builder import build_release, write_manifest
from search_engine import (
    build_search_database,
    check_search_database,
    maintain_search_database,
    search_database,
    search_status,
)
from security_audit import audit_security, save_security_audit
from security_posture import evaluate_security_posture, save_security_posture
from version_detector import detect_latest, parse_version, scan_latest
from workspace_core import WORKSPACE_LAYOUT, _safe_target, init_workspace, new_project, scan_inbox


class WorkspaceOSTest(unittest.TestCase):
    def setUp(self):
        # macOS /var is a symlink to /private/var. Match the canonical paths
        # returned by production safety checks, including filesystem mocks.
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.base = Path(self.temp.name) / "中文 空格" / "Workspace"

    def tearDown(self): self.temp.cleanup()

    def test_release_verify_checks_portable_entrypoints_and_wpf_hash(self):
        source = Path(self.temp.name) / "WorkspaceOS-ControlCenter-WPF.ps1"
        source.write_text("Write-Output 'test'\n", encoding="utf-8")
        archive = Path(self.temp.name) / "portable.zip"
        root = "WorkspaceOS-test/"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(root + "WorkspaceOS.cmd", "@echo off")
            bundle.writestr(root + "docs/verification-matrix.md", "1,097")
            bundle.writestr(root + "docs/completion-audit.md", "仍需真实环境完成 Restic；没有被模拟结果替代")
            bundle.writestr(root + "scripts/python/workspace_cli.py", "")
            bundle.writestr(root + "scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1", source.read_bytes())
            bundle.writestr(root + "scripts/python/release_verify.py", "")
        result = package_content_check(archive, source)
        self.assertTrue(result["passed"])
        source.write_text("tampered\n", encoding="utf-8")
        self.assertFalse(package_content_check(archive, source)["passed"])

        source.write_text("Write-Output 'test'\n", encoding="utf-8")
        unsafe_archive = Path(self.temp.name) / "unsafe.zip"
        with zipfile.ZipFile(unsafe_archive, "w") as bundle:
            for name in (
                "WorkspaceOS-test/WorkspaceOS.cmd",
                "WorkspaceOS-test/docs/verification-matrix.md",
                "WorkspaceOS-test/docs/completion-audit.md",
                "WorkspaceOS-test/scripts/python/workspace_cli.py",
                "WorkspaceOS-test/scripts/python/release_verify.py",
                "WorkspaceOS-test/scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1",
            ):
                payload = source.read_bytes() if name.endswith(".ps1") else (
                    "仍需真实环境完成 Restic；没有被模拟结果替代"
                    if name.endswith("completion-audit.md") else ""
                )
                bundle.writestr(name, payload)
            bundle.writestr("WorkspaceOS-test/secrets/credentials.txt", "not allowed")
        unsafe = package_content_check(unsafe_archive, source)
        self.assertFalse(unsafe["passed"])
        self.assertTrue(unsafe["forbidden"])

    def test_release_verify_python_compile_is_read_only(self):
        source_dir = Path(self.temp.name) / "python"
        source_dir.mkdir()
        (source_dir / "ok.py").write_text("value = 1\n", encoding="utf-8")
        result = python_compile_check(source_dir)
        self.assertTrue(result["passed"])
        self.assertEqual(result["checked_files"], 1)
        self.assertFalse((source_dir / "__pycache__").exists())

    def test_portable_package_rejects_invalid_privacy_declaration(self):
        archive = Path(self.temp.name) / "invalid-privacy.zip"
        manifest = {
            "privacy": {"user_data": True, "credentials": False},
            "files": [],
        }
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("WorkspaceOS-test/PORTABLE-MANIFEST.json", json.dumps(manifest))
        result = verify_portable_package(archive)
        self.assertFalse(result["valid"])
        self.assertIn("PRIVACY_DECLARATION_INVALID", {item["code"] for item in result["issues"]})

    def test_release_verify_validates_latest_pointer_hash(self):
        package = Path(self.temp.name) / "release.zip"
        package.write_bytes(b"release")
        pointer = Path(self.temp.name) / "LATEST.json"
        pointer.write_text(json.dumps({"package": package.name, "sha256": hashlib.sha256(b"release").hexdigest()}), encoding="utf-8")
        self.assertTrue(latest_pointer_check(pointer)["passed"])
        pointer.write_text(json.dumps({"package": package.name, "sha256": "0" * 64}), encoding="utf-8")
        self.assertFalse(latest_pointer_check(pointer)["passed"])

    def test_init_creates_full_layout_and_chinese_space_path(self):
        init_workspace(self.base)
        for top, children in WORKSPACE_LAYOUT.items():
            self.assertTrue((self.base / top / "README.md").is_file())
            for child in children: self.assertTrue((self.base / top / child).is_dir())

    def test_init_dry_run_does_not_modify(self):
        result = init_workspace(self.base, dry_run=True)
        self.assertTrue(result["operations"]); self.assertFalse(self.base.exists())

    def test_unc_share_root_is_valid_target(self):
        target = _safe_target(r"\\server\Workspace")
        self.assertTrue(str(target).startswith(r"\\server\Workspace"))

    def test_macos_control_center_matches_windows_core_actions(self):
        source = (ROOT / "scripts" / "macos" / "workspace_os_control_center.py").read_text(encoding="utf-8")
        for label in (
            "初始化工作区", "整理收件箱", "执行收件箱整理", "打开网页版",
            "搜索资料", "更新搜索索引", "快照预览", "创建快照",
            "系统健康检查", "安全检查", "提醒与告警", "恢复状态",
            "恢复到新文件夹", "打开工作区", "使用说明", "NAS 设置",
        ):
            self.assertIn(label, source)
        self.assertIn("dashboard_sync_server.py", source)
        self.assertIn("Application Support", source)
        self.assertIn("/Volumes/Workspace", source)

    def test_macos_portable_package_is_complete_and_verified(self):
        destination = Path(self.temp.name) / "macos-package"
        result = build_macos_package(ROOT, destination)
        archive = Path(result["archive"])
        self.assertTrue(archive.is_file())
        self.assertTrue(Path(result["checksum"]).is_file())
        self.assertTrue(result["verification"]["valid"])
        verified = verify_macos_package(archive)
        self.assertTrue(verified["valid"])
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            launcher = next(name for name in names if name.endswith("Workspace OS.app/Contents/MacOS/WorkspaceOS"))
            manifest = next(name for name in names if name.endswith("MACOS-MANIFEST.json"))
            self.assertTrue(((bundle.getinfo(launcher).external_attr >> 16) & 0o111) != 0)
            metadata = json.loads(bundle.read(manifest).decode("utf-8"))
            self.assertFalse(metadata["privacy"]["user_data"])
            self.assertFalse(metadata["privacy"]["credentials"])

    def test_project_creation_and_no_overwrite(self):
        init_workspace(self.base); new_project("software", "演示 Project", self.base)
        project = self.base / "01_Projects" / "Work" / "Active" / "演示 Project"
        self.assertIn("演示 Project", (project / "README.md").read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError): new_project("software", "演示 Project", self.base)

    def test_project_dry_run(self):
        init_workspace(self.base); new_project("ai", "Dry", self.base, dry_run=True)
        self.assertFalse((self.base / "01_Projects" / "Work" / "Active" / "Dry").exists())

    def test_personal_project_space(self):
        init_workspace(self.base); new_project("video", "生活视频", self.base, space="personal")
        self.assertTrue((self.base / "01_Projects" / "Personal" / "Active" / "生活视频" / "footage").is_dir())

    def test_version_parsing(self):
        item = parse_version("Demo_2026-07-22_v1.2.3_APPROVED.zip")
        self.assertEqual(item["version"], (1, 2, 3)); self.assertEqual(item["status"], "APPROVED"); self.assertEqual(item["date"], "2026-07-22")
        self.assertEqual(parse_version("cut_v001_REVIEW.mp4")["version"], (1, 0, 0))

    def test_latest_selection_excludes_proxy(self):
        items = ["work/Demo_v2.0_DRAFT.zip", "release/Demo_v1.5_RELEASE.zip", "proxies/Demo_v9.0_RELEASE.mp4"]
        result = detect_latest(items)
        self.assertIn("v1.5", result["formal_latest"]["version_text"])
        self.assertIn("v2.0", result["working_latest"]["version_text"])

    def test_hash_and_duplicates(self):
        self.base.mkdir(parents=True); (self.base / "a.bin").write_bytes(b"same"); (self.base / "b.bin").write_bytes(b"same"); (self.base / "c.bin").write_bytes(b"other")
        self.assertEqual(len(sha256_file(self.base / "a.bin")), 64)
        groups = find_duplicates(self.base); self.assertEqual(groups[0]["file_count"], 2)

    def test_inbox_dry_run_and_apply_rollback_log(self):
        init_workspace(self.base); source = self.base / "00_Inbox" / "ToSort" / "photo.jpg"; source.write_bytes(b"jpg")
        preview = scan_inbox(self.base); self.assertTrue(source.exists()); self.assertEqual(preview["mode"], "dry-run")
        applied = scan_inbox(self.base, apply=True); self.assertFalse(source.exists()); self.assertTrue(Path(applied["rollback_log"]).is_file())

    def test_classifier_metadata_only(self):
        self.base.mkdir(parents=True); file = self.base / "sample.mp4"; file.write_bytes(b"video")
        result = classify_file(file); self.assertEqual(result["privacy_mode"], "metadata-only"); self.assertIn("Video", result["suggested_target"])

    def test_config_load(self):
        path = Path(self.temp.name) / "配置.yaml"; path.write_text("privacy_mode: local-only\npaths:\n  windows: 'D:\\\\My Workspace'\n", encoding="utf-8")
        data = load_config(path); self.assertEqual(data["privacy_mode"], "local-only"); self.assertIn("windows", data["paths"])

    def test_index_generation(self):
        init_workspace(self.base); f = self.base / "02_Knowledge" / "Notes" / "Demo_v0.2_DRAFT.md"; f.write_text("hello", encoding="utf-8")
        index = build_index(self.base); record = next(x for x in index["files"] if x["name"] == f.name)
        self.assertEqual(record["version"], "v0.2"); self.assertEqual(record["status"], "DRAFT")

    def test_release_manifest(self):
        release = Path(self.temp.name) / "release"; release.mkdir(); (release / "app.zip").write_bytes(b"release")
        manifest, sums = write_manifest(release, "v1.0.0")
        data = json.loads(manifest.read_text(encoding="utf-8")); self.assertEqual(data["release_version"], "v1.0.0"); self.assertIn("app.zip", sums.read_text(encoding="utf-8"))

    def test_audit_forbidden_name(self):
        init_workspace(self.base); bad = self.base / "02_Knowledge" / "Notes" / "报告_最终版.docx"; bad.write_bytes(b"x")
        report = audit_workspace(self.base, check_duplicates=False)
        self.assertTrue(any(x["code"] == "FORBIDDEN_NAME" for x in report["findings"]))

    def test_audit_avoids_library_and_build_release_false_positives(self):
        init_workspace(self.base)
        project = self.base / "01_Projects" / "Work" / "Active" / "Client" / "Demo"
        (project / "src" / "cryptlib" / "release").mkdir(parents=True)
        (project / "src" / "Newtonsoft.Json.dll").write_bytes(b"dll")
        (project / "README.md").write_text("# Demo", encoding="utf-8")
        (project / "STATUS.md").write_text("当前状态：`ACTIVE`", encoding="utf-8")
        (project / "src" / "cryptlib" / "release" / "build.lib").write_bytes(b"lib")
        report = audit_workspace(self.base, check_duplicates=False)
        noisy = [item for item in report["findings"] if "Newtonsoft" in item["path"] or "cryptlib" in item["path"]]
        self.assertEqual(noisy, [])

    def test_cli_help(self):
        result = subprocess.run([sys.executable, str(TOOLS / "workspace_cli.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0); self.assertIn("scan-inbox", result.stdout)

    def test_location_snapshot_states_and_html(self):
        computer = Path(self.temp.name) / "computer"; nas = Path(self.temp.name) / "nas"
        computer.mkdir(); nas.mkdir()
        (computer / "same.txt").write_text("same", encoding="utf-8"); (nas / "same.txt").write_text("same", encoding="utf-8")
        (computer / "local.txt").write_text("local", encoding="utf-8"); (nas / "remote.txt").write_text("remote", encoding="utf-8")
        (computer / "conflict.txt").write_text("A", encoding="utf-8"); (nas / "conflict.txt").write_text("B", encoding="utf-8")
        (computer / "01_Projects" / "Work" / "Active").mkdir(parents=True); (nas / "01_Projects" / "Work" / "Active").mkdir(parents=True)
        (computer / ".workspace-os.json").write_text("local", encoding="utf-8"); (nas / ".workspace-os.json").write_text("nas", encoding="utf-8")
        devices = computer / "08_Indexes" / "Devices"
        devices.mkdir(parents=True)
        (devices / "local-device-manifest.json").write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "device_id": "test-device",
            "status": "ready",
            "file_count": 4,
            "total_bytes": 4,
            "inventory_sha256": "abc",
            "scopes": ["02_Knowledge"],
        }), encoding="utf-8")
        (devices / "device-sync-status.json").write_text(json.dumps({
            "status": "verified",
            "safe_to_switch_primary_device": True,
        }), encoding="utf-8")
        (devices / "device-apply-status.json").write_text(json.dumps({
            "status": "verified",
            "copied_files": 2,
            "overwritten_files": 0,
            "deleted_files": 0,
        }), encoding="utf-8")
        evidence = computer / "08_Indexes" / "Evidence"
        evidence.mkdir(parents=True)
        (evidence / "status.json").write_text(json.dumps({
            "checked_at": "2099-01-01T00:00:00+00:00",
            "status": "valid",
            "valid": True,
            "record_count": 3,
            "latest_sequence": 3,
            "latest_hash": "abc",
            "issues": [],
        }), encoding="utf-8")
        operations = computer / "08_Indexes" / "Operations"
        operations.mkdir(parents=True)
        (operations / "operations-history-status.json").write_text(json.dumps({
            "checked_at": "2099-01-01T00:00:00+00:00",
            "status": "valid",
            "valid": True,
            "record_count": 4,
            "latest_sequence": 4,
            "issues": [],
        }), encoding="utf-8")
        (operations / "operational-slo.json").write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "status": "insufficient-data",
            "window_days": 30,
            "sample_days": 4,
            "current_failed_signals": [],
            "metrics": {},
            "findings": [],
        }), encoding="utf-8")
        operations_drill = computer / "08_Indexes" / "OperationsDrills"
        operations_drill.mkdir(parents=True)
        (operations_drill / "latest-operations-history-drill.json").write_text(
            json.dumps({
                "completed_at": "2099-01-01T00:00:00+00:00",
                "result": "passed",
                "synthetic_record_count": 8,
                "gates": {"tamper_detected": True},
            }),
            encoding="utf-8",
        )
        security = computer / "08_Indexes" / "Security"
        security.mkdir(parents=True)
        (security / "acl-hardening.json").write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "status": "unchanged",
            "backup_root": None,
            "summary": {
                "existing": 3,
                "changes_required": 0,
                "verified": 3,
                "content_overwrites": 0,
                "content_deletions": 0,
            },
        }), encoding="utf-8")
        snapshot = build_location_snapshot(computer, nas)
        states = {x["relative"]: x["state"] for x in snapshot["files"]}
        self.assertEqual(states["same.txt"], "BOTH_SAME"); self.assertEqual(states["local.txt"], "COMPUTER_ONLY")
        self.assertEqual(states["remote.txt"], "NAS_ONLY"); self.assertEqual(states["conflict.txt"], "CONFLICT")
        self.assertNotIn(".workspace-os.json", states)
        self.assertTrue(snapshot["computer_storage"]["available"])
        self.assertTrue(snapshot["nas_storage"]["available"])
        self.assertEqual(snapshot["schema_version"], "2.8")
        self.assertEqual(snapshot["device_manifest"]["device_id"], "test-device")
        self.assertEqual(snapshot["device_sync_status"]["status"], "verified")
        self.assertEqual(snapshot["device_apply_status"]["copied_files"], 2)
        self.assertEqual(snapshot["evidence_chain"]["record_count"], 3)
        self.assertEqual(snapshot["operations"]["history"]["record_count"], 4)
        self.assertEqual(snapshot["operations"]["slo"]["sample_days"], 4)
        self.assertEqual(snapshot["operations"]["drill"]["result"], "passed")
        self.assertEqual(snapshot["acl_hardening"]["status"], "unchanged")
        directory_states = {x["relative"]: (x["computer"], x["nas"]) for x in snapshot["directories"]}
        self.assertEqual(directory_states["01_Projects/Work/Active"], (True, True))
        output, data = save_location_snapshot(snapshot, Path(self.temp.name) / "locations.html")
        dashboard = output.read_text(encoding="utf-8")
        self.assertIn("NEXUS | Workspace OS 2.0", dashboard)
        self.assertIn("数字资产中枢", dashboard)
        self.assertIn('class="nexus-logo"', dashboard)
        self.assertRegex(dashboard, r"快照更新于 <span>\d{4}-\d{2}-\d{2}</span>")
        self.assertIn("'00_Inbox':'收件箱'", dashboard)
        self.assertIn("Active:'进行中'", dashboard)
        self.assertIn("displayPath(f.relative)", dashboard)
        self.assertIn('id="storage"', dashboard)
        self.assertIn('id="type"', dashboard)
        self.assertIn('id="sort"', dashboard)
        self.assertIn('data-page="usage"', dashboard)
        self.assertIn('data-page="install"', dashboard)
        self.assertIn('data-page="shares"', dashboard)
        self.assertIn('data-page="compare"', dashboard)
        self.assertIn('id="page-compare"', dashboard)
        self.assertIn('id="compare-grid"', dashboard)
        self.assertIn('id="compare-category"', dashboard)
        self.assertIn('data-sync-one-overwrite', dashboard)
        self.assertIn("状态 / 操作", dashboard)
        self.assertIn('id="task-center"', dashboard)
        self.assertIn("后台任务中心", dashboard)
        self.assertIn("taskHistory", dashboard)
        self.assertIn("syncToast", dashboard)
        self.assertIn("已开始", dashboard)
        self.assertIn("tasksLoaded", dashboard)
        self.assertIn("compactTasks", dashboard)
        self.assertIn("taskKey", dashboard)
        self.assertNotIn("const refreshed=(data.jobs||[]).find", dashboard)
        self.assertIn("compare-dir-tree", dashboard)
        self.assertIn("compare-file", dashboard)
        self.assertIn("renderCompareFileRow", dashboard)
        self.assertIn('id="compare-collapse"', dashboard)
        self.assertIn('id="compare-expand"', dashboard)
        self.assertIn("dir-direct-diff", dashboard)
        self.assertIn("dir-child-diff", dashboard)
        self.assertIn("renderCompareDirectoryNodes", dashboard)
        self.assertIn("renderCompareChildren", dashboard)
        self.assertIn("data-compare-node", dashboard)
        self.assertIn("expandCompareAll", dashboard)
        self.assertIn("compareFolderActions", dashboard)
        self.assertIn("children.forEach(markDirectoryDiff)", dashboard)
        self.assertIn("node.toNas", dashboard)
        self.assertIn("node.toComputer", dashboard)
        self.assertIn("data-sync-folder-one", dashboard)
        self.assertIn("data-sync-folder-overwrite", dashboard)
        self.assertIn("relevantDirectoryRecords", dashboard)
        self.assertIn("cascadeFolderSelection", dashboard)
        self.assertIn("selectedForSync.add(value)", dashboard)
        self.assertNotIn("像 BCompare 一样，先看左右目录是否存在", dashboard)
        self.assertLess(dashboard.index('id="compare-grid"'), dashboard.index('id="compare-dirs"'))
        self.assertIn("左右对比", dashboard)
        self.assertIn("电脑本地", dashboard)
        self.assertIn('data-page="tree"', dashboard)
        self.assertIn('data-page="control"', dashboard)
        self.assertIn('id="page-control"', dashboard)
        self.assertIn('id="system-status"', dashboard)
        self.assertIn("自动维护任务", dashboard)
        self.assertIn("恢复就绪度", dashboard)
        self.assertIn("便携恢复工具包", dashboard)
        self.assertIn("变化哨兵", dashboard)
        self.assertIn("控制平面证据链", dashboard)
        self.assertIn("运维历史与 SLO", dashboard)
        self.assertIn("SLO 观测天数", dashboard)
        self.assertIn('id="acl-hardening"', dashboard)
        self.assertIn("ACL 最小权限", dashboard)
        self.assertIn('id="encryption-evidence"', dashboard)
        self.assertIn("磁盘加密证据", dashboard)
        self.assertIn("复制期间源一致性", dashboard)
        self.assertIn("内容摘要复核", dashboard)
        self.assertIn("链接隔离", dashboard)
        self.assertIn('data-page="obsidian"', dashboard)
        self.assertIn('id="page-obsidian"', dashboard)
        self.assertIn(r"D:\Workspace\02_Knowledge\ObsidianVault", dashboard)
        self.assertIn("$obsidian-worklog", dashboard)
        self.assertIn("这次不要记录", dashboard)
        self.assertIn('id="directory-tree"', dashboard)
        self.assertIn('data-sync-folder-select', dashboard)
        self.assertIn('id="overwrite-to-nas"', dashboard)
        self.assertNotIn('data-sync-folder="', dashboard)
        self.assertIn("WorkspacePrivate", dashboard)
        self.assertIn('target="_blank"', dashboard)
        self.assertIn('rel="noopener noreferrer"', dashboard)
        self.assertNotIn("workspaceos://open?path=", dashboard)
        self.assertNotIn("__PAYLOAD__", dashboard)
        self.assertTrue(data.is_file())

    def test_location_snapshot_can_reuse_cached_nas_metadata(self):
        computer = Path(self.temp.name) / "computer-cache"
        nas = Path(self.temp.name) / "nas-cache"
        computer.mkdir()
        nas.mkdir()
        (computer / "same.txt").write_text("same", encoding="utf-8")
        (nas / "same.txt").write_text("same", encoding="utf-8")
        first = build_location_snapshot(computer, nas)
        (nas / "new-after-cache.txt").write_text("new", encoding="utf-8")
        cached = build_location_snapshot(computer, nas, previous=first, reuse_previous_nas=True)
        self.assertEqual(cached["nas_scan_mode"], "cached")
        self.assertNotIn("new-after-cache.txt", {item["relative"] for item in cached["files"]})
        live = build_location_snapshot(computer, nas, previous=cached, reuse_previous_nas=False)
        self.assertEqual(live["nas_scan_mode"], "live")
        self.assertIn("new-after-cache.txt", {item["relative"] for item in live["files"]})

    def test_location_snapshot_cache_miss_never_scans_nas(self):
        computer = Path(self.temp.name) / "computer"
        nas = Path(self.temp.name) / "nas"
        computer.mkdir()
        nas.mkdir()
        (computer / "local.txt").write_text("local", encoding="utf-8")
        (nas / "remote.txt").write_text("remote", encoding="utf-8")
        snapshot = build_location_snapshot(
            computer,
            nas,
            previous=None,
            reuse_previous_nas=True,
        )
        self.assertEqual(snapshot["nas_scan_mode"], "cache-miss")
        self.assertNotIn("remote.txt", {item["relative"] for item in snapshot["files"]})
        self.assertFalse(snapshot["nas_storage"]["available"])

    def test_location_snapshot_reuses_cache_across_nas_aliases(self):
        computer = Path(self.temp.name) / "computer"
        nas = Path(self.temp.name) / "nas"
        computer.mkdir()
        nas.mkdir()
        (computer / "same.txt").write_text("same", encoding="utf-8")
        (nas / "same.txt").write_text("same", encoding="utf-8")
        first = build_location_snapshot(computer, nas)
        alias = Path(self.temp.name) / "nas-alias"
        cached = build_location_snapshot(
            computer,
            alias,
            previous=first,
            reuse_previous_nas=True,
        )
        self.assertEqual(cached["nas_scan_mode"], "cached-alias")
        self.assertEqual(sum(1 for item in cached["files"] if item["nas"]), 1)

    def test_dashboard_sync_jobs_copy_one_sided_file_without_overwrite(self):
        computer = Path(self.temp.name) / "sync-computer"
        nas = Path(self.temp.name) / "sync-nas"
        computer.mkdir(); nas.mkdir()
        (computer / "only-local.txt").write_text("source", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        snapshot = build_location_snapshot(computer, nas)
        save_location_snapshot(snapshot, dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_nas", ["only-local.txt"])
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["completed_files"], 1)
        self.assertIn("refreshed_at", job)
        self.assertFalse(job["errors"])
        self.assertEqual((nas / "only-local.txt").read_text(encoding="utf-8"), "source")
        refreshed = json.loads(dashboard.with_suffix(".json").read_text(encoding="utf-8"))
        copied = next(item for item in refreshed["files"] if item["relative"] == "only-local.txt")
        self.assertEqual(copied["state"], "BOTH_SAME")
        self.assertIn("sync-panel", dashboard.read_text(encoding="utf-8"))

    def test_dashboard_cached_refresh_updates_transferred_nas_metadata(self):
        computer = Path(self.temp.name) / "cache-computer"
        nas = Path(self.temp.name) / "cache-nas"
        computer.mkdir(); nas.mkdir()
        source = computer / "conflict.txt"
        target = nas / "conflict.txt"
        source.write_text("local replacement", encoding="utf-8")
        target.write_text("old NAS", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        for direction in ("upload", "download"):
            origin, destination = (source, target) if direction == "upload" else (target, source)
            if direction == "download":
                origin.write_text("NAS replacement version", encoding="utf-8")
            jobs._copy_one({"source": origin, "target": destination}, "overwrite")
            self.assertEqual(origin.read_bytes(), destination.read_bytes())
            refreshed = jobs._snapshot(live_nas=False, transferred=["conflict.txt"])
            item = next(f for f in refreshed["files"] if f["relative"] == "conflict.txt")
            self.assertIsNotNone(item["nas"])
            self.assertEqual(item["nas"]["size"], target.stat().st_size)
            self.assertNotEqual(item["state"], "CONFLICT")

    def test_dashboard_sync_appends_summary_to_nas_obsidian_daily_log(self):
        computer = Path(self.temp.name) / "log-computer"
        nas = Path(self.temp.name) / "log-nas"
        computer.mkdir(); nas.mkdir()
        source = computer / "note.txt"; source.write_text("hello", encoding="utf-8")
        jobs = SyncJobs(computer, nas, computer / "dashboard.html")
        task = {"direction": "to_nas", "mode": "safe", "errors": []}
        path = jobs._append_obsidian_sync_log(task, ["note.txt"])
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("网页同步上传到 NAS", content)
        self.assertIn("note.txt", content)
        # Appending again preserves the first device's entry.
        jobs._append_obsidian_sync_log({"direction": "to_computer", "mode": "overwrite", "errors": []}, ["note.txt"])
        self.assertEqual(Path(path).read_text(encoding="utf-8").count("### "), 2)
        local = jobs._pull_obsidian_log_to_local(path)
        self.assertEqual(Path(local).read_text(encoding="utf-8"), Path(path).read_text(encoding="utf-8"))

    def test_dashboard_manual_refresh_discovers_new_local_file(self):
        computer = Path(self.temp.name) / "refresh-computer"
        nas = Path(self.temp.name) / "refresh-nas"
        computer.mkdir(); nas.mkdir()
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        (computer / "added-after-opening.txt").write_text("new", encoding="utf-8")
        result = SyncJobs(computer, nas, dashboard).refresh_snapshot()
        refreshed = json.loads(dashboard.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertTrue(any(item["relative"] == "added-after-opening.txt" for item in refreshed["files"]))
        page = dashboard.read_text(encoding="utf-8")
        self.assertIn("刷新目录", page)
        self.assertIn("/api/refresh", page)

    def test_dashboard_sync_jobs_copy_folder_prefix(self):
        computer = Path(self.temp.name) / "folder-computer"
        nas = Path(self.temp.name) / "folder-nas"
        (computer / "ProjectA" / "sub").mkdir(parents=True)
        nas.mkdir()
        (computer / "ProjectA" / "a.txt").write_text("a", encoding="utf-8")
        (computer / "ProjectA" / "sub" / "b.txt").write_text("b", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_nas", [], ["ProjectA"])
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["completed_files"], 2)
        self.assertNotIn("observed_targets", job)
        self.assertEqual((nas / "ProjectA" / "a.txt").read_text(encoding="utf-8"), "a")
        self.assertEqual((nas / "ProjectA" / "sub" / "b.txt").read_text(encoding="utf-8"), "b")

    def test_dashboard_sync_jobs_download_file_and_empty_folder_to_computer(self):
        computer = Path(self.temp.name) / "download-computer"
        nas = Path(self.temp.name) / "download-nas"
        computer.mkdir(); (nas / "Remote" / "empty").mkdir(parents=True)
        (nas / "Remote" / "remote.txt").write_text("from nas", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_computer", [], ["Remote"])
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["total_files"], 1)
        self.assertEqual(job["completed_files"], 1)
        self.assertEqual((computer / "Remote" / "remote.txt").read_text(encoding="utf-8"), "from nas")
        self.assertTrue((computer / "Remote" / "empty").is_dir())

    def test_dashboard_sync_jobs_copy_empty_folder_as_completed_unit(self):
        computer = Path(self.temp.name) / "empty-computer"
        nas = Path(self.temp.name) / "empty-nas"
        (computer / "EmptyFolder").mkdir(parents=True); nas.mkdir()
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_nas", [], ["EmptyFolder"])
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["total_files"], 1)
        self.assertEqual(job["completed_files"], 1)
        self.assertEqual(job["total_bytes"], 0)
        self.assertTrue((nas / "EmptyFolder").is_dir())

    def test_dashboard_copy_reports_byte_progress_in_chunks(self):
        computer = Path(self.temp.name) / "progress-computer"
        nas = Path(self.temp.name) / "progress-nas"
        computer.mkdir(); nas.mkdir()
        source = computer / "large.bin"
        source.write_bytes(b"x" * (17 * 1024 * 1024))
        dashboard = computer / "08_Indexes" / "file-locations.html"
        jobs = SyncJobs(computer, nas, dashboard)
        updates = []
        jobs._copy_one(
            {"source": source, "target": nas / "large.bin", "relative": "large.bin", "size": source.stat().st_size},
            "safe", updates.append,
        )
        self.assertGreaterEqual(len(updates), 3)
        self.assertEqual(sum(updates), source.stat().st_size)
        self.assertEqual((nas / "large.bin").stat().st_size, source.stat().st_size)

    def test_dashboard_sync_status_never_guesses_progress_from_preexisting_target(self):
        computer = Path(self.temp.name) / "observe-computer"
        nas = Path(self.temp.name) / "observe-nas"
        computer.mkdir(); nas.mkdir()
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        with jobs.lock:
            jobs.jobs["manual"] = {
                "id": "manual", "direction": "to_nas", "mode": "safe", "status": "running",
                "total_files": 1, "completed_files": 2, "total_bytes": 4, "copied_bytes": 8,
                "current": "", "errors": [], "created_at": "now",
            }
        (nas / "done.txt").write_text("done", encoding="utf-8")
        job = jobs.status("manual")
        self.assertEqual(job["completed_files"], 1)
        self.assertEqual(job["copied_bytes"], 4)

    def test_dashboard_sync_folder_counts_only_files_that_need_copying(self):
        computer = Path(self.temp.name) / "safe-folder-computer"
        nas = Path(self.temp.name) / "safe-folder-nas"
        (computer / "Project").mkdir(parents=True); (nas / "Project").mkdir(parents=True)
        (computer / "Project" / "existing.txt").write_text("keep", encoding="utf-8")
        (nas / "Project" / "existing.txt").write_text("keep", encoding="utf-8")
        (computer / "Project" / "missing.txt").write_text("copy", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_nas", [], ["Project"])
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["total_files"], 1)
        self.assertEqual(job["completed_files"], 1)
        self.assertEqual(job["total_bytes"], 4)
        self.assertEqual((nas / "Project" / "missing.txt").read_text(encoding="utf-8"), "copy")

    def test_dashboard_sync_jobs_overwrite_existing_file_without_hash_check(self):
        computer = Path(self.temp.name) / "overwrite-computer"
        nas = Path(self.temp.name) / "overwrite-nas"
        computer.mkdir(); nas.mkdir()
        (computer / "same.txt").write_text("new", encoding="utf-8")
        (nas / "same.txt").write_text("old", encoding="utf-8")
        dashboard = computer / "08_Indexes" / "file-locations.html"
        save_location_snapshot(build_location_snapshot(computer, nas), dashboard)
        jobs = SyncJobs(computer, nas, dashboard)
        job = jobs.start("to_nas", ["same.txt"], [], "overwrite")
        for _ in range(120):
            job = jobs.status(job["id"])
            if job["status"] not in {"queued", "scanning", "running"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["completed_files"], 1)
        self.assertEqual((nas / "same.txt").read_text(encoding="utf-8"), "new")

    def test_snapshot_preview_apply_manifest_and_no_overwrite(self):
        init_workspace(self.base)
        sample = self.base / "02_Knowledge" / "Notes" / "示例.txt"
        sample.write_text("snapshot", encoding="utf-8")
        destination = Path(self.temp.name) / "snapshots"
        preview = create_snapshot(self.base, destination, snapshot_name="fixed")
        self.assertEqual(preview["mode"], "dry-run")
        self.assertFalse((destination / "fixed").exists())
        applied = create_snapshot(self.base, destination, apply=True, snapshot_name="fixed")
        self.assertEqual(applied["status"], "created")
        self.assertEqual((destination / "fixed" / sample.relative_to(self.base)).read_text(encoding="utf-8"), "snapshot")
        verification_evidence = json.loads(
            (self.base / "08_Indexes" / "BackupVerification" / "latest-snapshot-verification.json").read_text(encoding="utf-8")
        )
        self.assertEqual(Path(verification_evidence["snapshot"]), Path(applied["destination"]))
        self.assertTrue(verification_evidence["valid"])
        self.assertTrue(verification_evidence["source_consistency_verified"])
        manifest = json.loads(Path(applied["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "1.2")
        self.assertTrue(manifest["source_consistency"]["verified"])
        self.assertEqual(
            manifest["source_consistency"]["before_inventory_sha256"],
            manifest["source_consistency"]["after_inventory_sha256"],
        )
        self.assertEqual(
            manifest["source_consistency"]["after_inventory_sha256"],
            manifest["source_consistency"]["snapshot_inventory_sha256"],
        )
        self.assertTrue(any(item["path"].endswith("示例.txt") for item in manifest["files"]))
        with self.assertRaises(FileExistsError):
            create_snapshot(self.base, destination, apply=True, snapshot_name="fixed")

    def test_snapshot_aborts_and_cleans_partial_when_source_changes_during_copy(self):
        init_workspace(self.base)
        changing = self.base / "02_Knowledge" / "Notes" / "changing.txt"
        changing.write_text("before", encoding="utf-8")
        destination = Path(self.temp.name) / "snapshots"
        real_inventory = backup_module._inventory
        inventory_calls = 0

        def inventory_with_mutation(root, *args, **kwargs):
            nonlocal inventory_calls
            inventory_calls += 1
            if inventory_calls == 3:
                changing.write_text("after", encoding="utf-8")
            return real_inventory(root, *args, **kwargs)

        with patch("backup._inventory", side_effect=inventory_with_mutation):
            with self.assertRaisesRegex(
                OSError,
                "SOURCE_CHANGED_DURING_SNAPSHOT",
            ):
                create_snapshot(
                    self.base,
                    destination,
                    apply=True,
                    snapshot_name="unstable",
                )

        self.assertFalse((destination / "unstable").exists())
        self.assertEqual(list(destination.glob(".unstable.partial-*")), [])
        self.assertFalse(
            (
                self.base
                / "08_Indexes"
                / "BackupVerification"
                / "latest-snapshot-verification.json"
            ).exists()
        )

    def test_snapshot_rejects_destination_inside_workspace(self):
        init_workspace(self.base)
        with self.assertRaises(ValueError):
            create_snapshot(self.base, self.base / "snapshots", apply=True)

    def test_snapshot_verification_detects_tampering_and_blocks_restore(self):
        init_workspace(self.base)
        sample = self.base / "02_Knowledge" / "Notes" / "verified.txt"
        sample.write_text("original", encoding="utf-8")
        snapshots = Path(self.temp.name) / "snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="verified")
        snapshot = Path(created["destination"])
        self.assertTrue(verify_snapshot(snapshot)["valid"])
        restored = Path(self.temp.name) / "restored"
        preview = restore_snapshot(snapshot, restored)
        self.assertEqual(preview["status"], "planned")
        applied = restore_snapshot(snapshot, restored, apply=True)
        self.assertEqual(applied["status"], "restored")
        self.assertTrue(applied["post_verified"])
        self.assertEqual((restored / sample.relative_to(self.base)).read_text(encoding="utf-8"), "original")
        (snapshot / sample.relative_to(self.base)).write_text("tampered", encoding="utf-8")
        verification = verify_snapshot(snapshot)
        self.assertFalse(verification["valid"])
        blocked = restore_snapshot(snapshot, Path(self.temp.name) / "blocked", apply=True)
        self.assertEqual(blocked["status"], "blocked")

    def test_snapshot_export_requires_distinct_volume_and_never_overwrites(self):
        init_workspace(self.base)
        created = create_snapshot(
            self.base,
            Path(self.temp.name) / "snapshots",
            apply=True,
            snapshot_name="external",
        )
        media = Path(self.temp.name) / "external-media"
        initialized = initialize_backup_media(
            media,
            "Offline SSD",
            confirm_distinct_physical_media=True,
            apply=True,
        )
        self.assertEqual(initialized["status"], "initialized")
        blocked = export_snapshot_to_media(created["destination"], media, apply=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["issues"][0]["code"], "BACKUP_MEDIA_SAME_VOLUME")
        self.assertFalse((media / "WorkspaceOS-Snapshots" / "external").exists())

        def volume_identity(path):
            return "device:external" if str(path).startswith(str(media)) else "device:local"

        report_path = self.base / "08_Indexes" / "Recovery" / "snapshot-export.json"
        with patch("backup_media._volume_identity", side_effect=volume_identity):
            exported = export_snapshot_to_media(
                created["destination"],
                media,
                apply=True,
                output=report_path,
            )
            repeated = export_snapshot_to_media(
                created["destination"],
                media,
                apply=True,
                output=report_path,
            )
        self.assertEqual(exported["status"], "exported")
        self.assertTrue(exported["target_verified"])
        self.assertTrue(exported["eligible_for_distinct_media"])
        self.assertEqual(exported["overwritten_files"], 0)
        self.assertEqual(exported["deleted_files"], 0)
        self.assertTrue(Path(exported["receipt"]).is_file())
        self.assertEqual(repeated["status"], "existing-verified")
        self.assertEqual(repeated["receipt_id"], exported["receipt_id"])
        receipt_path = Path(exported["receipt"])
        tampered_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        tampered_receipt["verified"] = False
        receipt_path.write_text(json.dumps(tampered_receipt), encoding="utf-8")
        with patch("backup_media._volume_identity", side_effect=volume_identity):
            with self.assertRaises(FileExistsError):
                export_snapshot_to_media(created["destination"], media, apply=True)

    def test_snapshot_export_recovers_interrupted_partial_to_trash(self):
        init_workspace(self.base)
        created = create_snapshot(
            self.base,
            Path(self.temp.name) / "snapshots",
            apply=True,
            snapshot_name="interrupted",
        )
        media = Path(self.temp.name) / "interrupted-media"
        initialize_backup_media(
            media,
            "Recovery Test",
            confirm_distinct_physical_media=True,
            apply=True,
        )

        def volume_identity(path):
            return "device:external" if str(path).startswith(str(media)) else "device:local"

        def interrupted_copy(source, target, **kwargs):
            shutil.copytree(source, target, **kwargs)
            raise OSError("simulated power loss")

        with patch("backup_media._volume_identity", side_effect=volume_identity):
            with self.assertRaises(OSError):
                export_snapshot_to_media(
                    created["destination"],
                    media,
                    apply=True,
                    copy_tree=interrupted_copy,
                )
            self.assertTrue(list((media / ".workspace-os-transactions").glob("*.json")))
            recovered = export_snapshot_to_media(created["destination"], media, apply=True)
        self.assertEqual(recovered["status"], "exported")
        self.assertEqual(len(recovered["recovered_transactions"]), 1)
        self.assertEqual(
            recovered["recovered_transactions"][0]["action"],
            "partial-moved-to-recoverable-trash",
        )
        self.assertFalse(list((media / ".workspace-os-transactions").glob("*.json")))
        self.assertTrue((media / "_WorkspaceOS_Trash" / "InterruptedSnapshotExports").is_dir())

    def test_canary_restore_drill_copies_verifies_and_removes_temporary_content(self):
        init_workspace(self.base)
        project = self.base / "01_Projects" / "Work" / "Active" / "Demo"
        project.mkdir(parents=True)
        (project / "README.md").write_text("restore canary", encoding="utf-8")
        snapshots = Path(self.temp.name) / "snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="drill-source")
        restore_root = Path(self.temp.name) / "restore-drills"
        output = self.base / "08_Indexes" / "RecoveryDrills" / "latest-restore-drill.json"

        report = run_restore_drill(
            self.base,
            created["destination"],
            restore_root,
            sample_count=16,
            output=output,
        )
        self.assertEqual(report["result"], "passed")
        self.assertGreater(report["checked_files"], 0)
        self.assertGreater(report["checked_bytes"], 0)
        self.assertTrue(report["temporary_content_removed"])
        self.assertFalse(report["contains_sample_paths"])
        self.assertTrue(output.is_file())
        self.assertEqual(list(restore_root.glob(".workspaceos-restore-drill-*")), [])
        self.assertTrue(all(len(item) == 16 for item in report["sample_ids"]))

    def test_canary_restore_drill_detects_corrupt_selected_source(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="corrupt-canary")
        snapshot = Path(created["destination"])
        (snapshot / ".workspace-os.json").write_text("tampered", encoding="utf-8")
        restore_root = Path(self.temp.name) / "restore-drills"
        report = run_restore_drill(
            self.base,
            snapshot,
            restore_root,
            output=self.base / "08_Indexes" / "RecoveryDrills" / "latest-restore-drill.json",
        )
        self.assertEqual(report["result"], "failed")
        self.assertTrue(any(item["code"] == "SOURCE_HASH_MISMATCH" for item in report["issues"]))
        self.assertTrue(report["temporary_content_removed"])
        self.assertEqual(list(restore_root.glob(".workspaceos-restore-drill-*")), [])

    def test_canary_restore_drill_rejects_live_workspace_target(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="unsafe-target")
        with self.assertRaises(ValueError):
            run_restore_drill(
                self.base,
                created["destination"],
                self.base / "RestoreTests",
            )
        self.assertFalse((Path(self.temp.name) / "blocked").exists())

    def test_retention_moves_old_snapshots_to_recoverable_trash(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "snapshots"
        created = []
        for index, timestamp in enumerate(("2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00")):
            result = create_snapshot(self.base, snapshots, apply=True, snapshot_name=f"snapshot-{index}")
            manifest_path = Path(result["manifest"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["created_at"] = timestamp
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            created.append(Path(result["destination"]))
        preview = apply_retention(snapshots, hourly=0, daily=0, weekly=0, monthly=0)
        self.assertEqual(len(preview["keep"]), 1)
        self.assertEqual(len(preview["move_to_trash"]), 2)
        applied = apply_retention(snapshots, hourly=0, daily=0, weekly=0, monthly=0, apply=True)
        self.assertEqual(len(applied["moved"]), 2)
        self.assertTrue(created[-1].is_dir())
        self.assertEqual(len(list((snapshots / "_WorkspaceOS_Trash").rglob("WORKSPACE-SNAPSHOT-MANIFEST.json"))), 2)

    def test_doctor_reports_backup_nas_and_rebuildable_cache(self):
        init_workspace(self.base)
        cache = self.base / "01_Projects" / "Work" / "Active" / "Demo" / ".vs"
        cache.mkdir(parents=True)
        (cache / "cache.ipch").write_bytes(b"x" * 32)
        nas = Path(self.temp.name) / "nas"
        nas.mkdir()
        (nas / ".workspace-os.json").write_text("{}", encoding="utf-8")
        before = workspace_health(self.base, Path(self.temp.name) / "snapshots", nas)
        codes = {item["code"] for item in before["findings"]}
        self.assertIn("BACKUP_STATUS_MISSING", codes)
        self.assertIn("REBUILDABLE_CACHE", codes)
        self.assertIn("NAS_AVAILABLE", codes)
        bounded = workspace_health(
            self.base,
            Path(self.temp.name) / "snapshots",
            r"Z:\definitely-not-probed",
            nas_probe={
                "status": "timeout",
                "generated_at": "2026-07-27T00:00:00+00:00",
                "duration_ms": 5000,
                "marker_valid": False,
            },
        )
        bounded_codes = {item["code"] for item in bounded["findings"]}
        self.assertIn("NAS_PROBE_TIMEOUT", bounded_codes)
        snapshot = create_snapshot(self.base, Path(self.temp.name) / "snapshots", apply=True, snapshot_name="health")
        after = workspace_health(self.base, Path(self.temp.name) / "snapshots", nas)
        self.assertNotIn("BACKUP_STATUS_MISSING", {item["code"] for item in after["findings"]})
        outputs = save_health(after, Path(self.temp.name) / "health.json")
        self.assertTrue(all(path.is_file() for path in outputs))

    def test_snapshot_explicitly_excludes_rebuildable_cache(self):
        init_workspace(self.base)
        cache = self.base / "01_Projects" / "Work" / "Active" / "Demo" / ".vs"
        cache.mkdir(parents=True)
        (cache / "large.ipch").write_bytes(b"cache")
        keep = cache.parent / "source.cpp"
        keep.write_text("source", encoding="utf-8")
        snapshots = Path(self.temp.name) / "snapshots"
        preview = create_snapshot(
            self.base,
            snapshots,
            snapshot_name="lean",
            exclude_rebuildable_cache=True,
        )
        self.assertEqual(preview["exclusions"]["excluded_files"], 1)
        created = create_snapshot(
            self.base,
            snapshots,
            apply=True,
            snapshot_name="lean",
            exclude_rebuildable_cache=True,
        )
        target = Path(created["destination"])
        self.assertFalse((target / cache.relative_to(self.base)).exists())
        self.assertTrue((target / keep.relative_to(self.base)).is_file())
        manifest = json.loads(Path(created["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["exclusions"]["profile"], "rebuildable-cache")

    def test_pinned_snapshot_survives_retention(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "snapshots"
        first = create_snapshot(self.base, snapshots, apply=True, snapshot_name="milestone")
        second = create_snapshot(self.base, snapshots, apply=True, snapshot_name="latest")
        set_snapshot_pin(first["destination"])
        plan = apply_retention(snapshots, hourly=0, daily=0, weekly=0, monthly=0)
        self.assertIn(first["destination"], plan["keep"])
        self.assertIn(second["destination"], plan["keep"])
        self.assertEqual(plan["move_to_trash"], [])

    def test_incremental_fulltext_search_respects_privacy(self):
        init_workspace(self.base)
        project = self.base / "01_Projects" / "Work" / "Active" / "Client" / "Demo"
        project.mkdir(parents=True)
        (project / "README.md").write_text("量子火箭 alpha launch", encoding="utf-8")
        private = self.base / "07_Admin" / "Private" / "secret.txt"
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text("不可索引的秘密火箭", encoding="utf-8")
        derived = self.base / "08_Indexes" / "Security" / "change-baseline.json"
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text('{"path":"Private/不可索引的派生路径"}', encoding="utf-8")
        database = Path(self.temp.name) / "search" / "workspace.db"
        first = build_search_database(self.base, database, include_content=True)
        self.assertGreater(first["content_files"], 0)
        result = search_database(database, "量子火箭")
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["results"][0]["path"].endswith("README.md"))
        self.assertEqual(search_database(database, "不可索引的秘密火箭")["count"], 0)
        self.assertEqual(search_database(database, "不可索引的派生路径")["count"], 0)
        second = build_search_database(self.base, database, include_content=True)
        self.assertEqual(second["added"], 0)
        self.assertGreater(second["unchanged"], 0)
        (project / "README.md").write_text("量子火箭 beta launch", encoding="utf-8")
        third = build_search_database(self.base, database, include_content=True)
        self.assertEqual(third["updated"], 1)
        self.assertTrue(search_status(database)["available"])

    def test_search_maintenance_atomically_recovers_corruption_with_last_good_fallback(self):
        init_workspace(self.base)
        note = self.base / "02_Knowledge" / "Notes" / "index-recovery.md"
        note.write_text("first generation token", encoding="utf-8")
        database = self.base / "08_Indexes" / "Search" / "workspace-search.db"
        status_path = database.parent / "search-status.json"

        first = maintain_search_database(
            self.base, database, include_content=True, output=status_path
        )
        self.assertEqual(first["status"], "healthy")
        self.assertTrue(first["current_valid"])
        self.assertFalse(first["last_good_valid"])
        self.assertEqual(search_database(database, "first")["count"], 1)

        note.write_text("second generation token", encoding="utf-8")
        second = maintain_search_database(
            self.base, database, include_content=True, output=status_path
        )
        self.assertEqual(second["action"], "incremental-promoted")
        self.assertTrue(second["last_good_valid"])
        self.assertEqual(search_database(database, "second")["count"], 1)

        database.write_bytes(b"not a sqlite database")
        degraded = search_status(database)
        self.assertEqual(degraded["status"], "degraded")
        self.assertTrue(degraded["using_fallback"])
        fallback_result = search_database(database, "first")
        self.assertTrue(fallback_result["using_fallback"])
        self.assertEqual(fallback_result["count"], 1)

        repaired = maintain_search_database(
            self.base, database, include_content=True, output=status_path
        )
        self.assertEqual(repaired["status"], "healthy")
        self.assertEqual(repaired["action"], "rebuilt")
        self.assertTrue(check_search_database(database)["valid"])
        self.assertEqual(search_database(database, "second")["count"], 1)

    def test_search_detects_same_size_same_mtime_content_drift_and_fts_tampering(self):
        init_workspace(self.base)
        note = self.base / "02_Knowledge" / "Notes" / "stealth-drift.md"
        note.write_text("alpha stealth marker", encoding="utf-8")
        database = Path(self.temp.name) / "search" / "workspace.db"
        first = build_search_database(
            self.base,
            database,
            include_content=True,
        )
        self.assertGreater(first["content_hash_verified_files"], 0)
        original_stat = note.stat()

        note.write_text("bravo stealth marker", encoding="utf-8")
        os.utime(
            note,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        self.assertEqual(note.stat().st_size, original_stat.st_size)
        second = build_search_database(
            self.base,
            database,
            include_content=True,
        )
        self.assertEqual(second["content_drift_detected"], 1)
        self.assertEqual(search_database(database, "alpha")["count"], 0)
        self.assertEqual(search_database(database, "bravo")["count"], 1)

        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE documents_fts SET content = ? WHERE path = ?",
                ("forged index content", note.relative_to(self.base).as_posix()),
            )
            connection.commit()
        finally:
            connection.close()
        checked = check_search_database(database)
        self.assertFalse(checked["valid"])
        self.assertTrue(any(
            item["code"] == "FTS_CONTENT_HASH_MISMATCH"
            for item in checked["issues"]
        ))

    def test_search_maintenance_failure_preserves_current_database(self):
        init_workspace(self.base)
        (self.base / "02_Knowledge" / "Notes" / "keep.md").write_text(
            "preserve current index", encoding="utf-8"
        )
        database = self.base / "08_Indexes" / "Search" / "workspace-search.db"
        maintain_search_database(self.base, database, include_content=True)
        before_hash = sha256_file(database)
        with patch("search_engine.build_search_database", side_effect=OSError("simulated build failure")):
            report = maintain_search_database(self.base, database, include_content=True)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["action"], "kept-existing")
        self.assertTrue(report["available"])
        self.assertEqual(sha256_file(database), before_hash)
        self.assertTrue(report["maintenance_issues"])
        self.assertEqual(search_database(database, "preserve")["count"], 1)

    def test_alert_center_surfaces_search_fallback(self):
        init_workspace(self.base)
        status = self.base / "08_Indexes" / "Search" / "search-status.json"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "available": True,
            "current_valid": False,
            "last_good_valid": True,
            "using_fallback": True,
            "current_issues": [{"code": "DATABASE_UNREADABLE"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        alert = next(item for item in report["alerts"] if item["code"] == "INDEX_FALLBACK_ACTIVE")
        self.assertEqual(alert["severity"], "WARNING")
        self.assertEqual(alert["source"], "search")

    def test_workspace_graph_links_nested_project_and_obsidian_notes(self):
        init_workspace(self.base)
        project = self.base / "01_Projects" / "Work" / "Active" / "Client" / "Demo"
        (project / "src").mkdir(parents=True)
        (project / "STATUS.md").write_text("当前状态：`ACTIVE`", encoding="utf-8")
        vault = self.base / "02_Knowledge" / "ObsidianVault"
        vault.mkdir(parents=True)
        (vault / "Demo.md").write_text(f"项目路径：{project}\n链接 [[Architecture]]", encoding="utf-8")
        (vault / "Architecture.md").write_text("# Architecture", encoding="utf-8")
        graph = build_workspace_graph(self.base)
        self.assertTrue(any(node["id"] == "project:Client/Demo" for node in graph["nodes"]))
        relations = {(edge["source"], edge["target"], edge["relation"]) for edge in graph["edges"]}
        self.assertIn(("group:Client", "project:Client/Demo", "GROUPS"), relations)
        self.assertIn(("note:Demo.md", "project:Client/Demo", "DOCUMENTS"), relations)
        self.assertIn(("note:Demo.md", "note:Architecture.md", "LINKS_TO"), relations)
        output = save_workspace_graph(graph, Path(self.temp.name) / "graph.json")
        self.assertTrue(output.is_file())

    def test_alert_center_propagates_critical_and_missing_signals(self):
        init_workspace(self.base)
        health_path = self.base / "08_Indexes" / "Health" / "workspace-health.json"
        health_path.parent.mkdir(parents=True)
        health_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "findings": [{"severity": "CRITICAL", "code": "DISK", "message": "disk failed", "path": "D:"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        self.assertEqual(report["status"], "critical")
        self.assertTrue(any(item["source"] == "health" and item["code"] == "DISK" for item in report["alerts"]))
        self.assertTrue(any(item["code"] == "REPORT_MISSING" for item in report["alerts"]))
        outputs = save_alert_center(report, self.base / "08_Indexes" / "Alerts" / "control-plane.json")
        self.assertTrue(all(path.is_file() for path in outputs))

    def test_alert_center_does_not_replay_expired_findings_as_current_failures(self):
        init_workspace(self.base)
        health_path = self.base / "08_Indexes" / "Health" / "workspace-health.json"
        health_path.parent.mkdir(parents=True, exist_ok=True)
        health_path.write_text(json.dumps({
            "generated_at": "2020-01-01T00:00:00+00:00",
            "findings": [{"severity": "ERROR", "code": "OLD_FAILURE", "message": "old"}],
        }), encoding="utf-8")
        audit_path = self.base / "08_Indexes" / "Audit" / "audit-report.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "findings": [{"severity": "ERROR", "code": "FILE_POLICY", "message": "file"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        codes = {item["code"] for item in report["alerts"]}
        self.assertIn("REPORT_STALE", codes)
        self.assertNotIn("OLD_FAILURE", codes)
        self.assertNotIn("FILE_POLICY", codes)

    def test_alert_center_surfaces_nas_publish_failure_as_warning(self):
        init_workspace(self.base)
        publish_path = self.base / "08_Indexes" / "Alerts" / "nas-publish-status.json"
        publish_path.parent.mkdir(parents=True)
        publish_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "success": False,
            "code": "NAS_PUBLISH_TIMEOUT",
            "message": "NAS publishing timed out.",
            "destination": "W:\\08_Indexes",
            "exit_code": 0,
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        publish_alert = next(item for item in report["alerts"] if item["source"] == "nas_publish")
        self.assertEqual(publish_alert["severity"], "WARNING")
        self.assertEqual(publish_alert["code"], "NAS_PUBLISH_TIMEOUT")

    def test_alert_center_marks_old_nas_publish_failure_as_stale(self):
        init_workspace(self.base)
        publish_path = self.base / "08_Indexes" / "Alerts" / "nas-publish-status.json"
        publish_path.parent.mkdir(parents=True)
        publish_path.write_text(json.dumps({
            "generated_at": "2020-01-01T00:00:00+00:00",
            "success": False,
            "code": "NAS_PUBLISH_FAILED",
            "message": "old failure",
            "destination": "W:\\08_Indexes",
            "exit_code": 1,
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        publish_alert = next(item for item in report["alerts"] if item["source"] == "nas_publish")
        self.assertEqual(publish_alert["code"], "NAS_PUBLISH_STATUS_STALE")
        self.assertGreater(publish_alert["age_hours"], 26)

    def test_alert_center_surfaces_scheduled_task_failure(self):
        init_workspace(self.base)
        tasks_path = self.base / "08_Indexes" / "Health" / "scheduled-tasks.json"
        tasks_path.parent.mkdir(parents=True)
        tasks_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "tasks": [{
                "name": "WorkspaceOS-DailySnapshot",
                "enabled": True,
                "last_result": 1,
                "last_run_time": "2099-01-01T00:00:00+00:00",
            }],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        task_alert = next(item for item in report["alerts"] if item["source"] == "automation")
        self.assertEqual(task_alert["severity"], "ERROR")
        self.assertEqual(task_alert["code"], "TASK_LAST_RUN_FAILED")

    def test_maintenance_audit_detects_definition_identity_and_trigger_drift(self):
        policy_path = ROOT / "config" / "maintenance-policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        workspace = Path(self.temp.name) / "maintenance-workspace"
        snapshots = Path(self.temp.name) / "maintenance-snapshots"
        restore_root = Path(self.temp.name) / "maintenance-restore"
        context = {
            "repository": str(ROOT),
            "workspace": str(workspace.resolve()),
            "snapshots": str(snapshots.resolve()),
            "nas": "W:\\",
            "restore_root": str(restore_root.resolve()),
        }

        def expand(values):
            result = []
            for value in values:
                for key, replacement in context.items():
                    value = value.replace("${" + key + "}", replacement)
                result.append(value)
            return result

        tasks = []
        for definition in policy["tasks"]:
            script = ROOT / definition["script"]
            trigger = definition["trigger"]
            tasks.append({
                "name": definition["name"],
                "execute": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "action_count": 1,
                "script": str(script),
                "script_sha256": sha256_file(script),
                "host_tokens": ["-NoProfile", "-ExecutionPolicy", "Bypass"],
                "argument_tokens": expand(definition["arguments"]),
                "principal": {
                    "user": "test-user",
                    "logon_type": "Interactive",
                    "run_level": "Limited",
                },
                "trigger_count": 1,
                "triggers": [{
                    "type": trigger["type"],
                    "time": trigger["time"],
                    "interval": trigger["interval"],
                    "days_of_week": trigger.get("days_of_week"),
                }],
                "settings": {
                    "execution_time_limit": "PT6H",
                    "start_when_available": True,
                },
            })
        report = {"schema_version": "1.1", "tasks": tasks}
        healthy = audit_maintenance_tasks(
            report,
            policy,
            repository=ROOT,
            workspace=workspace,
            snapshots=snapshots,
            nas="W:\\",
            restore_root=restore_root,
            expected_user="test-user",
        )
        self.assertEqual(healthy["status"], "healthy")
        self.assertEqual(healthy["summary"]["findings"], 0)

        drifted = copy.deepcopy(report)
        removed = drifted["tasks"].pop()
        drifted["tasks"].append({
            **copy.deepcopy(drifted["tasks"][0]),
            "name": "WorkspaceOS-Unexpected",
        })
        changed = drifted["tasks"][0]
        changed["execute"] = r"C:\Windows\System32\cmd.exe"
        changed["action_count"] = 2
        changed["script"] = str(ROOT / "README.md")
        changed["script_sha256"] = "0" * 64
        changed["host_tokens"].extend(["-EncodedCommand", "AAAA"])
        changed["principal"]["run_level"] = "Highest"
        changed["principal"]["user"] = "different-user"
        changed["triggers"][0]["time"] = "23:59"
        audit = audit_maintenance_tasks(
            drifted,
            policy,
            repository=ROOT,
            workspace=workspace,
            snapshots=snapshots,
            nas="W:\\",
            restore_root=restore_root,
            expected_user="test-user",
        )
        codes = {item["code"] for item in audit["findings"]}
        self.assertEqual(audit["status"], "critical")
        self.assertIn("MAINTENANCE_TASK_MISSING", codes)
        self.assertIn("MAINTENANCE_TASK_UNEXPECTED", codes)
        self.assertIn("TASK_ACTION_COUNT_INVALID", codes)
        self.assertIn("TASK_EXECUTABLE_UNTRUSTED", codes)
        self.assertIn("TASK_SCRIPT_MISMATCH", codes)
        self.assertIn("TASK_DANGEROUS_ARGUMENT", codes)
        self.assertIn("TASK_HOST_ARGUMENTS_MISMATCH", codes)
        self.assertIn("TASK_RUN_LEVEL_MISMATCH", codes)
        self.assertIn("TASK_PRINCIPAL_MISMATCH", codes)
        self.assertIn("TASK_TRIGGER_MISMATCH", codes)
        self.assertEqual(removed["name"], "WorkspaceOS-WeeklyRecoveryKitRetention")

        output = save_maintenance_audit(
            audit,
            workspace / "08_Indexes" / "Health" / "maintenance-audit.json",
        )
        self.assertTrue(output.is_file())

    def test_alert_center_surfaces_maintenance_definition_drift(self):
        init_workspace(self.base)
        audit_path = self.base / "08_Indexes" / "Health" / "maintenance-audit.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "status": "critical",
            "findings": [{
                "severity": "CRITICAL",
                "code": "TASK_DANGEROUS_ARGUMENT",
                "message": "dangerous",
                "task": "WorkspaceOS-DailySnapshot",
            }],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        alert = next(
            item for item in report["alerts"]
            if item["code"] == "TASK_DANGEROUS_ARGUMENT"
        )
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertEqual(alert["source"], "automation_integrity")

    def test_operations_history_deduplicates_chains_and_computes_error_budgets(self):
        init_workspace(self.base)
        indexes = self.base / "08_Indexes"

        def write(relative, value):
            path = indexes / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")

        write("Search/search-status.json", {"available": True})
        write("Recovery/recovery-readiness.json", {
            "score": 65,
            "evidence": {"snapshot_trusted": True},
        })
        write("Health/maintenance-audit.json", {"status": "healthy"})
        write("Evidence/status.json", {"valid": True})
        write("Health/scheduled-tasks.json", {"healthy": True})
        write("Alerts/control-plane.json", {
            "summary": {"WARNING": 2, "ERROR": 0, "CRITICAL": 0},
        })
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = append_operations_record(self.base, now=start)
        self.assertEqual(first["status"], "appended")
        repeated = append_operations_record(
            self.base,
            now=start + timedelta(minutes=10),
        )
        self.assertEqual(repeated["status"], "unchanged")
        self.assertEqual(repeated["sequence"], 1)

        for offset in range(1, 5):
            appended = append_operations_record(
                self.base,
                now=start + timedelta(days=offset),
            )
            self.assertEqual(appended["status"], "appended")
        write("Search/search-status.json", {"available": False})
        for offset in range(5, 8):
            appended = append_operations_record(
                self.base,
                now=start + timedelta(days=offset),
            )
            self.assertEqual(appended["status"], "appended")
        slo = appended["slo"]
        self.assertEqual(slo["sample_days"], 8)
        self.assertEqual(slo["status"], "degraded")
        self.assertEqual(
            slo["metrics"]["search_available"]["consecutive_failed_days"],
            3,
        )
        codes = {item["code"] for item in slo["findings"]}
        self.assertIn("OPERATIONS_ERROR_BUDGET_EXHAUSTED", codes)
        self.assertIn("OPERATIONS_CONSECUTIVE_FAILURES", codes)

        verification = verify_operations_history(self.base)
        self.assertTrue(verification["valid"])
        self.assertEqual(verification["record_count"], 8)
        records = sorted(
            (indexes / "Operations" / "records").glob("*.json")
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in records)
        self.assertNotIn(str(self.base), combined)
        self.assertNotIn('"path"', combined.casefold())

        tampered = json.loads(records[0].read_text(encoding="utf-8"))
        tampered["measures"]["recovery_score"] = 0
        records[0].write_text(json.dumps(tampered), encoding="utf-8")
        invalid = verify_operations_history(self.base)
        self.assertFalse(invalid["valid"])
        self.assertTrue(any(
            item["code"] == "OPERATIONS_RECORD_HASH_MISMATCH"
            for item in invalid["issues"]
        ))
        blocked = append_operations_record(
            self.base,
            now=start + timedelta(days=8),
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(len(list(
            (indexes / "Operations" / "records").glob("*.json")
        )), 8)

    def test_operations_history_rejects_invalid_windows_and_runs_isolated_drill(self):
        init_workspace(self.base)
        with self.assertRaises(ValueError):
            append_operations_record(self.base, window_days=0)
        with self.assertRaises(ValueError):
            append_operations_record(self.base, dedupe_minutes=-1)
        with self.assertRaises(ValueError):
            run_operations_history_drill(
                self.base,
                self.base / "unsafe-drill",
            )

        drill_root = Path(self.temp.name) / "isolated-operations-drill"
        report = run_operations_history_drill(self.base, drill_root)
        self.assertEqual(report["result"], "passed")
        self.assertEqual(report["synthetic_record_count"], 8)
        self.assertTrue(report["gates"]["error_budget_exhaustion_detected"])
        self.assertTrue(report["gates"]["tamper_detected"])
        self.assertTrue(report["gates"]["append_blocked_after_tamper"])
        self.assertEqual(report["gates"]["source_overwrites"], 0)
        self.assertEqual(report["gates"]["source_deletions"], 0)
        self.assertFalse(report["privacy"]["business_file_contents_read"])
        self.assertTrue(Path(report["output"]).is_file())

    def test_alert_center_surfaces_operations_history_and_slo_failures(self):
        init_workspace(self.base)
        operations = self.base / "08_Indexes" / "Operations"
        operations.mkdir(parents=True, exist_ok=True)
        (operations / "operations-history-status.json").write_text(json.dumps({
            "checked_at": "2099-01-01T00:00:00+00:00",
            "valid": False,
            "status": "invalid",
            "issues": [{"code": "OPERATIONS_RECORD_HASH_MISMATCH"}],
        }), encoding="utf-8")
        (operations / "operational-slo.json").write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "findings": [{
                "severity": "ERROR",
                "code": "OPERATIONS_CONSECUTIVE_FAILURES",
                "message": "three days",
                "signal": "search_available",
            }],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        history = next(
            item for item in report["alerts"]
            if item["code"] == "OPERATIONS_HISTORY_INVALID"
        )
        trend = next(
            item for item in report["alerts"]
            if item["code"] == "OPERATIONS_CONSECUTIVE_FAILURES"
        )
        self.assertEqual(history["severity"], "CRITICAL")
        self.assertEqual(trend["severity"], "ERROR")

    def test_evidence_chain_detects_history_tampering_and_refuses_append(self):
        init_workspace(self.base)
        artifact = self.base / "08_Indexes" / "Health" / "workspace-health.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"status":"healthy"}', encoding="utf-8")
        relative = "08_Indexes/Health/workspace-health.json"

        first = append_evidence_record(self.base, paths=[relative])
        second = append_evidence_record(self.base, paths=[relative])
        valid = verify_evidence_chain(self.base, verify_current=True)
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(valid["status"], "valid")
        self.assertEqual(valid["record_count"], 2)

        first_path = Path(first["record"])
        tampered = json.loads(first_path.read_text(encoding="utf-8"))
        tampered["subject"] = "tampered"
        first_path.write_text(json.dumps(tampered), encoding="utf-8")
        invalid = verify_evidence_chain(self.base)
        self.assertEqual(invalid["status"], "invalid")
        self.assertTrue(any(item["code"] == "RECORD_HASH_MISMATCH" for item in invalid["issues"]))
        with self.assertRaises(ValueError):
            append_evidence_record(self.base, paths=[relative])

    def test_evidence_chain_detects_current_artifact_drift(self):
        init_workspace(self.base)
        artifact = self.base / "08_Indexes" / "Health" / "workspace-health.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"status":"healthy"}', encoding="utf-8")
        append_evidence_record(
            self.base,
            paths=["08_Indexes/Health/workspace-health.json"],
        )
        artifact.write_text('{"status":"changed"}', encoding="utf-8")
        report = verify_evidence_chain(self.base, verify_current=True)
        self.assertEqual(report["status"], "invalid")
        self.assertTrue(any(item["code"] == "CURRENT_HASH_MISMATCH" for item in report["issues"]))

    def test_alert_center_surfaces_invalid_evidence_chain_as_critical(self):
        init_workspace(self.base)
        evidence = self.base / "08_Indexes" / "Evidence" / "status.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({
            "checked_at": "2099-01-01T00:00:00+00:00",
            "status": "invalid",
            "valid": False,
            "record_count": 2,
            "issues": [{"code": "RECORD_HASH_MISMATCH"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        item = next(alert for alert in report["alerts"] if alert["code"] == "EVIDENCE_CHAIN_INVALID")
        self.assertEqual(item["severity"], "CRITICAL")
        self.assertEqual(item["source"], "evidence")

    def test_recovery_readiness_proves_local_restore_but_flags_3_2_1_gap(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="ready")
        verification = verify_snapshot(created["destination"])
        verification_path = self.base / "08_Indexes" / "BackupVerification" / "latest-snapshot-verification.json"
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        drill_path = self.base / "08_Indexes" / "RecoveryDrills" / "drill.json"
        drill_path.parent.mkdir(parents=True)
        drill_path.write_text(json.dumps({
            "performed_at": verification["checked_at"],
            "result": "passed",
            "scope": "full",
            "snapshot": created["destination"],
            "snapshot_manifest_sha256": verification["manifest_sha256"],
            "checked_files": verification["checked_files"],
        }), encoding="utf-8")
        (drill_path.parent / "newer-kit-drill.json").write_text(json.dumps({
            "performed_at": "2099-01-01T00:00:00+00:00",
            "result": "passed",
            "scope": "portable-recovery-kit",
        }), encoding="utf-8")
        report = build_recovery_readiness(self.base, snapshots)
        self.assertEqual(report["status"], "degraded")
        self.assertTrue(report["evidence"]["snapshot_verified"])
        self.assertTrue(report["evidence"]["source_consistency_verified"])
        self.assertTrue(report["evidence"]["restore_drill_passed"])
        self.assertEqual(Path(report["evidence"]["restore_drill_report"]), drill_path)
        self.assertEqual(report["evidence"]["restore_drill_scope"], "full")
        self.assertFalse(report["coverage"]["meets_3_2_1"])
        self.assertTrue(any(item["code"] == "OFFSITE_ENCRYPTED_BACKUP_MISSING" for item in report["findings"]))
        self.assertFalse(report["evidence"]["restic_installed"])
        self.assertFalse(report["evidence"]["restic_command_available"])
        self.assertEqual(report["evidence"]["restic_scope"], "external-or-explicit")
        override = build_recovery_readiness(self.base, snapshots, drill_report=drill_path)
        self.assertTrue(override["evidence"]["restore_drill_passed"])
        self.assertEqual(Path(override["evidence"]["restore_drill_report"]), drill_path)
        kit_archive = Path(self.temp.name) / "recovery-kit.zip"
        kit_archive.write_bytes(b"kit")
        kit_report = Path(self.temp.name) / "recovery-kit.json"
        kit_report.write_text(json.dumps({
            "status": "created",
            "archive": str(kit_archive),
            "verification": {"valid": True, "checked_at": verification["checked_at"]},
        }), encoding="utf-8")
        with_kit = build_recovery_readiness(
            self.base,
            snapshots,
            drill_report=drill_path,
            recovery_kit_report=kit_report,
        )
        self.assertTrue(with_kit["evidence"]["recovery_kit_valid"])
        media = Path(self.temp.name) / "readiness-media"
        initialize_backup_media(
            media,
            "Readiness SSD",
            confirm_distinct_physical_media=True,
            apply=True,
        )

        def volume_identity(path):
            return "device:external" if str(path).startswith(str(media)) else "device:local"

        with patch("backup_media._volume_identity", side_effect=volume_identity):
            export_snapshot_to_media(
                created["destination"],
                media,
                apply=True,
                output=self.base / "08_Indexes" / "Recovery" / "snapshot-export.json",
            )
        protected = build_recovery_readiness(self.base, snapshots)
        self.assertTrue(protected["evidence"]["snapshot_export_valid"])
        self.assertEqual(protected["coverage"]["confirmed_copies"], 3)
        self.assertEqual(protected["coverage"]["confirmed_media"], 2)
        self.assertFalse(any(item["code"] == "SNAPSHOT_SAME_VOLUME" for item in protected["findings"]))
        self.assertFalse(protected["coverage"]["meets_3_2_1"])
        outputs = save_recovery_readiness(report, self.base / "08_Indexes" / "Recovery" / "readiness.json")
        self.assertTrue(all(path.is_file() for path in outputs))

    def test_recovery_readiness_binds_verification_and_drill_to_current_manifest(self):
        init_workspace(self.base)
        snapshots = Path(self.temp.name) / "bound-snapshots"
        created = create_snapshot(self.base, snapshots, apply=True, snapshot_name="bound")
        snapshot = Path(created["destination"])
        verification_path = (
            self.base
            / "08_Indexes"
            / "BackupVerification"
            / "latest-snapshot-verification.json"
        )
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        self.assertEqual(len(verification["manifest_sha256"]), 64)
        drill_path = self.base / "08_Indexes" / "RecoveryDrills" / "bound.json"
        drill_path.parent.mkdir(parents=True)

        def write_drill(snapshot_value: str) -> None:
            drill_path.write_text(json.dumps({
                "performed_at": verification["checked_at"],
                "result": "passed",
                "scope": "canary",
                "snapshot": snapshot_value,
                "snapshot_manifest_sha256": verification["manifest_sha256"],
                "checked_files": 1,
            }), encoding="utf-8")

        write_drill(str(snapshot))
        baseline = build_recovery_readiness(self.base, snapshots)
        self.assertTrue(baseline["evidence"]["snapshot_trusted"])
        self.assertTrue(baseline["evidence"]["verification_manifest_matches"])
        self.assertTrue(baseline["evidence"]["source_consistency_verified"])
        self.assertTrue(baseline["evidence"]["restore_drill_manifest_matches"])

        legacy_verification = dict(verification)
        legacy_verification["source_consistency_verified"] = False
        verification_path.write_text(
            json.dumps(legacy_verification),
            encoding="utf-8",
        )
        unproven = build_recovery_readiness(self.base, snapshots)
        self.assertTrue(any(
            item["code"] == "SNAPSHOT_SOURCE_CONSISTENCY_UNPROVEN"
            for item in unproven["findings"]
        ))
        verification_path.write_text(json.dumps(verification), encoding="utf-8")

        write_drill(str(snapshots / "different-snapshot"))
        wrong_drill = build_recovery_readiness(self.base, snapshots)
        self.assertFalse(wrong_drill["evidence"]["restore_drill_passed"])
        self.assertTrue(any(
            item["code"] == "RESTORE_DRILL_SNAPSHOT_MISMATCH"
            for item in wrong_drill["findings"]
        ))

        write_drill(str(snapshot))
        checked_at = datetime.fromisoformat(
            verification["checked_at"].replace("Z", "+00:00")
        )
        stale = build_recovery_readiness(
            self.base,
            snapshots,
            now=checked_at.astimezone(timezone.utc) + timedelta(days=9),
        )
        self.assertFalse(stale["evidence"]["verification_valid"])
        self.assertTrue(any(
            item["code"] == "SNAPSHOT_VERIFICATION_STALE"
            for item in stale["findings"]
        ))

        manifest_path = snapshot / "WORKSPACE-SNAPSHOT-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["unexpected_revision"] = "tampered-after-verification"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        drifted = build_recovery_readiness(self.base, snapshots)
        self.assertFalse(drifted["evidence"]["snapshot_trusted"])
        self.assertFalse(drifted["evidence"]["verification_manifest_matches"])
        self.assertEqual(drifted["coverage"]["confirmed_copies"], 1)
        self.assertTrue(any(
            item["code"] == "SNAPSHOT_MANIFEST_DRIFT"
            for item in drifted["findings"]
        ))
        drill = run_restore_drill(
            self.base,
            snapshot,
            Path(self.temp.name) / "bound-restore",
            output=drill_path,
        )
        self.assertEqual(drill["result"], "failed")
        self.assertEqual(drill["issues"][0]["code"], "VERIFICATION_MANIFEST_MISMATCH")

    def test_notification_outbox_deduplicates_and_strips_paths(self):
        control_plane = {
            "alerts": [{
                "id": "alert-1",
                "severity": "ERROR",
                "source": "backup",
                "code": "FAILED",
                "message": "Backup failed.",
                "path": "D:\\Private\\secret.txt",
            }]
        }
        first = build_notification_bundle(control_plane)
        self.assertEqual(first["status"], "pending")
        self.assertNotIn("path", first["alerts"][0])
        repeated = build_notification_bundle(
            control_plane,
            {"last_delivered_fingerprint": first["fingerprint"]},
        )
        self.assertEqual(repeated["status"], "unchanged")

    def test_recovery_kit_is_atomic_private_and_self_verifying(self):
        source = Path(self.temp.name) / "source"
        (source / "scripts" / "python").mkdir(parents=True)
        (source / "scripts" / "python" / "workspace_cli.py").write_text("print('ok')", encoding="utf-8")
        (source / "VERSION").write_text("2.0-test", encoding="utf-8")
        (source / "README.md").write_text("recovery", encoding="utf-8")
        (source / "config").mkdir()
        (source / "config" / "safe.example.json").write_text("{}", encoding="utf-8")
        (source / "config" / "maintenance-policy.json").write_text("{}", encoding="utf-8")
        (source / "config" / "private.json").write_text('{"token":"secret"}', encoding="utf-8")
        destination = Path(self.temp.name) / "packages"
        default_preview = build_recovery_kit(source, destination)
        self.assertIn(default_preview["source_fingerprint"][:10], Path(default_preview["archive"]).stem)
        preview = build_recovery_kit(source, destination, name="kit")
        self.assertEqual(preview["status"], "planned")
        self.assertFalse(destination.exists())
        created = build_recovery_kit(source, destination, name="kit", apply=True)
        archive = Path(created["archive"])
        self.assertTrue(created["verification"]["valid"])
        self.assertTrue(Path(created["checksum"]).is_file())
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertTrue(any(name.endswith("/config/safe.example.json") for name in names))
            self.assertTrue(any(name.endswith("/config/maintenance-policy.json") for name in names))
            self.assertFalse(any(name.endswith("/config/private.json") for name in names))
            self.assertTrue(any(name.endswith("/RESTORE-FIRST.md") for name in names))
        existing = build_recovery_kit(source, destination, name="kit", apply=True)
        self.assertEqual(existing["status"], "existing_verified")
        self.assertTrue(verify_recovery_kit(archive)["valid"])
        malicious = destination / "malicious-recovery-kit.zip"
        shutil.copy2(archive, malicious)
        with zipfile.ZipFile(malicious) as bundle:
            prefix = bundle.namelist()[0].split("/", 1)[0] + "/"
        with zipfile.ZipFile(malicious, "a") as bundle:
            bundle.writestr(prefix + "../escape.txt", b"escape")
        malicious_report = verify_recovery_kit(malicious)
        self.assertFalse(malicious_report["valid"])
        self.assertTrue(any(
            item["code"] == "UNSAFE_ARCHIVE_PATH"
            for item in malicious_report["issues"]
        ))

    def test_distribution_is_atomic_private_and_has_trial_entrypoint(self):
        source = Path(self.temp.name) / "distribution-source"
        (source / "scripts" / "python").mkdir(parents=True)
        (source / "scripts" / "windows").mkdir(parents=True)
        (source / "scripts" / "python" / "workspace_cli.py").write_text("print('ok')", encoding="utf-8")
        (source / "scripts" / "windows" / "Start-WorkspaceOSTrial.ps1").write_text("Write-Output ok", encoding="utf-8")
        (source / "scripts" / "windows" / "Install-WorkspaceOS.ps1").write_text("Write-Output ok", encoding="utf-8")
        (source / "VERSION").write_text("2.0-test", encoding="utf-8")
        (source / "README.md").write_text("distribution", encoding="utf-8")
        (source / "AGENTS.md").write_text("rules", encoding="utf-8")
        (source / "CHANGELOG.md").write_text("changes", encoding="utf-8")
        (source / "LICENSE").write_text("license", encoding="utf-8")
        (source / "config").mkdir()
        (source / "config" / "safe.example.json").write_text("{}", encoding="utf-8")
        (source / "config" / "maintenance-policy.json").write_text("{}", encoding="utf-8")
        (source / "config" / "private.json").write_text('{"token":"secret"}', encoding="utf-8")
        destination = Path(self.temp.name) / "distributions"

        preview = build_distribution(source, destination)
        self.assertEqual(preview["status"], "planned")
        self.assertFalse(destination.exists())
        created = build_distribution(source, destination, apply=True)
        archive = Path(created["archive"])
        self.assertEqual(created["status"], "created")
        self.assertTrue(created["verification"]["valid"])
        self.assertTrue(Path(created["checksum"]).is_file())
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertTrue(any(name.endswith("/TRY-WORKSPACE-OS.cmd") for name in names))
            self.assertTrue(any(name.endswith("/OPEN-TRIAL-NEXUS.cmd") for name in names))
            self.assertTrue(any(name.endswith("/README-FIRST.txt") for name in names))
            self.assertTrue(any(name.endswith("/scripts/windows/Start-WorkspaceOSTrial.ps1") for name in names))
            self.assertTrue(any(name.endswith("/config/maintenance-policy.json") for name in names))
            self.assertTrue(any(name.endswith("/DISTRIBUTION-MANIFEST.json") for name in names))
            self.assertFalse(any(name.endswith("/config/private.json") for name in names))
        repeated = build_distribution(source, destination, apply=True)
        self.assertEqual(repeated["status"], "existing_verified")
        self.assertTrue(verify_distribution(archive)["valid"])

        malicious = destination / "malicious-distribution.zip"
        shutil.copy2(archive, malicious)
        with zipfile.ZipFile(malicious) as bundle:
            prefix = bundle.namelist()[0].split("/", 1)[0] + "/"
        symlink = zipfile.ZipInfo(prefix + "unsafe-link")
        symlink.create_system = 3
        symlink.external_attr = (0o120777 << 16)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(malicious, "a") as bundle:
                bundle.writestr(prefix + "../escape.txt", b"escape")
                bundle.writestr(symlink, b"../../outside")
                bundle.writestr(prefix + "README.md", b"duplicate")
        malicious_report = verify_distribution(malicious)
        malicious_codes = {item["code"] for item in malicious_report["issues"]}
        self.assertFalse(malicious_report["valid"])
        self.assertIn("UNSAFE_ARCHIVE_PATH", malicious_codes)
        self.assertIn("SYMLINK_ARCHIVE_MEMBER", malicious_codes)
        self.assertIn("DUPLICATE_ARCHIVE_MEMBER", malicious_codes)

    def test_recovery_kit_retention_protects_latest_reports_and_moves_pairs(self):
        packages = Path(self.temp.name) / "packages"
        packages.mkdir()
        created: dict[str, list[Path]] = {"Kit": [], "Portable": []}
        base_timestamp = 1_700_000_000
        for flavor in created:
            for index in range(5):
                stem = f"WorkspaceOS-Recovery-{flavor}-2.0.0-2026010{index + 1}-{index:010d}"
                archive = packages / f"{stem}.zip"
                checksum = packages / f"{stem}.sha256"
                archive.write_bytes(f"{flavor}-{index}".encode())
                checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
                timestamp = base_timestamp + index * 86400
                os.utime(archive, (timestamp, timestamp))
                os.utime(checksum, (timestamp, timestamp))
                created[flavor].append(archive)
        orphan = packages / "WorkspaceOS-Recovery-Kit-2.0.0-20260109-orphan.zip"
        orphan.write_bytes(b"orphan")
        report = Path(self.temp.name) / "latest.json"
        report.write_text(json.dumps({"archive": str(created["Kit"][0])}), encoding="utf-8")

        preview = apply_recovery_kit_retention(
            packages,
            keep_latest=1,
            daily=2,
            weekly=0,
            monthly=0,
            protect_reports=[report],
        )
        kept_archives = {Path(item["archive"]) for item in preview["keep"]}
        self.assertIn(created["Kit"][-1], kept_archives)
        self.assertIn(created["Portable"][-1], kept_archives)
        self.assertIn(created["Kit"][0], kept_archives)
        self.assertEqual(preview["orphans"][0]["archive"], str(orphan))
        self.assertGreater(preview["reclaimable_bytes"], 0)

        applied = apply_recovery_kit_retention(
            packages,
            keep_latest=1,
            daily=2,
            weekly=0,
            monthly=0,
            protect_reports=[report],
            apply=True,
        )
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(created["Kit"][-1].is_file())
        self.assertTrue(created["Portable"][-1].is_file())
        self.assertTrue(created["Kit"][0].is_file())
        self.assertTrue(orphan.is_file())
        for item in applied["moved"]:
            trash = Path(item["trash"])
            self.assertTrue((trash / Path(item["archive"]).name).is_file())
            self.assertTrue((trash / Path(item["checksum"]).name).is_file())

    def test_device_handoff_blocks_conflicts_and_receipts_require_exact_match(self):
        source = Path(self.temp.name) / "source-device"
        target = Path(self.temp.name) / "target-device"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        source_scope = source / "02_Knowledge"
        target_scope = target / "02_Knowledge"
        (source_scope / "same.txt").write_text("same", encoding="utf-8")
        (target_scope / "same.txt").write_text("same", encoding="utf-8")
        (source_scope / "new.txt").write_text("new", encoding="utf-8")

        source_manifest = build_device_manifest(source, "windows", scopes=["02_Knowledge"])
        target_manifest = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        plan = compare_device_manifests(source_manifest, target_manifest)
        self.assertEqual(plan["status"], "ready")
        self.assertTrue(plan["safe_to_copy_source_to_target"])
        self.assertEqual(plan["source_only"], ["02_Knowledge/new.txt"])
        self.assertFalse(build_sync_receipt(source_manifest, target_manifest)["safe_to_switch_primary_device"])

        (target_scope / "new.txt").write_text("new", encoding="utf-8")
        matched_target = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        receipt = build_sync_receipt(source_manifest, matched_target)
        self.assertEqual(receipt["status"], "verified")
        self.assertTrue(receipt["safe_to_switch_primary_device"])

        (target_scope / "same.txt").write_text("conflict", encoding="utf-8")
        conflicted = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        blocked = compare_device_manifests(source_manifest, conflicted)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["summary"]["conflicts"], 1)
        sync_status = self.base / "08_Indexes" / "Devices" / "device-sync-status.json"
        sync_status.parent.mkdir(parents=True)
        sync_status.write_text(json.dumps(blocked), encoding="utf-8")
        alerts = build_alert_center(self.base)
        self.assertTrue(any(
            item["code"] == "DEVICE_HANDOFF_BLOCKED"
            for item in alerts["alerts"]
        ))

        manifest_path = Path(self.temp.name) / "manifest.json"
        save_json_atomic(source_manifest, manifest_path)
        self.assertEqual(load_device_manifest(manifest_path)["inventory_sha256"], source_manifest["inventory_sha256"])
        tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
        tampered["files"][0]["size"] += 1
        manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_device_manifest(manifest_path)

    def test_device_handoff_apply_stages_verifies_and_never_overwrites(self):
        source = Path(self.temp.name) / "source-apply"
        target = Path(self.temp.name) / "target-apply"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        (source / "02_Knowledge" / "same.txt").write_text("same", encoding="utf-8")
        (target / "02_Knowledge" / "same.txt").write_text("same", encoding="utf-8")
        new_file = source / "02_Knowledge" / "new.txt"
        new_file.write_text("new content", encoding="utf-8")
        source_manifest = build_device_manifest(source, "windows", scopes=["02_Knowledge"])
        target_manifest = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        source_path = Path(self.temp.name) / "source.json"
        target_path = Path(self.temp.name) / "target.json"
        save_json_atomic(source_manifest, source_path)
        save_json_atomic(target_manifest, target_path)
        output = target / "08_Indexes" / "Devices" / "device-apply-status.json"

        preview = apply_source_only_handoff(
            source, target, source_path, target_path, output=output
        )
        self.assertEqual(preview["status"], "planned")
        self.assertFalse((target / "02_Knowledge" / "new.txt").exists())
        self.assertEqual(preview["overwritten_files"], 0)
        applied = apply_source_only_handoff(
            source, target, source_path, target_path, apply=True, output=output
        )
        self.assertEqual(applied["status"], "verified")
        self.assertEqual(applied["copied_files"], 1)
        self.assertEqual((target / "02_Knowledge" / "new.txt").read_text(encoding="utf-8"), "new content")
        self.assertTrue(applied["receipt"]["safe_to_switch_primary_device"])
        self.assertEqual(applied["overwritten_files"], 0)
        self.assertEqual(applied["deleted_files"], 0)
        staging = target / "08_Indexes" / "Devices" / "HandoffStaging"
        self.assertFalse(staging.exists())

    def test_device_handoff_apply_blocks_stale_plan_without_copying(self):
        source = Path(self.temp.name) / "source-stale"
        target = Path(self.temp.name) / "target-stale"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        source_file = source / "02_Knowledge" / "planned.txt"
        source_file.write_text("planned", encoding="utf-8")
        source_manifest = build_device_manifest(source, "windows", scopes=["02_Knowledge"])
        target_manifest = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        source_path = save_json_atomic(source_manifest, Path(self.temp.name) / "source-stale.json")
        target_path = save_json_atomic(target_manifest, Path(self.temp.name) / "target-stale.json")
        source_file.write_text("changed after plan", encoding="utf-8")

        report = apply_source_only_handoff(
            source, target, source_path, target_path, apply=True
        )
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(item["code"] == "SOURCE_MANIFEST_STALE" for item in report["issues"]))
        self.assertFalse((target / "02_Knowledge" / "planned.txt").exists())

    def test_device_handoff_recovers_interrupted_commit_before_retry(self):
        source = Path(self.temp.name) / "source-recover"
        target = Path(self.temp.name) / "target-recover"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        source_file = source / "02_Knowledge" / "recover.txt"
        source_file.write_text("recoverable", encoding="utf-8")
        source_manifest = build_device_manifest(source, "windows", scopes=["02_Knowledge"])
        target_manifest = build_device_manifest(target, "mac", scopes=["02_Knowledge"])
        source_path = save_json_atomic(source_manifest, Path(self.temp.name) / "source-recover.json")
        target_path = save_json_atomic(target_manifest, Path(self.temp.name) / "target-recover.json")

        interrupted_target = target / "02_Knowledge" / "recover.txt"
        interrupted_target.write_bytes(source_file.read_bytes())
        transaction = target / "08_Indexes" / "Devices" / "HandoffStaging" / "interrupted"
        transaction.mkdir(parents=True)
        item = next(entry for entry in source_manifest["files"] if entry["path"].endswith("recover.txt"))
        save_json_atomic({
            "schema_version": "1.0",
            "state": "committing",
            "files": [{
                "path": item["path"],
                "size": item["size"],
                "sha256": item["sha256"],
            }],
        }, transaction / "transaction.json")

        preview = apply_source_only_handoff(
            source, target, source_path, target_path, apply=False
        )
        self.assertEqual(preview["status"], "blocked")
        self.assertEqual(preview["issues"][0]["code"], "INTERRUPTED_TRANSACTION_PENDING")
        self.assertTrue(interrupted_target.is_file())
        self.assertTrue(transaction.is_dir())

        report = apply_source_only_handoff(
            source, target, source_path, target_path, apply=True
        )
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["recovered_transactions"], 1)
        self.assertEqual(interrupted_target.read_text(encoding="utf-8"), "recoverable")
        self.assertFalse((target / "08_Indexes" / "Devices" / "HandoffStaging").exists())

    def test_alert_center_surfaces_failed_device_apply(self):
        init_workspace(self.base)
        status = self.base / "08_Indexes" / "Devices" / "device-apply-status.json"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps({
            "status": "failed",
            "overwritten_files": 0,
            "deleted_files": 0,
            "issues": [{"code": "HANDOFF_APPLY_FAILED"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        alert = next(item for item in report["alerts"] if item["code"] == "DEVICE_HANDOFF_APPLY_FAILED")
        self.assertEqual(alert["severity"], "ERROR")
        self.assertEqual(alert["source"], "device_sync")

        bundle_status = self.base / "08_Indexes" / "Devices" / "device-bundle-import.json"
        bundle_status.write_text(json.dumps({
            "status": "blocked",
            "overwritten_files": 0,
            "deleted_files": 0,
            "issues": [{"code": "BUNDLE_IMPORT_CONFLICT"}],
        }), encoding="utf-8")
        bundle_report = build_alert_center(self.base)
        bundle_alert = next(
            item for item in bundle_report["alerts"]
            if item["code"] == "DEVICE_BUNDLE_IMPORT_BLOCKED"
        )
        self.assertEqual(bundle_alert["severity"], "WARNING")
        self.assertEqual(bundle_alert["source"], "device_bundle")

    def test_offline_device_bundle_exports_verifies_and_imports_without_overwrite(self):
        source = Path(self.temp.name) / "bundle-source"
        target = Path(self.temp.name) / "bundle-target"
        destination = Path(self.temp.name) / "transport"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        payload = source / "02_Knowledge" / "offline.txt"
        payload.write_text("offline handoff", encoding="utf-8")

        preview = export_device_bundle(
            source, "windows", destination, scopes=["02_Knowledge"]
        )
        self.assertEqual(preview["status"], "planned")
        self.assertFalse(Path(preview["archive"]).exists())
        with self.assertRaises(ValueError):
            export_device_bundle(
                source,
                "windows",
                destination,
                scopes=["02_Knowledge"],
                apply=True,
            )
        exported = export_device_bundle(
            source,
            "windows",
            destination,
            scopes=["02_Knowledge"],
            simulation=True,
            apply=True,
        )
        archive = Path(exported["archive"])
        self.assertEqual(exported["status"], "exported")
        self.assertTrue(verify_device_bundle(archive)["valid"])

        planned = import_device_bundle(archive, target, "mac")
        self.assertEqual(planned["status"], "planned")
        self.assertFalse((target / "02_Knowledge" / "offline.txt").exists())
        applied = import_device_bundle(archive, target, "mac", apply=True)
        self.assertEqual(applied["status"], "verified")
        self.assertEqual(applied["copied_files"], 1)
        self.assertEqual(applied["overwritten_files"], 0)
        self.assertEqual(applied["deleted_files"], 0)
        self.assertTrue(applied["receipt"]["safe_to_switch_primary_device"])
        self.assertEqual(
            (target / "02_Knowledge" / "offline.txt").read_text(encoding="utf-8"),
            "offline handoff",
        )
        repeated = import_device_bundle(archive, target, "mac", apply=True)
        self.assertEqual(repeated["status"], "already-synced")

    def test_offline_device_bundle_blocks_tampering_conflicts_and_sensitive_scopes(self):
        source = Path(self.temp.name) / "bundle-block-source"
        target = Path(self.temp.name) / "bundle-block-target"
        destination = Path(self.temp.name) / "bundle-block-transport"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        (source / "02_Knowledge" / "conflict.txt").write_text("source", encoding="utf-8")
        exported = export_device_bundle(
            source,
            "windows",
            destination,
            scopes=["02_Knowledge"],
            simulation=True,
            apply=True,
        )
        archive = Path(exported["archive"])

        (target / "02_Knowledge" / "conflict.txt").write_text("target", encoding="utf-8")
        blocked = import_device_bundle(archive, target, "mac", apply=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(
            (target / "02_Knowledge" / "conflict.txt").read_text(encoding="utf-8"),
            "target",
        )
        self.assertEqual(blocked["overwritten_files"], 0)

        tampered = destination / "tampered.zip"
        shutil.copy2(archive, tampered)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(tampered, "a") as bundle:
                prefix = zipfile.ZipFile(archive).namelist()[0].split("/")[0]
                bundle.writestr(f"{prefix}/PAYLOAD/../../escape.txt", b"escape")
        verification = verify_device_bundle(tampered)
        self.assertFalse(verification["valid"])
        self.assertTrue(any(
            item["code"] in {"UNSAFE_ARCHIVE_PATH", "UNEXPECTED_BUNDLE_MEMBER"}
            for item in verification["issues"]
        ))
        self.assertEqual(import_device_bundle(tampered, target, "mac")["status"], "blocked")

        with self.assertRaises(ValueError):
            build_device_manifest(source, "windows", scopes=["00_Inbox/Private"])

    def test_offline_device_bundle_recovers_interrupted_commit_before_retry(self):
        source = Path(self.temp.name) / "bundle-recover-source"
        target = Path(self.temp.name) / "bundle-recover-target"
        destination = Path(self.temp.name) / "bundle-recover-transport"
        init_workspace(source)
        init_workspace(target)
        (target / ".workspace-os.json").write_bytes((source / ".workspace-os.json").read_bytes())
        source_file = source / "02_Knowledge" / "recover.txt"
        source_file.write_text("recover bundle", encoding="utf-8")
        exported = export_device_bundle(
            source,
            "windows",
            destination,
            scopes=["02_Knowledge"],
            simulation=True,
            apply=True,
        )
        archive = Path(exported["archive"])
        verification = verify_device_bundle(archive)
        source_manifest = build_device_manifest(source, "windows", scopes=["02_Knowledge"])
        entry = next(item for item in source_manifest["files"] if item["path"].endswith("recover.txt"))

        interrupted_target = target / entry["path"]
        interrupted_target.write_bytes(source_file.read_bytes())
        transaction = target / "08_Indexes" / "Devices" / "BundleStaging" / "interrupted"
        transaction.mkdir(parents=True)
        save_json_atomic({
            "schema_version": "1.0",
            "state": "committing",
            "archive_sha256": verification["archive_sha256"],
            "files": [{
                "path": entry["path"],
                "size": entry["size"],
                "sha256": entry["sha256"],
            }],
        }, transaction / "transaction.json")

        preview = import_device_bundle(archive, target, "mac")
        self.assertEqual(preview["status"], "blocked")
        self.assertEqual(
            preview["issues"][0]["code"],
            "INTERRUPTED_BUNDLE_TRANSACTION_PENDING",
        )
        applied = import_device_bundle(archive, target, "mac", apply=True)
        self.assertEqual(applied["status"], "verified")
        self.assertEqual(applied["recovered_transactions"], 1)
        self.assertEqual(interrupted_target.read_text(encoding="utf-8"), "recover bundle")
        self.assertFalse((target / "08_Indexes" / "Devices" / "BundleStaging").exists())

    def test_change_guard_detects_encrypted_rename_and_freezes_baseline(self):
        init_workspace(self.base)
        protected = self.base / "01_Projects" / "Work" / "Active" / "Guard"
        protected.mkdir(parents=True, exist_ok=True)
        originals = []
        for index in range(3):
            path = protected / f"document-{index}.txt"
            path.write_text(f"content-{index}", encoding="utf-8")
            originals.append(path)
        baseline = self.base / "08_Indexes" / "Security" / "change-baseline.json"
        output = self.base / "08_Indexes" / "Security" / "change-guard.json"
        first, _, _ = run_change_guard(self.base, baseline, output)
        self.assertEqual(first["status"], "learning")
        self.assertNotIn("08_Indexes", baseline.read_text(encoding="utf-8"))
        baseline_before = baseline.read_text(encoding="utf-8")
        for path in originals:
            path.rename(path.with_name(path.name + ".locked"))
        detected, _, _ = run_change_guard(self.base, baseline, output)
        self.assertEqual(detected["status"], "critical")
        self.assertFalse(detected["baseline_updated"])
        self.assertEqual(detected["summary"]["encrypted_renames"], 3)
        self.assertEqual(baseline.read_text(encoding="utf-8"), baseline_before)
        accepted, _, _ = run_change_guard(self.base, baseline, output, accept=True)
        self.assertTrue(accepted["baseline_updated"])
        self.assertEqual(accepted["baseline_update_reason"], "explicitly-accepted")

    def test_alert_center_propagates_change_guard_critical(self):
        init_workspace(self.base)
        security_path = self.base / "08_Indexes" / "Security" / "change-guard.json"
        security_path.parent.mkdir(parents=True)
        security_path.write_text(json.dumps({
            "generated_at": "2099-01-01T00:00:00+00:00",
            "findings": [{
                "severity": "CRITICAL",
                "code": "RANSOM_NOTE_DETECTED",
                "message": "Ransom note detected.",
            }],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        finding = next(item for item in report["alerts"] if item["source"] == "security")
        self.assertEqual(finding["severity"], "CRITICAL")
        self.assertEqual(finding["code"], "RANSOM_NOTE_DETECTED")

    def test_security_audit_redacts_secret_values_and_skips_protected_paths(self):
        init_workspace(self.base)
        source = self.base / "01_Projects" / "Work" / "Active" / "Security"
        source.mkdir(parents=True)
        exposed = "sk-proj-" + "A" * 32
        (source / "settings.py").write_text(
            f'OPENAI_API_KEY = "{exposed}"\n',
            encoding="utf-8",
        )
        protected = self.base / "07_Admin" / "Private"
        protected.mkdir(parents=True, exist_ok=True)
        protected_value = "ghp_" + "B" * 40
        (protected / "credentials.txt").write_text(protected_value, encoding="utf-8")

        report = audit_security(self.base)
        self.assertEqual(report["status"], "error")
        finding = next(item for item in report["findings"] if item["code"] == "OPENAI_API_KEY")
        self.assertEqual(finding["line"], 1)
        self.assertNotIn(exposed, json.dumps(report))
        self.assertNotIn(protected_value, json.dumps(report))
        self.assertGreaterEqual(report["summary"]["skipped_protected_files"], 1)
        outputs = save_security_audit(
            report,
            self.base / "08_Indexes" / "Security" / "security-audit.json",
        )
        self.assertTrue(all(path.is_file() for path in outputs))
        self.assertNotIn(exposed, outputs[0].read_text(encoding="utf-8"))
        self.assertNotIn(exposed, outputs[1].read_text(encoding="utf-8"))

    def test_security_audit_ignore_is_explicit_and_file_findings_stay_in_report(self):
        init_workspace(self.base)
        source = self.base / "01_Projects" / "Work" / "Active" / "Fixtures"
        source.mkdir(parents=True)
        (source / "fixture.txt").write_text(
            "token=ghp_" + "C" * 40,
            encoding="utf-8",
        )
        config = self.base / "07_Admin" / "WorkspaceOS" / "security-audit-ignore.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({
            "ignore": [{
                "path": "01_Projects/Work/Active/Fixtures/*",
                "codes": ["GITHUB_TOKEN"],
                "reason": "Synthetic fixture",
            }]
        }), encoding="utf-8")
        ignored = audit_security(self.base)
        self.assertFalse(any(item["code"] == "GITHUB_TOKEN" for item in ignored["findings"]))

        config.unlink()
        report = audit_security(self.base)
        output = self.base / "08_Indexes" / "Security" / "security-audit.json"
        save_security_audit(report, output)
        alerts = build_alert_center(self.base)
        self.assertTrue(any(item["code"] == "GITHUB_TOKEN" for item in report["findings"]))
        self.assertFalse(any(
            item["source"] == "security_audit" and item["code"] == "GITHUB_TOKEN"
            for item in alerts["alerts"]
        ))
        self.assertNotIn("ghp_", json.dumps(alerts))

    @unittest.skipUnless(os.name == "nt", "Windows junction integration test")
    def test_junction_escape_is_reported_and_never_scanned_copied_or_moved(self):
        init_workspace(self.base)
        outside = Path(self.temp.name) / "outside-sensitive"
        outside.mkdir()
        secret = outside / "outside-secret.md"
        secret.write_text(
            "OUTSIDE_JUNCTION_SECRET_9f3c",
            encoding="utf-8",
        )
        link = self.base / "02_Knowledge" / "Notes" / "OutsideLink"
        created = subprocess.run(
            [
                "cmd.exe",
                "/c",
                "mklink",
                "/J",
                str(link),
                str(outside),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            created.returncode,
            0,
            msg=created.stdout + created.stderr,
        )

        security = audit_security(self.base)
        self.assertTrue(any(
            item["code"] == "LINK_ESCAPES_WORKSPACE"
            and item["path"].endswith("OutsideLink")
            for item in security["findings"]
        ))

        database = Path(self.temp.name) / "search" / "workspace.db"
        search_build = build_search_database(
            self.base,
            database,
            include_content=True,
        )
        self.assertGreaterEqual(search_build["link_entries_skipped"], 1)
        self.assertEqual(
            search_database(database, "OUTSIDE_JUNCTION_SECRET_9f3c")["count"],
            0,
        )

        manifest = build_device_manifest(
            self.base,
            "junction-test",
            scopes=["02_Knowledge"],
        )
        self.assertEqual(manifest["status"], "blocked")
        self.assertTrue(any(
            item["reason"] == "reparse_point"
            and item["path"].endswith("OutsideLink")
            for item in manifest["unverified"]
        ))

        nas = Path(self.temp.name) / "empty-nas"
        nas.mkdir()
        locations = build_location_snapshot(self.base, nas)
        self.assertFalse(any(
            "OutsideLink" in item["relative"]
            for item in locations["files"]
        ))

        snapshots = Path(self.temp.name) / "snapshots"
        with self.assertRaisesRegex(ValueError, "UNSAFE_REPARSE_POINT"):
            create_snapshot(
                self.base,
                snapshots,
                apply=True,
                snapshot_name="junction-escape",
            )
        self.assertFalse((snapshots / "junction-escape").exists())
        self.assertEqual(
            list(snapshots.glob(".junction-escape.partial-*")),
            [],
        )

        inbox_link = self.base / "00_Inbox" / "ToSort" / "OutsideInbox"
        inbox_created = subprocess.run(
            [
                "cmd.exe",
                "/c",
                "mklink",
                "/J",
                str(inbox_link),
                str(outside),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            inbox_created.returncode,
            0,
            msg=inbox_created.stdout + inbox_created.stderr,
        )
        preview = scan_inbox(self.base)
        self.assertFalse(any(
            "outside-secret.md" in item["source"]
            for item in preview["plans"]
        ))
        self.assertTrue(secret.is_file())

    @unittest.skipUnless(os.name == "nt", "Windows junction export integration test")
    def test_junction_escape_cannot_enter_product_exports_or_version_scan(self):
        source = Path(self.temp.name) / "product-source"
        (source / "scripts" / "python").mkdir(parents=True)
        (source / "scripts" / "python" / "workspace_cli.py").write_text(
            "print('ok')",
            encoding="utf-8",
        )
        (source / "docs").mkdir()
        (source / "VERSION").write_text("2.0-test", encoding="utf-8")
        (source / "README.md").write_text("release", encoding="utf-8")
        (source / "release_v2_RELEASE.zip").write_bytes(b"local")
        outside = Path(self.temp.name) / "outside-product"
        outside.mkdir()
        secret = outside / "release_v999_RELEASE.zip"
        secret.write_bytes(b"outside-secret")
        link = source / "docs" / "OutsideDocs"
        created = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(created.returncode, 0, msg=created.stdout + created.stderr)

        destination = Path(self.temp.name) / "packages"
        with self.assertRaisesRegex(ValueError, "UNSAFE_EXPORT_SOURCE_LINK"):
            build_recovery_kit(source, destination)
        with self.assertRaisesRegex(ValueError, "UNSAFE_EXPORT_SOURCE_LINK"):
            build_distribution(source, destination)
        with self.assertRaisesRegex(ValueError, "UNSAFE_RELEASE_SOURCE_LINK"):
            build_release(source, destination / "release")

        latest = scan_latest(source)
        self.assertEqual(latest["candidate_count"], 4)
        self.assertNotIn("v999", json.dumps(latest))

        migration_plan = Path(self.temp.name) / "migration-plan.csv"
        migrated = subprocess.run(
            [
                sys.executable,
                str(ROOT / "migration" / "legacy-scan.py"),
                str(source),
                "--output",
                str(migration_plan),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(migrated.returncode, 0, msg=migrated.stdout + migrated.stderr)
        self.assertNotIn("release_v999_RELEASE.zip", migration_plan.read_text(encoding="utf-8-sig"))
        self.assertTrue(secret.is_file())

    def test_security_posture_detects_broad_acl_and_unverified_encryption(self):
        init_workspace(self.base)
        probe = {
            "generated_at": "2099-01-01T00:00:00+00:00",
            "platform": "windows",
            "probe_status": "ok",
            "protected_paths": [{
                "relative": "07_Admin/Private",
                "exists": True,
                "acl_query_status": "ok",
                "owner_sid": "S-1-5-21-1",
                "owner_is_current_user": True,
                "inheritance_protected": False,
                "access": [{
                    "sid": "S-1-5-11",
                    "access_type": "Allow",
                    "inherited": True,
                    "can_read": True,
                    "can_write": True,
                }],
            }],
            "volume": {
                "mount_point": "D:\\",
                "query_status": "unavailable",
                "query_code": "ACCESS_DENIED",
                "evidence_source": "none",
            },
        }
        report = evaluate_security_posture(self.base, probe)
        self.assertEqual(report["status"], "error")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("PROTECTED_PATH_BROAD_WRITE", codes)
        self.assertIn("PROTECTED_PATH_ACL_INHERITED", codes)
        self.assertIn("VOLUME_ENCRYPTION_EVIDENCE_UNAVAILABLE", codes)
        self.assertNotIn("S-1-5-21-1", json.dumps(report))
        outputs = save_security_posture(
            report,
            self.base / "08_Indexes" / "Security" / "security-posture.json",
        )
        self.assertTrue(all(path.is_file() for path in outputs))
        alerts = build_alert_center(self.base)
        self.assertTrue(any(
            item["source"] == "security_posture"
            and item["code"] == "PROTECTED_PATH_BROAD_WRITE"
            for item in alerts["alerts"]
        ))

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_acl_hardening_previews_backs_up_applies_and_is_idempotent(self):
        init_workspace(self.base)
        script = (
            ROOT
            / "scripts"
            / "windows"
            / "Protect-WorkspaceSensitiveDirectories.ps1"
        )
        report_path = (
            self.base
            / "08_Indexes"
            / "Security"
            / "acl-hardening.json"
        )
        protected = [
            self.base / "07_Admin" / "Accounts",
            self.base / "07_Admin" / "Certificates",
            self.base / "07_Admin" / "Private",
        ]
        before = {
            str(path): sha256_file(path / "README.md")
            for path in protected
        }
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-WorkspacePath",
            str(self.base),
        ]

        def invoke(*extra):
            return subprocess.run(
                [*command, *extra],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        def run(*extra):
            result = invoke(*extra)
            self.assertEqual(
                result.returncode,
                0,
                msg=result.stdout + result.stderr,
            )
            return json.loads(
                report_path.read_text(encoding="utf-8-sig")
            )

        unsafe_output = self.base / "acl-hardening-outside-index.json"
        rejected_output = invoke("-OutputPath", str(unsafe_output))
        self.assertNotEqual(rejected_output.returncode, 0)
        self.assertFalse(unsafe_output.exists())
        unsafe_backup = protected[0] / "unsafe-acl-backup"
        rejected_backup = invoke(
            "-Apply",
            "-BackupRoot",
            str(unsafe_backup),
        )
        self.assertNotEqual(rejected_backup.returncode, 0)
        self.assertFalse(unsafe_backup.exists())

        preview = run()
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["summary"]["changes_required"], 3)
        self.assertEqual(preview["summary"]["changed"], 0)
        self.assertIsNone(preview["backup_root"])

        applied = run("-Apply")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["summary"]["changed"], 3)
        self.assertEqual(applied["summary"]["verified"], 3)
        self.assertEqual(applied["summary"]["content_overwrites"], 0)
        self.assertEqual(applied["summary"]["content_deletions"], 0)
        backup = Path(applied["backup_root"])
        for name in (
            "Accounts.acl",
            "Certificates.acl",
            "Private.acl",
            "RESTORE.md",
        ):
            self.assertTrue((backup / name).is_file())
        for path in protected:
            self.assertEqual(
                before[str(path)],
                sha256_file(path / "README.md"),
            )

        repeated = run("-Apply")
        self.assertEqual(repeated["status"], "unchanged")
        self.assertEqual(repeated["summary"]["changes_required"], 0)
        self.assertEqual(repeated["summary"]["changed"], 0)
        self.assertIsNone(repeated["backup_root"])

    def test_security_posture_accepts_isolated_acl_and_verified_encryption(self):
        init_workspace(self.base)
        probe = {
            "generated_at": "2099-01-01T00:00:00+00:00",
            "platform": "windows",
            "probe_status": "ok",
            "protected_paths": [{
                "relative": "07_Admin/Private",
                "exists": True,
                "acl_query_status": "ok",
                "owner_sid": "S-1-5-21-1",
                "owner_is_current_user": True,
                "inheritance_protected": True,
                "access": [{
                    "sid": "S-1-5-18",
                    "access_type": "Allow",
                    "inherited": False,
                    "can_read": True,
                    "can_write": True,
                }],
            }],
            "volume": {
                "mount_point": "D:\\",
                "query_status": "ok",
                "query_code": "CACHED_ELEVATED_EVIDENCE",
                "evidence_source": "cached-elevated",
                "evidence_age_hours": 1.5,
                "volume_status": "FullyEncrypted",
                "protection_status": "On",
                "encryption_percentage": 100,
            },
        }
        report = evaluate_security_posture(self.base, probe)
        self.assertEqual(report["status"], "healthy")
        self.assertTrue(report["summary"]["volume_encryption_verified"])
        self.assertEqual(
            report["summary"]["volume_evidence_source"],
            "cached-elevated",
        )
        self.assertEqual(report["summary"]["volume_evidence_age_hours"], 1.5)
        self.assertEqual(report["findings"], [])

    @unittest.skipUnless(os.name == "nt", "Windows encryption evidence integration test")
    def test_security_probe_accepts_only_bound_fresh_cached_evidence(self):
        init_workspace(self.base)
        script = (
            ROOT
            / "scripts"
            / "windows"
            / "Probe-WorkspaceSecurityPosture.ps1"
        )
        output = (
            self.base
            / "08_Indexes"
            / "Security"
            / "security-posture-probe.json"
        )
        evidence = (
            self.base
            / "08_Indexes"
            / "Security"
            / "encryption-evidence.json"
        )
        drive_letter = self.base.anchor.rstrip("\\").rstrip(":")
        volume_result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                (
                    f"(Get-Volume -DriveLetter '{drive_letter}' "
                    "-ErrorAction Stop).UniqueId"
                ),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            volume_result.returncode,
            0,
            msg=volume_result.stdout + volume_result.stderr,
        )
        volume_id = volume_result.stdout.strip()
        marker_hash = sha256_file(self.base / ".workspace-os.json")
        report = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "platform": "windows",
            "source": "elevated-bitlocker",
            "privacy_mode": "hashed-volume-id-no-user-identities",
            "workspace_marker_sha256": marker_hash,
            "mount_point": self.base.anchor,
            "filesystem": "NTFS",
            "volume_id_hash": hashlib.sha256(
                volume_id.lower().encode("utf-8")
            ).hexdigest(),
            "query_status": "ok",
            "volume_status": "FullyEncrypted",
            "protection_status": "On",
            "encryption_percentage": 100,
            "encryption_method": "XtsAes256",
        }
        evidence.parent.mkdir(parents=True, exist_ok=True)

        def run_probe(payload):
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-WorkspacePath",
                    str(self.base),
                    "-OutputPath",
                    str(output),
                    "-EncryptionEvidencePath",
                    str(evidence),
                    "-CachedEvidenceOnly",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=result.stdout + result.stderr,
            )
            return json.loads(output.read_text(encoding="utf-8-sig"))

        accepted = run_probe(report)
        self.assertEqual(accepted["volume"]["query_status"], "ok")
        self.assertEqual(
            accepted["volume"]["query_code"],
            "CACHED_ELEVATED_EVIDENCE",
        )
        self.assertEqual(
            accepted["volume"]["evidence_source"],
            "cached-elevated",
        )
        self.assertEqual(accepted["volume"]["cached_evidence_status"], "valid")
        self.assertEqual(accepted["volume"]["live_query_code"], "CACHED_ONLY")

        mismatched = dict(report)
        mismatched["workspace_marker_sha256"] = "0" * 64
        rejected = run_probe(mismatched)
        self.assertEqual(rejected["volume"]["query_status"], "unavailable")
        self.assertEqual(
            rejected["volume"]["cached_evidence_status"],
            "workspace-mismatch",
        )

        stale = dict(report)
        stale["generated_at"] = (
            datetime.now(timezone.utc) - timedelta(days=9)
        ).isoformat()
        rejected = run_probe(stale)
        self.assertEqual(rejected["volume"]["query_status"], "unavailable")
        self.assertEqual(rejected["volume"]["cached_evidence_status"], "stale")

    def test_alert_center_surfaces_recovery_kit_retention_issues(self):
        init_workspace(self.base)
        report_path = self.base / "08_Indexes" / "Recovery" / "recovery-kit-retention.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps({
            "orphans": [{"archive": "orphan.zip"}],
            "report_issues": [{"report": "missing.json", "error": "missing"}],
        }), encoding="utf-8")
        report = build_alert_center(self.base)
        codes = {
            item["code"]
            for item in report["alerts"]
            if item["source"] == "recovery"
        }
        self.assertIn("RECOVERY_KIT_ORPHANS", codes)
        self.assertIn("RECOVERY_KIT_PROTECTION_REPORT_INVALID", codes)


if __name__ == "__main__": unittest.main()
