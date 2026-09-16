"""Re-run isolated existing suites; store evidence without changing product code."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = os.getenv("LINGOU_VALIDATION_RUN_ID", "mvp-20260916-01")
OUT = ROOT / "docs" / "validation" / RUN_ID
PYTHON = Path("/Users/bytedance/Documents/Codex/2026-09-08/du/work/step-01/runtime-venv/bin/python")


def capture(args, cwd=ROOT, timeout=120):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def fingerprint():
    listed = capture(["git", "ls-files", "-co", "--exclude-standard"]).stdout.splitlines()
    files = {}
    for name in sorted(set(listed)):
        path = ROOT / name
        if path.is_file() and not name.startswith("docs/validation/"):
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def runtime_metadata():
    root = ROOT / "data"
    return sorted([
        [str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_mode]
        for p in root.rglob("*") if p.is_file()
    ])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": RUN_ID,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": capture([str(PYTHON), "--version"]).stdout.strip(),
        "head": capture(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "source_sha256": fingerprint(),
        "runtime_metadata_before": runtime_metadata(),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    jobs = [
        (p.stem, [str(PYTHON), "-B", str(p.relative_to(ROOT / "services/companion-server")), "-v"],
         ROOT / "services/companion-server")
        for p in sorted((ROOT / "services/companion-server/tests").glob("test_*.py"))
    ]
    jobs += [("hardware_adapter", [str(PYTHON), "-B", "-m", "unittest", "discover",
                                   "-s", "hardware_adapter/tests", "-v"], ROOT)]
    jobs += [(name.replace(":", "_"), ["npm", "run", name], ROOT / "apps/soul-studio-h5")
             for name in ["test:auth", "test:flow", "test:voice", "test:audio", "build"]]
    jobs += [("pip_check", [str(PYTHON), "-m", "pip", "check"], ROOT)]
    results = []
    for name, args, cwd in jobs:
        proc = capture(args, cwd)
        log = OUT / f"baseline-{name}.log"
        log.write_text(proc.stdout + proc.stderr)
        results.append({"name": name, "returncode": proc.returncode,
                        "evidence": log.name, "command": args})
        print(f"{name}: exit={proc.returncode}", flush=True)
        (OUT / "baseline-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    assert runtime_metadata() == manifest["runtime_metadata_before"], "runtime data changed"
    print("runtime metadata unchanged", flush=True)
    return int(any(row["returncode"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
