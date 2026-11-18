#!/usr/bin/env python3
"""Offline verification of the Render runtime configuration (no deployment, no account, no install).

    python scripts/verify_runtime_config.py                 # blueprint, start command, env names, requirements: offline
    python scripts/verify_runtime_config.py --resolve OUT   # ALSO ask pip (dry run: nothing is installed) to resolve requirements-cloud.txt
                                                            # for CPython 3.11 on Linux x86_64 and write the resolved wheels to OUT (network)
    python scripts/verify_runtime_config.py --json

Exit 0 only when there is no FAIL. WARN lines are things to read, not blockers.
"""
import argparse
import ast
import json
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HEAVY = {"torch", "transformers", "sentence-transformers", "faiss-cpu", "faiss", "unstructured", "jupyter", "notebook", "langchain-ollama",
         "langchain-groq", "boto3", "botocore", "huggingface-hub", "onnxruntime", "scikit-learn", "pandas", "tensorflow", "ollama"}
SECRETISH = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)
REQUIRED_LITERALS = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2"}
# Variables the platform or the interpreter supplies, or that are read only by operator tools: not expected in the blueprint.
PLATFORM = {"PORT", "RENDER", "HOME", "PATH", "PYTHON_VERSION", "PYTHONUNBUFFERED", "MALLOC_ARENA_MAX", "ANONYMIZED_TELEMETRY",
            "RENDER_EXTERNAL_URL", "WEB_CONCURRENCY", "TMPDIR"}


class Report:
    def __init__(self):
        self.items = []

    def add(self, status, name, detail=""):
        self.items.append({"status": status, "check": name, "detail": detail})

    @property
    def failed(self):
        return any(i["status"] == "FAIL" for i in self.items)


def _read_yaml(path):
    try:
        import yaml
    except ImportError:
        return None
    return yaml.safe_load(Path(path).read_text("utf-8"))


def env_names_in(rel):
    """Names of environment variables a Python file reads, from the common access patterns used in this code base."""
    text = (ROOT / rel).read_text("utf-8")
    names = set(re.findall(r'(?:environ|env)\.get\(\s*"([A-Z][A-Z0-9_]+)"', text))
    names |= set(re.findall(r'(?:environ|env)\[\s*"([A-Z][A-Z0-9_]+)"\s*\]', text))
    names |= set(re.findall(r'\b(?:_flag|env_flag|_num|_secret)\(\s*(?:env|environ)?,?\s*"([A-Z][A-Z0-9_]+)"', text))
    names |= set(re.findall(r'\b_secret\(\s*env\s*,\s*"([A-Z][A-Z0-9_]+)"', text))
    names |= set(re.findall(r'\bnum\(\s*"([A-Z][A-Z0-9_]+)"', text))
    return names


