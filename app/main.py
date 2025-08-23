# app/main.py
import os
import requests
from fastapi import FastAPI, HTTPException, Query
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

# Cloud Run の GUI で設定する環境変数
PROJECT_ID = os.environ["PROJECT_ID"]
ZONE       = os.environ["ZONE"]
INSTANCE   = os.environ.get("INSTANCE", "")  # 既定のVM名（空ならクエリで必須にしてもOK）

app = FastAPI(title="VM Controller (start/stop)")

def get_access_token(scope: str = "https://www.googleapis.com/auth/cloud-platform") -> str:
    """Cloud Run のサービスアカウントで ADC を用いてトークン取得"""
    creds, _ = google_auth_default(scopes=[scope])
    if not creds.valid:
        creds.refresh(Request())
    return creds.token

def gce_post(url: str):
    token = get_access_token()
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 300:
        raise HTTPException(status_code=500, detail=r.text)
    return r.json()

@app.post("/vm/start")
def vm_start(
    project: str  = Query(default=PROJECT_ID),
    zone: str     = Query(default=ZONE),
    instance: str = Query(default=INSTANCE)
):
    if not instance:
        raise HTTPException(400, "query param 'instance' is required")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start"
    return gce_post(url)

@app.post("/vm/stop")
def vm_stop(
    project: str  = Query(default=PROJECT_ID),
    zone: str     = Query(default=ZONE),
    instance: str = Query(default=INSTANCE)
):
    if not instance:
        raise HTTPException(400, "query param 'instance' is required")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop"
    return gce_post(url)

# 任意: ヘルスチェック
@app.get("/healthz")
def healthz():
    return {"ok": True}
