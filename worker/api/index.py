# worker/api/index.py
import os
from fastapi import FastAPI, Header, HTTPException, Depends

WORKER_TOKEN = os.getenv("WORKER_TOKEN")

def verify_token(x_worker_token: str | None = Header(None, alias="X-Worker-Token")):
    if not WORKER_TOKEN:
        raise HTTPException(status_code=500, detail="WORKER_TOKEN not set")
    if x_worker_token != WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-Worker-Token")

app = FastAPI(dependencies=[Depends(verify_token)])  # global requirement

@app.get("/healthz")
def healthz():
    # If you want healthz public, remove the global dependency above
    return {"status": "alive"}

@app.get("/")
def root():
    return {"ok": True}
