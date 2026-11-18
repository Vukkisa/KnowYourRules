#!/usr/bin/env python3
"""Deployment manifest: which files the production start command and the Pages workflow actually need, derived from the code, and a
clean-export check that proves the service starts from exactly those files.

    python scripts/deployment_manifest.py --write            # (re)write deploy/deployment-manifest.json from the code
    python scripts/deployment_manifest.py --check            # the manifest is current, every file exists, nothing evidence/secret is listed
    python scripts/deployment_manifest.py --export DIR       # copy ONLY the required files into DIR (a stand-in for a clean checkout)
    python scripts/deployment_manifest.py --smoke DIR        # run the start chain from DIR with no network and no real credentials

Nothing here touches git, the index, the lifecycle registry or any account. `git_state` in the manifest is information for the
operator (which of these files are not committed yet), never an action.
"""
import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "deploy" / "deployment-manifest.json"

# Entry points: the uvicorn app, the start-command validator, the Pages build.
ENTRIES = {"backend/server.py": "uvicorn target (deploy/render.yaml startCommand)",
           "scripts/check_cloud_env.py": "run before uvicorn by the start command",
           "scripts/build_pages.py": "run by .github/workflows/pages.yml"}

# Not importable but read at runtime / build time.
STATIC = {
    "backend/nomic_local.py": ("runtime-code", "the in-process nomic-embed-text-v1.5 engine; imported when EMBEDDING_PROVIDER=inprocess_nomic"),
    "deploy/render.yaml": ("config", "Render Blueprint (set the Blueprint Path to deploy/render.yaml in the Render dashboard)"),
    "deploy/cloud.env.example": ("config", "placeholders only: the variables the operator sets in the Render dashboard"),
    "deploy/deployment-manifest.json": ("config", "this manifest"),
    "requirements-cloud.txt": ("config", "the only dependency list Render installs (no torch, no notebooks)"),
    ".github/workflows/pages.yml": ("ci", "manual GitHub Pages deployment workflow"),
    "legal-status/source-status.json": ("runtime-data", "text-currency status of each source (unverified until independently confirmed)"),
    "frontend/index.html": ("runtime-data", "the page; served by the API and copied by the Pages build"),
    "frontend/render.js": ("runtime-data", "sanitising Markdown renderer for the page"),
    "tests/test_frontend.py": ("ci", "run by the Pages workflow before the build"),
    "tests/test_pages_build.py": ("ci", "run by the Pages workflow before the build"),
    "tests/frontend/sanitize_test.html": ("ci", "browser test page referenced by tests/test_frontend.py"),
    "scripts/deployment_manifest.py": ("operator-tool", "this tool"),
    "scripts/verify_runtime_config.py": ("operator-tool", "offline check of the Render blueprint, env names, requirements and wheels"),
}
# Never part of a deployment, whatever imports them: evidence, local state, secrets.
EXCLUDED_PREFIXES = ("eval/", "chroma_", "legal/", "build/", ".env", "docs/", "research/", "notebooks/", "data/", "reference/")
SECRET_NAMES = (".env", "telangana-approval.json", "trusted-keys.json", "approval.sig")


def _module_path(mod: str):
    parts = mod.split(".")
    for cand in (ROOT.joinpath(*parts).with_suffix(".py"), ROOT.joinpath(*parts, "__init__.py")):
        if cand.is_file():
            return cand.relative_to(ROOT).as_posix()
    return None


def imports_of(rel: str):
    """(top_level, lazy): project modules a file imports at import time, and inside functions."""
    tree = ast.parse((ROOT / rel).read_text("utf-8"))
    top, lazy = set(), set()

    def visit(node, in_func):
        for child in ast.iter_child_nodes(node):
            fn = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if isinstance(child, ast.Import):
                names = [a.name for a in child.names]
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                names = [child.module] + [f"{child.module}.{a.name}" for a in child.names]
            else:
                visit(child, fn)
                continue
            for n in names:
                p = _module_path(n)
                if p:
                    (lazy if in_func else top).add(p)
            visit(child, fn)
    visit(tree, False)
    return top, lazy


def closure():
    """(required_at_import, operator_only_lazy) as sorted relative paths, traced from the entry points."""
    seen, lazy_seen = {}, {}
    todo = list(ENTRIES)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        top, lazy = imports_of(f)
        seen[f] = top
        todo += [p for p in top if p not in seen]
        for p in lazy:
            lazy_seen.setdefault(p, f)
    # lazily imported modules need their own import-time closure too (they are only run by operator tools)
    lazy_only = {}
    todo = [p for p in lazy_seen if p not in seen]
    while todo:
        f = todo.pop()
        if f in lazy_only or f in seen:
            continue
        top, lazy = imports_of(f)
        lazy_only[f] = True
        todo += [p for p in top | lazy if p not in seen and p not in lazy_only]
    return sorted(seen), sorted(lazy_only)


def git_state(paths):
    out = {}
    try:
        tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n"))
        status = {line[3:]: line[:2] for line in subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=ROOT,
                                                                capture_output=True, text=True, check=True).stdout.split("\n") if line}
    except (OSError, subprocess.CalledProcessError):
        return {p: "unknown" for p in paths}
    for p in paths:
        out[p] = ("untracked" if p not in tracked else ("modified" if status.get(p, "  ").strip() else "committed"))
    return out


