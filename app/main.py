# app/main.py
import os
import time
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

app = FastAPI(title="GCE VM Controller", version="1.1.0")

# --- CORS ---
_allow_origins = os.environ.get("ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _allow_origins.split(",")] if _allow_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
PROJECT_ID = os.environ.get("PROJECT_ID", "")
ZONE       = os.environ.get("ZONE", "")
INSTANCE   = os.environ.get("INSTANCE", "")
API_KEY    = os.environ.get("API_KEY")
COMFY_BASEURL = os.environ.get("COMFY_BASEURL")  # 例: http://10.0.0.5:8188  （任意）

# --- Requests セッション（★ タイムアウト & 軽いリトライ） ---
_session = requests.Session()
# 429/5xx 系のみ軽くリトライ（最大3回）
from requests.adapters import HTTPAdapter, Retry  # type: ignore
_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset(["GET", "POST"])
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))
_DEFAULT_TIMEOUT = (3, 30)  # (connect, read) seconds

# --- Helpers ---
def check_key(x_api_key: Optional[str]) -> None:
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

def _raise_http(status: int, text: str):
    # ★ JSONなら中身を返す／そうでなければ短い文字列へ
    detail = text
    try:
        import json
        detail = json.loads(text)  # type: ignore
    except Exception:
        # 長すぎるHTMLなどは圧縮
        detail = {"error": text[:1000]}
    raise HTTPException(status_code=status, detail=detail)

def gce_req(method: str, url: str):
    token = get_access_token()
    r = _session.request(method, url, headers={"Authorization": f"Bearer {token}"},
                         timeout=_DEFAULT_TIMEOUT)
    if r.status_code >= 300:
        _raise_http(r.status_code, r.text)
    # 一部のGETは空ボディのこともある
    return r.json() if r.text else {}

def instance_url(project: str, zone: str, instance: str) -> str:
    return f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}"

# --- Health ---
@app.get("/")
def root():
    return {"ok": True, "service": "vm-ctrl"}

# --- Start / Stop / Status ---
@app.api_route("/vm/start", methods=["POST", "GET"])  # ★ GETも許容（任意）
def vm_start(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    url = instance_url(project, zone, instance) + "/start"
    return gce_req("POST", url)

@app.api_route("/vm/stop", methods=["POST", "GET"])   # ★ GETも許容（任意）
def vm_stop(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    url = instance_url(project, zone, instance) + "/stop"
    return gce_req("POST", url)

@app.api_route("/vm/status", methods=["GET", "POST"])  # ★ POSTも許容（任意）
def vm_status(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
    x_api_key: Optional[str] = Header(default=None),
):
    check_key(x_api_key)
    ensure_params(project, zone, instance)
    j = gce_req("GET", instance_url(project, zone, instance))
    return {"name": instance, "zone": zone, "status": j.get("status", "UNKNOWN")}



# --- ComfyUI ping（疎通確認用・任意） ---
@app.get("/comfy/ping")
def comfy_ping(x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)
    if not COMFY_BASEURL:
        raise HTTPException(500, "COMFY_BASEURL not set")
    try:
        r = _session.get(f"{COMFY_BASEURL}/system_stats", timeout=_DEFAULT_TIMEOUT)
        return {"ok": r.ok, "status": r.status_code}
    except Exception as e:
        raise HTTPException(502, f"connect failed: {e}")
