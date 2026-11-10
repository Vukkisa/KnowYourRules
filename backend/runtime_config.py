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
