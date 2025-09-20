"""
Simple Deta-style worker for PO review pipeline.

This FastAPI app exposes endpoints to receive PO review jobs,
store input files, return artifacts, and update status. It
stores files under the `/data` directory relative to the
container root. In a Deta Space deployment, persistent
storage is provided automatically.

Endpoints:
    POST /po-check
        Accepts multipart form data with files `po`, `pi`,
        `commission` and optional toggles: `template_override`,
        `noban_option`, `pg_waived`, `apg_required`. Saves the
        files and returns a new job ID.

    GET /status/{jobId}
        Returns the JSON status for the given job. If the
        status file does not exist, returns {"status":"unknown"}.

    PUT /status/{jobId}
        Accepts a JSON body and updates the status for the
        given job.

    GET /artifact/{jobId}/{filename}
        Returns the stored file for the given job and file
        name. Files are stored under `out/{jobId}/{filename}`.

    PUT /artifact/{jobId}/{filename}
        Writes the body to the output file for the given job
        and filename. Creates directories as needed.
"""

import os
import uuid
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Header, HTTPException
from fastapi.responses import Response

app = FastAPI()

DATA_ROOT = Path("/data")  # base directory for input, output and status

def save_binary(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

def read_binary(path: Path) -> bytes | None:
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return f.read()

@app.post("/po-check")
async def po_check(
    po: UploadFile = File(...),
    pi: UploadFile = File(...),
    commission: UploadFile = File(...),
    template_override: str = "irr_main",
    noban_option: str = "a",
    pg_waived: str = "false",
    apg_required: str = "true",
    authorization: str | None = Header(default=None)
):
    """Receive a PO review job and save its input files and toggles.

    Returns a unique jobId and sets initial status to "received".
    """
    job_id = str(uuid.uuid4())
    # Save files
    save_binary(DATA_ROOT / "in" / job_id / "po", await po.read())
    save_binary(DATA_ROOT / "in" / job_id / "pi", await pi.read())
    save_binary(DATA_ROOT / "in" / job_id / "commission", await commission.read())
    toggles = {
        "template_override": template_override,
        "noban_option": noban_option,
        "pg_waived": pg_waived,
        "apg_required": apg_required,
    }
    save_binary(
        DATA_ROOT / "in" / job_id / "toggles.json",
        json.dumps(toggles, ensure_ascii=False).encode("utf-8"),
    )
    # Initialise status
    save_binary(
        DATA_ROOT / "status" / f"{job_id}.json",
        json.dumps({"status": "received"}, ensure_ascii=False).encode("utf-8"),
    )
    return {"jobId": job_id, "status": "received", "status_url": f"/status/{job_id}"}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Return the status JSON for the given job."""
    data = read_binary(DATA_ROOT / "status" / f"{job_id}.json")
    if data is None:
        return {"status": "unknown"}
    return json.loads(data)

@app.put("/status/{job_id}")
async def put_status(job_id: str, body: bytes = None, authorization: str | None = Header(default=None)):
    """Replace the status JSON for the given job."""
    if body is None:
        raise HTTPException(status_code=400, detail="No body provided")
    save_binary(DATA_ROOT / "status" / f"{job_id}.json", body)
    return {"status": "ok"}

@app.get("/artifact/{job_id}/{filename}")
async def get_artifact(job_id: str, filename: str):
    """Retrieve an output or input file by job ID and filename."""
    # Try output first
    path = DATA_ROOT / "out" / job_id / filename
    data = read_binary(path)
    if data is None:
        path = DATA_ROOT / "in" / job_id / filename
        data = read_binary(path)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=data)

@app.put("/artifact/{job_id}/{filename}")
async def put_artifact(job_id: str, filename: str, body: bytes = None, authorization: str | None = Header(default=None)):
    """Store an output file for the given job."""
    if body is None:
        raise HTTPException(status_code=400, detail="No body provided")
    save_binary(DATA_ROOT / "out" / job_id / filename, body)
    return {"status": "ok"}
