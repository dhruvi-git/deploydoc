import os

from fastapi import FastAPI

# Deliberate: the app refuses to start without its config. This is what the
# "missing_env" failure scenario breaks, on all three clouds at once.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable DATABASE_URL")

VERSION = os.environ.get("APP_VERSION", "dev")
app = FastAPI(title="deploydoc-target")


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/")
def root():
    return {"service": "deploydoc-target", "version": VERSION}