def check_blueprint(rep: Report, manifest):
    bp_path = ROOT / "deploy" / "render.yaml"
    doc = _read_yaml(bp_path)
    if doc is None:
        rep.add("WARN", "blueprint parse", "PyYAML is not installed: the blueprint was not parsed")
        return {}
    services = doc.get("services") or []
    web = [s for s in services if s.get("type") == "web"]
    if len(web) != 1:
        rep.add("FAIL", "blueprint has exactly one web service", f"found {len(web)}")
        return {}
    svc = web[0]
    rep.add("PASS", "blueprint location", "deploy/render.yaml: Render's default is a root render.yaml, but the dashboard's Blueprint Path field "
                                          "accepts another path (verified against Render's Blueprint docs in Stage 7C)")
    for key, want in (("runtime", "python"), ("plan", "free")):
        rep.add("PASS" if svc.get(key) == want else "FAIL", f"service {key}", f"{svc.get(key)!r}")
    start = svc.get("startCommand", "")
    rep.add("PASS" if re.search(r"\bpython scripts/check_cloud_env\.py\s*&&\s*exec uvicorn backend\.server:app\b", start) else "FAIL",
            "start command validates the environment, then exec's uvicorn on backend.server:app", start[:120])
    rep.add("PASS" if re.search(r"--workers 1\b", start) else "FAIL", "one worker (an explicit flag, so Render's WEB_CONCURRENCY cannot raise it)")
    rep.add("PASS" if "--host 0.0.0.0" in start and "--port $PORT" in start else "FAIL", "binds 0.0.0.0 on $PORT")
    for token in re.findall(r"[\w./-]+\.py", start) + ["backend/server.py"]:
        rep.add("PASS" if (ROOT / token).is_file() else "FAIL", f"start command file exists: {token}")
        if manifest and token not in manifest["files"]:
            rep.add("FAIL", f"start command file is in the deployment manifest: {token}")
    build = svc.get("buildCommand", "")
    rep.add("PASS" if re.fullmatch(r"pip install --no-cache-dir -r requirements-cloud\.txt", build) else "FAIL",
            "build installs only requirements-cloud.txt", build)
    hc = svc.get("healthCheckPath")
    server_src = (ROOT / "backend" / "server.py").read_text("utf-8")
    rep.add("PASS" if hc and f'@app.get("{hc}")' in server_src else "FAIL", "healthCheckPath is a route of the app", str(hc))
    rep.add("PASS" if hc == "/ready" else "WARN", "health check is the READINESS route",
            "Render stops routing to an instance whose check fails for 15 s and restarts it after 60 s; a failed restore therefore "
            "restarts and retries instead of staying up and unready" if hc == "/ready" else f"health check is {hc}: liveness only")
    envs = {e["key"]: e for e in svc.get("envVars", [])}
    pv = str((envs.get("PYTHON_VERSION") or {}).get("value", ""))
    rep.add("PASS" if re.fullmatch(r"\d+\.\d+\.\d+", pv) else "FAIL", "PYTHON_VERSION is a full x.y.z (Render requires it)", pv)
    for k, want in REQUIRED_LITERALS.items():
        got = str((envs.get(k) or {}).get("value", ""))
        rep.add("PASS" if got == want else "FAIL", f"{k}={want}", got or "(missing)")
    for k, e in envs.items():
        if SECRETISH.search(k) and "value" in e and not (k.endswith("_FILE") and str(e["value"]).startswith(("/etc/secrets/", "legal-status/"))):
            rep.add("FAIL", f"secret-looking variable has a literal value in git: {k}")
    for k in ("TG_SNAPSHOT_PIN_SHA256", "TG_CORS_ORIGINS", "R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "GROQ_API_KEY",
              "GEMINI_API_KEY", "EMBEDDING_PROVIDER"):
        e = envs.get(k)
        rep.add("PASS" if e is not None and e.get("sync") is False else "FAIL", f"{k} is asked for in the dashboard (sync: false), never stored", "")
    for k in ("TG_DB_DIR", "TG_LIFECYCLE_DIR", "TG_KB_APPROVED", "TG_LEGACY_DEV_ANSWERS", "TG_ENABLE_APPROVAL_REFRESH", "EMBEDDING_VERIFY"):
        rep.add("FAIL" if k in envs else "PASS", f"{k} is absent from the blueprint")
    return {"service": svc, "envs": envs, "python_version": pv}


def check_env_names(rep: Report, blueprint, manifest):
    documented = set(blueprint.get("envs", {})) | set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / "deploy" / "cloud.env.example").read_text("utf-8"), re.M))
    used = set()
    for f, info in (manifest or {}).get("files", {}).items():
        if f.endswith(".py") and info["category"] in ("runtime-code",):
            used |= env_names_in(f)
    prefixes = ("TG_", "EMBEDDING_", "R2_", "GROQ_", "GEMINI_", "OLLAMA_", "RAG_", "PROVIDER_", "LLM_", "KYR_")
    undocumented = sorted(n for n in used if n.startswith(prefixes) and n not in documented and n not in PLATFORM)
    rep.add("PASS", "environment variables read by the start-time code", f"{len(used)} names found")
    rep.add("WARN" if undocumented else "PASS", "optional variables the code reads that the blueprint and example do not mention (defaults apply)",
            ", ".join(undocumented) or "none")
    unused = sorted(n for n in documented if n not in used and n not in PLATFORM and not n.startswith("R2_"))
    rep.add("WARN" if unused else "PASS", "variables in the blueprint/example that no start-time code reads", ", ".join(unused) or "none")


