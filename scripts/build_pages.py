#!/usr/bin/env python3
"""Static build of the frontend for GitHub Pages (no Node, no dependencies).

The frontend is one HTML file plus one script (frontend/index.html, frontend/render.js): there is no framework, bundler or client-side
router, so "build" means copying the two files and applying three safe transformations:
  1. the API origin goes into <meta name="kyr-api-base"> (the page prefixes every fetch with it; empty = same origin);
  2. root-absolute asset paths become relative (src="/static/render.js" -> src="static/render.js"), so the page works from the
     project subpath https://<owner>.github.io/<repo>/ as well as from a domain root;
  3. a Content-Security-Policy meta limits where the page may send requests (connect-src: itself and the API origin only),
     forbids <base> changes and form posts.
Then it scans the output and FAILS the build if anything looks like a credential. The API origin is public; no key is ever needed or
accepted by the frontend.

    python3 scripts/build_pages.py --api-base https://kyr-api.onrender.com --out build/pages
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
META = '<meta name="kyr-api-base" content="">'
META_TIMEOUT = '<meta name="kyr-timeout-seconds" content="">'
# Strings that must never be in anything published. Provider names are fine in prose; key shapes and variable names are not.
FORBIDDEN_PATTERNS = [
    (r"gsk_[A-Za-z0-9]{20,}", "Groq key"), (r"AIza[0-9A-Za-z_\-]{30,}", "Google API key"), (r"\bsk-[A-Za-z0-9]{20,}", "secret key"),
    (r"fw_[A-Za-z0-9]{20,}", "Fireworks key"), (r"hf_[A-Za-z0-9]{30,}", "Hugging Face token"), (r"\bnk-[A-Za-z0-9_\-]{20,}", "Nomic key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"), (r"\bAKIA[0-9A-Z]{16}\b", "AWS-style access key id"),
    (r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}", "bearer token"),
    (r"(GROQ_API_KEY|GEMINI_API_KEY|EMBEDDING_API_KEY|R2_SECRET_ACCESS_KEY|R2_ACCESS_KEY_ID|HF_TOKEN|TG_TRUSTED_KEYS_FILE)", "secret variable name"),
]
SECRET_ENV = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)


class BuildError(Exception):
    pass


def check_api_base(value: str, allow_local: bool = False) -> str:
    """The API's origin: https://host[:port], nothing else. Empty is allowed (same-origin build)."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    p = urlparse(value)
    local = (p.hostname or "") in ("localhost", "127.0.0.1")
    if p.scheme != "https" and not (allow_local and p.scheme == "http" and local):
        raise BuildError("the API base URL must be https (GitHub Pages is https; browsers block calls to plain http)")
    if not p.hostname or p.path or p.query or p.fragment or p.username or p.password or '"' in value or "<" in value:
        raise BuildError("the API base URL must be an origin only: https://host[:port]")
    if local and not allow_local:
        raise BuildError("the API base URL must be a public host, not localhost")
    return value


def check_timeout(value) -> str:
    """Optional request timeout (seconds) the page waits for the backend before offering a retry; "" = the page's own default."""
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        seconds = float(value)
    except ValueError:
        raise BuildError("the request timeout must be a number of seconds between 5 and 300") from None
    if not 5 <= seconds <= 300:
        raise BuildError("the request timeout must be a number of seconds between 5 and 300")
    return f"{seconds:g}"


def transform(html: str, api_base: str, timeout_seconds: str = "") -> str:
    if html.count(META_TIMEOUT) != 1:
        raise BuildError("frontend/index.html must contain the kyr-timeout-seconds meta tag exactly once")
    if html.count(META) != 1:
        raise BuildError("frontend/index.html must contain the kyr-api-base meta tag exactly once")
    if html.count('src="/static/render.js"') != 1:
        raise BuildError("frontend/index.html must load /static/render.js exactly once")
    csp_connect = "'self'" + (f" {api_base}" if api_base else "")
    csp = (f'<meta http-equiv="Content-Security-Policy" content="base-uri \'self\'; form-action \'none\'; '
           f'connect-src {csp_connect}; object-src \'none\'">')
    html = html.replace(META_TIMEOUT, f'<meta name="kyr-timeout-seconds" content="{check_timeout(timeout_seconds)}">')
    html = html.replace(META, f'<meta name="kyr-api-base" content="{api_base}">\n{csp}')
    return html.replace('src="/static/render.js"', 'src="static/render.js"')


def scan(out_dir: Path, env=None) -> list:
    """Findings (file, what) in the built files: key shapes, secret variable names, and the VALUES of secret-looking variables
    present in the build environment."""
    env = os.environ if env is None else env
    values = [v for k, v in env.items() if SECRET_ENV.search(k) and len(v) >= 8 and not v.isdigit()]
    findings = []
    for f in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        text = f.read_text("utf-8", errors="ignore")
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                findings.append((str(f.relative_to(out_dir)), label))
        if any(v in text for v in values):
            findings.append((str(f.relative_to(out_dir)), "value of a secret environment variable"))
    return findings


def build(out_dir, api_base="", allow_local=False, env=None, require_api_base=False, timeout_seconds="") -> dict:
    api_base = check_api_base(api_base, allow_local)
    if require_api_base and not api_base:
        raise BuildError("no API base URL: a published GitHub Pages site must be told where the backend is (KYR_API_BASE_URL)")
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    (out / "index.html").write_text(transform((FRONTEND / "index.html").read_text("utf-8"), api_base, timeout_seconds), "utf-8")
    shutil.copyfile(FRONTEND / "render.js", out / "static" / "render.js")
    (out / ".nojekyll").write_text("", "utf-8")   # serve files as they are; no Jekyll processing
    findings = scan(out, env)
    if findings:
        shutil.rmtree(out)
        raise BuildError("refusing to publish, possible credentials in the build: " + "; ".join(f"{a}: {b}" for a, b in findings))
    return {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api-base", default=os.environ.get("KYR_API_BASE_URL", ""), help="https origin of the FastAPI backend (Render)")
    ap.add_argument("--request-timeout-seconds", default=os.environ.get("KYR_REQUEST_TIMEOUT_SECONDS", ""),
                    help="optional: how long the page waits for the backend before offering a retry (5-300; default is built into the page)")
    ap.add_argument("--out", default=str(ROOT / "build" / "pages"))
    ap.add_argument("--allow-local", action="store_true", help="testing only: allow http://localhost")
    ap.add_argument("--require-api-base", action="store_true", help="fail when no API base is given (the publishing workflow uses this)")
    a = ap.parse_args(argv)
    try:
        files = build(a.out, a.api_base, a.allow_local, require_api_base=a.require_api_base, timeout_seconds=a.request_timeout_seconds)
    except BuildError as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    for name, digest in files.items():
        print(f"{digest[:16]}  {name}")
    print(f"built {len(files)} files into {a.out} (API base: {a.api_base or '(same origin)'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
