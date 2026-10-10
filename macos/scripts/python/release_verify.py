"""Run the repeatable, read-only release verification gates for Workspace OS."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def run(command: list[str], cwd: Path) -> dict[str, object]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "passed": completed.returncode == 0,
    }


def python_compile_check(directory: Path) -> dict[str, object]:
    """Compile Python sources in memory so this gate never creates __pycache__."""
    failures: list[dict[str, str]] = []
    checked = 0
    for path in sorted(directory.rglob("*.py")):
        checked += 1
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append({"path": str(path), "error": str(exc)})
    return {"passed": not failures, "checked_files": checked, "failures": failures}


def package_content_check(package: Path, source: Path) -> dict[str, object]:
    required = {
        "WorkspaceOS.cmd",
        "docs/verification-matrix.md",
        "docs/completion-audit.md",
        "scripts/python/release_verify.py",
        "scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1",
        "scripts/python/workspace_cli.py",
    }
    with zipfile.ZipFile(package) as bundle:
        files = [name for name in bundle.namelist() if not name.endswith("/")]
        prefix = files[0].split("/", 1)[0] + "/"
        missing = sorted(prefix + item for item in required if prefix + item not in files)
        forbidden_markers = {".env", "credentials", "secrets", "tokens", "passwords"}
        forbidden = sorted(
            name for name in files
            if any(part.lower() in forbidden_markers for part in Path(name[len(prefix):]).parts)
        )
        audit_text = bundle.read(prefix + "docs/completion-audit.md").decode("utf-8", errors="replace")
        audit_markers = ["仍需真实环境完成", "Restic", "没有被模拟结果替代"]
        audit_issues = [marker for marker in audit_markers if marker not in audit_text]
        packaged = bundle.read(prefix + "scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    package_hash = hashlib.sha256(packaged).hexdigest()
    return {"passed": not missing and not forbidden and not audit_issues and source_hash == package_hash, "missing": missing, "forbidden": forbidden, "audit_issues": audit_issues, "source_sha256": source_hash, "package_sha256": package_hash}


def latest_pointer_check(pointer: Path) -> dict[str, object]:
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        package_name = str(payload["package"])
        package = pointer.parent / package_name
        actual = hashlib.sha256(package.read_bytes()).hexdigest()
        expected = str(payload["sha256"]).lower()
        return {"passed": actual == expected, "pointer": str(pointer), "package": str(package), "expected_sha256": expected, "actual_sha256": actual}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"passed": False, "pointer": str(pointer), "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--latest-pointer", type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output; omitted means read-only")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    package = args.package.resolve()
    checks: dict[str, object] = {}
    checks["unit_tests"] = run([sys.executable, "-m", "unittest", "tests.test_workspace_os", "-q"], workspace)
    checks["python_compile"] = python_compile_check(workspace / "scripts/python")
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell:
        script = "$bad=@(); Get-ChildItem scripts/windows -Filter *.ps1 -File | ForEach-Object { try { [scriptblock]::Create((Get-Content -Raw -LiteralPath $_.FullName)) | Out-Null } catch { $bad += $_.FullName } }; if($bad.Count){ exit 1 }"
        checks["powershell_parse"] = run([powershell, "-NoProfile", "-Command", script], workspace)
    else:
        checks["powershell_parse"] = {"passed": False, "skipped": True, "reason": "PowerShell not found"}
    checks["portable_manifest"] = run([sys.executable, "scripts/python/portable_package.py", "--verify", str(package)], workspace)
    checks["package_content"] = package_content_check(package, workspace / "scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1")
    if args.latest_pointer:
        checks["latest_pointer"] = latest_pointer_check(args.latest_pointer.resolve())
    passed = all(bool(value.get("passed")) for value in checks.values() if isinstance(value, dict))
    result = {"workspace": str(workspace), "package": str(package), "passed": passed, "checks": checks}
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".partial")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