def check_requirements(rep: Report, blueprint):
    lines = [l.strip() for l in (ROOT / "requirements-cloud.txt").read_text("utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
    pins = {}
    for l in lines:
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+]+)", l)
        if not m:
            rep.add("FAIL", "every requirement is pinned with ==", l)
            continue
        pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    rep.add("PASS", "requirements-cloud.txt pins", ", ".join(f"{k}=={v}" for k, v in pins.items()))
    heavy = sorted(set(pins) & HEAVY)
    rep.add("FAIL" if heavy else "PASS", "no PyTorch / notebook / unrelated heavy package is installed directly", ", ".join(heavy) or "none")
    return pins


def resolve(rep: Report, out: Path, python_version: str):
    """pip dry run: resolves requirements-cloud.txt to wheels for CPython 3.11, Linux x86_64 (and aarch64). Nothing is installed."""
    from packaging.specifiers import SpecifierSet
    results = {}
    for arch, plats in (("x86_64", ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64", "manylinux_2_34_x86_64", "linux_x86_64"]),
                        ("aarch64", ["manylinux2014_aarch64", "manylinux_2_17_aarch64", "manylinux_2_28_aarch64", "manylinux_2_34_aarch64"])):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--only-binary=:all:", "--quiet", "--disable-pip-version-check",
                   "--python-version", "3.11", "--implementation", "cp", "--abi", "cp311", "--target", str(Path(tmp) / "t"), "--report", str(report),
                   "-r", str(ROOT / "requirements-cloud.txt")]
            for p in plats:
                cmd += ["--platform", p]
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if run.returncode != 0 or not report.is_file():
                rep.add("FAIL", f"requirements resolve to wheels for CPython 3.11 / Linux {arch}", (run.stderr or run.stdout).strip().splitlines()[-1][:300])
                results[arch] = {"error": (run.stderr or run.stdout)[-1500:]}
                continue
            data = json.loads(report.read_text())
            pkgs = []
            for item in data["install"]:
                meta, url = item["metadata"], item["download_info"]["url"]
                pkgs.append({"name": meta["name"], "version": meta["version"], "wheel": url.rsplit("/", 1)[-1], "requires_python": meta.get("requires_python"),
                             "python_ok": (SpecifierSet(meta["requires_python"]).contains(python_version) if meta.get("requires_python") else True)})
            results[arch] = {"packages": len(pkgs), "resolved": sorted(pkgs, key=lambda p: p["name"].lower())}
            bad = [p["name"] for p in pkgs if not p["python_ok"]]
            rep.add("PASS" if not bad else "FAIL", f"every resolved wheel (Linux {arch}) accepts Python {python_version}", ", ".join(bad) or f"{len(pkgs)} wheels")
            rep.add("PASS", f"binary wheels exist for CPython 3.11 / Linux {arch}", f"{len(pkgs)} packages, none needs a source build")
    out.write_text(json.dumps({"python_version_checked": python_version, "results": results}, indent=1))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resolve", metavar="OUT.json", help="also resolve the requirements with pip --dry-run for Linux (network)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = Report()
    mpath = ROOT / "deploy" / "deployment-manifest.json"
    manifest = json.loads(mpath.read_text("utf-8")) if mpath.is_file() else None
    if manifest is None:
        rep.add("FAIL", "deployment manifest exists", "run scripts/deployment_manifest.py --write")
    bp = check_blueprint(rep, manifest)
    if bp:
        check_env_names(rep, bp, manifest)
    pins = check_requirements(rep, bp)
    rep.add("PASS" if sys.version_info[:2] == tuple(int(x) for x in (bp.get("python_version") or "0.0").split(".")[:2]) else "WARN",
            "this interpreter matches the blueprint's Python minor version", f"running {platform.python_version()}, blueprint {bp.get('python_version')}")
    if a.resolve and bp:
        resolve(rep, Path(a.resolve), bp["python_version"])
    if a.json:
        print(json.dumps({"ok": not rep.failed, "items": rep.items}, indent=1))
    else:
        for i in rep.items:
            print(f"{i['status']:4}  {i['check']}" + (f"  [{i['detail']}]" if i["detail"] else ""))
        print("RESULT:", "FAIL" if rep.failed else "no failures")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
