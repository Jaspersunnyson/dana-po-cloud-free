"""
FastAPI worker for PO review pipeline (Vercel-ready).

- Writes to /tmp (Vercel's writable dir).
- Enforces X-Worker-Token on all routes.
- On POST /po-check, saves inputs and triggers GitHub repository_dispatch
  with event_type=po_review_request and client_payload={"jobId": <uuid>}.

Env vars required (set in Vercel Project Settings → Environment Variables):
  WORKER_TOKEN          # the shared secret for clients
  DATA_ROOT             # optional; defaults to /tmp/data
  GH_OWNER              # e.g., 'Jaspersunnyson'
  GH_REPO               # e.g., 'dana-po-cloud-free'
  GH_DISPATCH_TOKEN     # fine-grained PAT with Contents:RW and Actions:RW (repo)
"""

import os
import uuid
import json
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Depends
from fastapi.responses import Response

app = FastAPI()

# Writable on Vercel:
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/data"))

# Security
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")

def verify_token(x_worker_token: Optional[str] = Header(None)):
    if not WORKER_TOKEN:
        # If you forgot to set it, block everything.
        raise HTTPException(status_code=500, detail="WORKER_TOKEN not configured")
    if x_worker_token != WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

def _save_binary(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

def _read_binary(path: Path) -> Optional[bytes]:
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return f.read()

def _dispatch_to_github(job_id: str) -> dict:
    """POST repository_dispatch to trigger the pipeline."""
    owner = os.getenv("GH_OWNER")
    repo  = os.getenv("GH_REPO")
    token = os.getenv("GH_DISPATCH_TOKEN")
    if not all([owner, repo, token]):
        return {"dispatched": False, "reason": "GH_* env missing"}

    url = f"https://api.github.com/repos/{owner}/{repo}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "event_type": "po_review_request",
        "client_payload": {"jobId": job_id}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    ok = (200 <= r.status_code < 300)
    return {"dispatched": ok, "status": r.status_code, "text": r.text[:200]}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/po-check")
async def po_check(
    po: UploadFile = File(...),
    pi: UploadFile = File(...),
    commission: UploadFile = File(...),
    template_override: str = "irr_main",
    noban_option: str = "a",
    pg_waived: str = "false",
    apg_required: str = "true",
    _=Depends(verify_token),
):
    job_id = str(uuid.uuid4())

    # Save inputs
    _save_binary(DATA_ROOT / "in" / job_id / "po",        await po.read())
    _save_binary(DATA_ROOT / "in" / job_id / "pi",        await pi.read())
    _save_binary(DATA_ROOT / "in" / job_id / "commission",await commission.read())

    toggles = {
        "template_override": template_override,
        "noban_option": noban_option,
        "pg_waived": pg_waived,
        "apg_required": apg_required,
    }
    _save_binary(DATA_ROOT / "in" / job_id / "toggles.json",
                 json.dumps(toggles, ensure_ascii=False).encode("utf-8"))

    # Init status
    _save_binary(DATA_ROOT / "status" / f"{job_id}.json",
                 json.dumps({"status": "received"}, ensu
