# app/main.py
import os
import time
import mimetypes
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

# ==========================================================
# App meta
# ==========================================================
app = FastAPI(title="GCE VM Controller", version="1.2.0")

# ==========================================================
# CORS
# ==========================================================
_allow_origins = os.environ.get("ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _allow_origins.split(",")] if _allow_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ==========================================================
# Config
# ==========================================================
PROJECT_ID = os.environ.get("PROJECT_ID", "")
ZONE       = os.environ.get("ZONE", "")
INSTANCE   = os.environ.get("INSTANCE", "")
API_KEY    = os.environ.get("API_KEY")
# 例: "http://10.128.0.3:8188"（VM の内部IP:8188）
COMFY_BASEURL = os.environ.get("COMFY_BASEURL")

# ==========================================================
# Requests session（軽リトライ＋タイムアウト）
# ==========================================================
_session = requests.Session()
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

# ==========================================================
# Helpers
# ==========================================================
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
    # JSONならそのまま、非JSONは先頭1000文字に圧縮
    detail: Any = text
    try:
        import json
        detail = json.loads(text)  # type: ignore
    except Exception:
        detail = {"error": text[:1000]}
    raise HTTPException(status_code=status, detail=detail)

def gce_req(method: str, url: str) -> Dict[str, Any]:
    token = get_access_token()
    r = _session.request(method, url, headers={"Authorization": f"Bearer {token}"},
                         timeout=_DEFAULT_TIMEOUT)
    if r.status_code >= 300:
        _raise_http(r.status_code, r.text)
    return r.json() if r.text else {}

def instance_url(project: str, zone: str, instance: str) -> str:
    return f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}"

def comfy_get(path: str, params: Optional[Dict[str, Any]] = None, stream: bool = False):
    if not COMFY_BASEURL:
        raise HTTPException(500, "COMFY_BASEURL not set")
    url = f"{COMFY_BASEURL.rstrip('/')}/{path.lstrip('/')}"
    r = _session.get(url, params=params, timeout=_DEFAULT_TIMEOUT, stream=stream)
    if r.status_code >= 300:
        _raise_http(r.status_code, r.text)
    return r

def comfy_post(path: str, json: Dict[str, Any]):
    if not COMFY_BASEURL:
        raise HTTPException(500, "COMFY_BASEURL not set")
    url = f"{COMFY_BASEURL.rstrip('/')}/{path.lstrip('/')}"
    r = _session.post(url, json=json, timeout=_DEFAULT_TIMEOUT)
    if r.status_code >= 300:
        _raise_http(r.status_code, r.text)
    return r

# ==========================================================
# Health
# ==========================================================
@app.get("/")
def root():
    return {"ok": True, "service": "vm-ctrl"}

# ==========================================================
# Start / Stop / Status
# ==========================================================
@app.api_route("/vm/start", methods=["POST", "GET"])  # GETも許容
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

@app.api_route("/vm/stop", methods=["POST", "GET"])   # GETも許容
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

@app.api_route("/vm/status", methods=["GET", "POST"])  # POSTも許容
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

# ==========================================================
# ComfyUI: ping / run / result / fetch
# ==========================================================
@app.get("/comfy/ping")
def comfy_ping(x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)
    try:
        r = comfy_get("/system_stats")
        return {"ok": r.ok, "status": r.status_code}
    except Exception as e:
        raise HTTPException(502, f"connect failed: {e}")

@app.post("/comfy/run")
def comfy_run(
    payload: Dict[str, Any],
    x_api_key: Optional[str] = Header(default=None),
):
    """
    ComfyUI の /prompt にワークフロー JSON をそのままPOST。
    返り値例: {"prompt_id":"...", "node_errors":{...}}
    """
    check_key(x_api_key)
    try:
        r = comfy_post("/prompt", json=payload)
        j = r.json()
        if "prompt_id" not in j:
            raise HTTPException(502, f"Unexpected response from ComfyUI: {j}")
        return j
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"ComfyUI error: {e}")

@app.get("/comfy/result")
def comfy_result(
    prompt_id: str = Query(..., description="comfy_run が返す prompt_id"),
    timeout_sec: int = Query(60, ge=1, le=600),
    poll_interval: float = Query(1.5, gt=0, le=10.0),
    x_api_key: Optional[str] = Header(default=None),
):
    """
    /history/<prompt_id> をポーリングし、生成画像のファイル名一覧を返す。
    返り値: {"done": true/false, "files": [...], "error": "...(任意)"}
    """
    check_key(x_api_key)
    deadline = time.time() + timeout_sec
    last_error: Optional[str] = None

    while time.time() < deadline:
        try:
            r = comfy_get(f"/history/{prompt_id}")
            # 404 でなければ JSON
            hist = r.json()
            if prompt_id not in hist:
                time.sleep(poll_interval)
                continue

            outputs = hist[prompt_id].get("outputs", {})
            files: List[str] = []
            for node_id, out in outputs.items():
                for img in out.get("images", []):
                    fn = img.get("filename")
                    if fn:
                        files.append(fn)

            if files:
                return {"done": True, "files": files}

            # 画像まだ→継続
            time.sleep(poll_interval)
        except HTTPException as he:
            # /history が未作成などで 404 の可能性（_raise_http が投げる）
            last_error = str(he.detail)
            time.sleep(poll_interval)
        except Exception as e:
            last_error = str(e)
            time.sleep(poll_interval)

    # タイムアウト
    return JSONResponse(status_code=200, content={"done": False, "files": [], "error": last_error})

@app.get("/comfy/fetch")
def comfy_fetch(
    filename: str = Query(..., description="ComfyUI の /view で参照するファイル名"),
    x_api_key: Optional[str] = Header(default=None),
):
    """
    ComfyUI の /view?filename=... をプロキシして画像を返す。
    Bubble 側は <img src="<RUN_URL>/comfy/fetch?filename=..."> で表示可能。
    """
    check_key(x_api_key)
    try:
        r = comfy_get("/view", params={"filename": filename}, stream=True)
        mime = "image/png"
        guess, _ = mimetypes.guess_type(filename)
        if guess:
            mime = guess
        return StreamingResponse(r.iter_content(chunk_size=8192), media_type=mime)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"ComfyUI fetch error: {e}")
