import os
from fastapi import FastAPI, Depends, Header, HTTPException

app = FastAPI()
WORKER_TOKEN = os.getenv("WORKER_TOKEN")

def require_worker_token(
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token")
):
    if not WORKER_TOKEN:
        raise HTTPException(status_code=500, detail="WORKER_TOKEN not set")
    if x_worker_token != WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-Worker-Token")

@app.get("/healthz")
def healthz():
    return {"status": "alive"}

@app.get("/", dependencies=[Depends(require_worker_token)])
def root():
    return {"ok": True}
