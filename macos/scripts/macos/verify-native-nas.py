"""Opt-in verification on isolated temporary directories; no real diary touched."""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from dashboard_sync_server import SyncJobs

nas_inbox = Path(sys.argv[1])
if not nas_inbox.is_dir():
    raise SystemExit("NAS test parent is unavailable")
with tempfile.TemporaryDirectory(prefix="WorkspaceOS-verification-", dir=nas_inbox) as remote_dir, \
     tempfile.TemporaryDirectory(prefix="WorkspaceOS-verification-") as local_dir:
    local, remote = Path(local_dir).resolve(), Path(remote_dir).resolve()
    jobs = SyncJobs(local, remote, local / "08_Indexes/file-locations.html")
    payload = b"WorkspaceOS-2.0.6-SMB-verification\n" * 262144
    relative = "中文 空格/上传验证.bin"
    source = local / relative; source.parent.mkdir(); source.write_bytes(payload)
    started = time.monotonic()
    jobs._copy_one({"source": source, "target": remote / relative}, "safe")
    expected = hashlib.sha256(payload).hexdigest()
    assert hashlib.sha256((remote / relative).read_bytes()).hexdigest() == expected
    try:
        jobs._copy_one({"source": source, "target": remote / relative}, "safe")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Safe mode accepted an existing target")
    target = local / "下载验证.bin"
    jobs._copy_one({"source": remote / relative, "target": target}, "safe")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    empty = local / "空文件"; empty.touch()
    jobs._copy_one({"source": empty, "target": remote / "空文件"}, "safe")
    assert (remote / "空文件").stat().st_size == 0
    entry = {"direction": "to_nas", "mode": "safe", "errors": []}
    log = Path(jobs._append_obsidian_sync_log(entry, [relative]))
    first = log.read_bytes()
    jobs._append_obsidian_sync_log(entry, ["空文件"])
    assert log.read_bytes().startswith(first)
    local_log = local / log.relative_to(remote)
    local_log.parent.mkdir(parents=True)
    local_log.write_text("本地独有测试记录", encoding="utf-8")
    jobs._pull_obsidian_log_to_local(str(log))
    assert local_log.read_bytes() == log.read_bytes()
    assert Path(jobs.last_preserved_log).read_text() == "本地独有测试记录"
    result = jobs.refresh_snapshot(live_nas=True)
    assert result.get("published"), result
    assert (remote / "08_Indexes/file-locations.html").is_file()
    print(json.dumps({"passed": True, "bytes_each_direction": len(payload),
                      "sha256": expected, "seconds": round(time.monotonic() - started, 2),
                      "checks": ["upload", "download", "no-overwrite", "unicode", "empty-file",
                                 "append-log", "preserve-local-log", "publish-both"]}))
print("Isolated verification fixtures removed; user files and real daily notes untouched.")
