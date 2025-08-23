# app/main.py
import os
import time
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

# ---------------------------
# FastAPI app & middlewares
# ---------------------------
app = FastAPI(title="GCE VM Controller", version="1.0.0")

# CORS: 必要なら Cloud Run の環境変数 ALLOW_ORIGINS に
# "https://your-bubble-app.bubbleapps.io,https://example.com" のようにカンマ区切りで指定
_allow_origins = os.environ.get("ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _allow_origins.split(",")] if _allow_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Config from env (optional defaults)
# ---------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "")
ZONE       = os.environ.get("ZONE", "")
INSTANCE   = os.environ.get("INSTANCE", "")
API_KEY    = os.environ.get("API_KEY")  # 設定されている場合のみ検証する

# ---------------------------
# Helpers
# ---------------------------
def check_key(x_api_key: Optional[str]) -> None:
    """APIキー検証（API_KEY が未設定のときはスキップ）"""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

def ensure_params(project: str, zone: str, instance: str) -> None:
    if not (project and zone and instance):
        raise HTTPException(status_code=400, detail="PROJECT_ID/ZONE/INSTANCE not set")

def get_access_token(scope: str = "https://www.googleapis.com/auth/cloud-platform") -> str:
    creds, _ = google_auth_default(scopes=[scope])
    if not creds.valid:
        creds.refresh(Request())
    return creds.token

def gce_req(method: str, url: str):
    """Google Compute Engine REST を呼ぶ汎用関数（認証含む）"""
    token = get_access_token()
    r = requests.request(method, url, headers={"Authorization": f"Bearer {token}"})
    # GCE のエラー本文をそのまま返すとデバッグしやすい
    if r.status_code >= 300:
        # 404 などはそのまま透過させる
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

def instance_url(project: str, zone: str, instance: str) -> str:
    return f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}"

# ---------------------------
# Health
# ---------------------------
@app.get("/")
def root():
    return {"ok": True, "service": "vm-ctrl"}

# ---------------------------
# Start / Stop / Status
# ---------------------------
@app.post("/vm/start")
def vm_start(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    url = instance_url(project, zone, instance) + "/start"
    return gce_req("POST", url)  # 非同期 Operation を返す

@app.post("/vm/stop")
def vm_stop(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    url = instance_url(project, zone, instance) + "/stop"
    return gce_req("POST", url)  # 非同期 Operation を返す

@app.get("/vm/status")
def vm_status(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    j = gce_req("GET", instance_url(project, zone, instance))
    # 代表例: PROVISIONING -> STAGING -> RUNNING / STOPPING -> TERMINATED
    return {"name": instance, "zone": zone, "status": j.get("status", "UNKNOWN")}

# ---------------------------
# Wait until target status (optional but handy for Bubble)
# ---------------------------
@app.post("/vm/wait")
def vm_wait(
    target: str  = Query(default="RUNNING", pattern="^(RUNNING|TERMINATED)$"),
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    max_checks: int   = Query(default=60, ge=1, le=600),  # 5秒*60=最大5分
    interval_sec: int = Query(default=5, ge=1, le=60),
    x_api_key: Optional[str] = Header(default=None),
):
    """
    例:
      起動待ち: POST /vm/start → POST /vm/wait?target=RUNNING
      停止待ち: POST /vm/stop  → POST /vm/wait?target=TERMINATED
    """
    check_key(x_api_key)
    ensure_params(project, zone, instance)

    url = instance_url(project, zone, instance)
    last_status = "UNKNOWN"
    for _ in range(max_checks):
        j = gce_req("GET", url)
        last_status = j.get("status", "UNKNOWN")
        if last_status == target:
            return {"name": instance, "zone": zone, "status": last_status}
        time.sleep(interval_sec)

    raise HTTPException(status_code=408, detail=f"timeout: last status={last_status}")