def build() -> dict:
    required, lazy = closure()
    files = {}
    for f in required:
        files[f] = {"category": "runtime-code", "purpose": ENTRIES.get(f, "imported at start by the backend")}
    for f in lazy:
        files[f] = {"category": "operator-only-code", "purpose": "imported lazily by operator paths (ingest, lifecycle CLI); not used while serving"}
    for f, (cat, why) in STATIC.items():
        files[f] = {"category": cat, "purpose": why}
    for f in files:
        files[f]["exists"] = (ROOT / f).is_file()
    states = git_state(sorted(files))
    for f in files:
        files[f]["git_state"] = states[f]
    return {
        "schema_version": 1,
        "note": "Derived by scripts/deployment_manifest.py from the import graph of the entry points. Evidence (eval/), the index "
                "(chroma_*), the lifecycle registry (legal/), secrets (.env, approval and key files) and tests other than the two "
                "Pages-workflow tests are NOT part of a deployment. Render clones the repository; this lists what must be COMMITTED for the "
                "start command and the Pages workflow to work.",
        "entry_points": ENTRIES,
        "excluded": {"prefixes": list(EXCLUDED_PREFIXES), "secret_file_names": list(SECRET_NAMES)},
        "files": dict(sorted(files.items())),
    }


def problems(manifest: dict) -> list:
    out = []
    for f, info in manifest["files"].items():
        if not (ROOT / f).is_file():
            out.append(f"listed file is missing: {f}")
        if f.startswith(EXCLUDED_PREFIXES) or Path(f).name in SECRET_NAMES:
            out.append(f"evidence, local state or a secret is listed: {f}")
    required, lazy = closure()
    for f in required:
        if f not in manifest["files"]:
            out.append(f"imported at start but not in the manifest: {f}")
    return out


def export(dest: Path, manifest: dict):
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty")
    for f in manifest["files"]:
        src, dst = ROOT / f, dest / f
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    return sorted(manifest["files"])


def smoke(dest: Path) -> dict:
    """Run the start chain from a directory that holds only the manifest's files. No network (the object store points at a closed
    loopback port), no real credentials, no index, no registry."""
    env_base = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    cloud = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2",
             "R2_ENDPOINT": "http://127.0.0.1:9", "R2_BUCKET": "smoke", "R2_ACCESS_KEY_ID": "smoke-id", "R2_SECRET_ACCESS_KEY": "smoke-secret",
             "EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5",
             "EMBEDDING_API_URL": "http://127.0.0.1:9/v1", "EMBEDDING_API_KEY": "smoke-key", "TG_CORS_ORIGINS": "https://pages.invalid",
             "TG_SNAPSHOT_PIN_SHA256": "ab" * 32, "TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS": "5", "TG_SNAPSHOT_RETRY_BASE_SECONDS": "0.1",
             "TG_SNAPSHOT_RETRY_MAX_DELAY_SECONDS": "1", "GROQ_API_KEY": "smoke", "TG_SNAPSHOT_WORK_DIR": str(dest / ".smoke-work")}
    results = {}

    def run(name, args, env=None):
        p = subprocess.run([sys.executable, *args], cwd=dest, env={**env_base, **(env or {})}, capture_output=True, text=True, timeout=300)
        results[name] = {"returncode": p.returncode, "stdout_tail": p.stdout.strip().splitlines()[-6:], "stderr_tail": p.stderr.strip().splitlines()[-4:]}
        return p
    run("check_cloud_env", ["scripts/check_cloud_env.py"], cloud)
    run("build_pages", ["scripts/build_pages.py", "--api-base", "https://smoke-api.invalid", "--out", str(dest / ".smoke-pages")])
    run("server_import_and_probes", ["-c", (
        "import json,sys\nfrom fastapi.testclient import TestClient\nimport backend.server as s\nc = TestClient(s.app)\n"
        "r = c.get('/ready')\nchat = c.post('/chat', json={'message': 'What is Rule 6?', 'session_id': 'smoke'}).json()\n"
        "print(json.dumps({'health': c.get('/health').status_code, 'ready': r.status_code, 'failed': sorted(k for k, v in r.json()['checks'].items() if v != 'ok'),"
        " 'chat_kind': chat['kind'], 'snapshot_state': s.SNAPSHOT.state, 'attempts': s.SNAPSHOT.attempts}))")], cloud)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--export", metavar="DIR")
    g.add_argument("--smoke", metavar="DIR", help="DIR must come from --export")
    a = ap.parse_args(argv)
    if a.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        m = build()
        MANIFEST.write_text(json.dumps(m, indent=1) + "\n", "utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)}: {len(m['files'])} files")
        return 0
    if a.check:
        if not MANIFEST.is_file():
            print("deploy/deployment-manifest.json is missing: run --write")
            return 1
        m = json.loads(MANIFEST.read_text("utf-8"))
        found = problems(m)
        fresh = build()
        if set(fresh["files"]) != set(m["files"]):
            found.append("the manifest is out of date: run --write")
        for f in found:
            print("PROBLEM:", f)
        uncommitted = sorted(f for f, i in fresh["files"].items() if i["git_state"] != "committed")
        print(f"{len(m['files'])} files listed; {len(uncommitted)} not committed yet (information, not an error)")
        return 1 if found else 0
    if a.export:
        files = export(Path(a.export), json.loads(MANIFEST.read_text("utf-8")))
        print(f"exported {len(files)} files to {a.export}")
        return 0
    res = smoke(Path(a.smoke))
    print(json.dumps(res, indent=1))
    return 0 if all(r["returncode"] == 0 for r in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
