"""
Deployment configuration boundary.

Precedence (highest first):
  1. The process environment supplied by the deployment (shell, container, service manager).
  2. The project .env file - ONLY when the process environment already says TG_ENVIRONMENT=development,
     and never for a variable the process environment already defines.
  3. Built-in defaults, which are always the safe ones (answer mode "disabled").

A .env file therefore cannot switch a deployment into development mode: TG_ENVIRONMENT must come from the
process environment, and without it the file is not read at all. Missing configuration resolves to disabled.

Operators CAN still deliberately enable legacy development answers (TG_ENVIRONMENT=development plus
TG_LEGACY_DEV_ANSWERS=1 plus a GROQ_API_KEY). That mode serves unvalidated model text and is not suitable for
public legal-answer traffic under any circumstances.
"""

import os
import re
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEVELOPMENT = "development"
KNOWN_ENVIRONMENTS = frozenset({"development", "staging", "production"})


def deployment_environment(environ=None) -> str:
    """TG_ENVIRONMENT from the given environment, lower-cased; "" when unset."""
    environ = os.environ if environ is None else environ
    return (environ.get("TG_ENVIRONMENT") or "").strip().lower()


def load_local_env(path=None, environ=None) -> list[str]:
    """Copy .env values into environ for keys it does not already define, only in development.
    Returns the keys that were added (values are never logged or returned)."""
    environ = os.environ if environ is None else environ
    if deployment_environment(environ) != DEVELOPMENT:
        return []
    path = Path(path or ENV_FILE)
    if not path.is_file():
        return []
    added = []
    for key, value in dotenv_values(path).items():
        if value is None or key in environ or key == "TG_ENVIRONMENT":
            continue  # the deployment wins; the file can never set the environment itself
        environ[key] = value
        added.append(key)
    return added


PRODUCTION_LIKE = frozenset({"production", "staging"})
_HOST_OK = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$|^[0-9a-fA-F:]+$")


def is_production_like(environ=None) -> bool:
    """A deployed environment (TG_ENVIRONMENT production or staging): CORS, the snapshot pin and the embedding checks are strict there."""
    return deployment_environment(environ) in PRODUCTION_LIKE


def cors_origins(environ=None) -> tuple[list[str], list[str]]:
    """TG_CORS_ORIGINS: comma-separated browser origins allowed to call the API from another site (e.g. the GitHub Pages site,
    https://<user>.github.io). Exact origins only: scheme://host[:port], no path, no wildcard, https (http only for localhost, and
    localhost only outside production/staging). Returns (accepted, rejected); rejected entries are dropped, so a typo can only close
    CORS, never open it. Empty = no CORS. Whether "empty" is acceptable is cors_problems()' business."""
    from urllib.parse import urlparse
    environ = os.environ if environ is None else environ
    strict = is_production_like(environ)
    accepted, rejected = [], []
    for raw in (environ.get("TG_CORS_ORIGINS") or "").split(","):
        item = raw.strip().rstrip("/")
        if not item:
            continue
        p = urlparse(item)
        host = (p.hostname or "")
        local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
        try:
            port = p.port
        except ValueError:
            port = None
        ok = (item != "*" and "*" not in item and host and _HOST_OK.match(host) and not p.path and not p.query and not p.fragment
              and not p.username and (p.scheme == "https" or (p.scheme == "http" and local)) and port != 0
              and not (strict and local))                       # production never trusts a page served from the operator's own machine
        target = accepted if ok else rejected
        if item not in target:
            target.append(item)
    return accepted, rejected


def cors_problems(environ=None) -> list[str]:
    """Configuration errors for CORS. In production/staging an explicit, non-empty, valid TG_CORS_ORIGINS is mandatory (the browser
    frontend is a different origin); in development nothing is required. Messages name the variable, never a value."""
    environ = os.environ if environ is None else environ
    problems = []
    accepted, rejected = cors_origins(environ)
    if rejected:
        problems.append(f"{len(rejected)} TG_CORS_ORIGINS entr{'y is' if len(rejected) == 1 else 'ies are'} not an exact https origin "
                        "(scheme://host, no path, no wildcard, no localhost in production)")
    if is_production_like(environ) and not accepted:
        problems.append("TG_CORS_ORIGINS is required in production: set it to the exact origin of the frontend (https://<owner>.github.io)")
    return problems
