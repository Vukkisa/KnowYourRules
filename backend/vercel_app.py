"""Vercel entry point (pyproject.toml: [tool.vercel] entrypoint = "backend.vercel_app:app").

The same FastAPI application as every other host: backend.server is imported unchanged, after backend.vercel_runtime has validated the
environment and held the verified, pinned model in memory (nothing is written to /tmp for it). If either step fails this import raises and the function does not start."""
from backend import vercel_runtime

vercel_runtime.prepare()

from backend.server import app  # noqa: E402,F401  (the import must come after prepare(); `app` is what Vercel serves)
