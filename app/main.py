# app/main.py
import os, requests
from fastapi import FastAPI, HTTPException, Query
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

app = FastAPI()

# ヘルス確認用（起動確認に使う）
@app.get("/")
def root():
    return {"ok": True}

PROJECT_ID = os.environ.get("PROJECT_ID", "")
ZONE       = os.environ.get("ZONE", "")
INSTANCE   = os.environ.get("INSTANCE", "")

def get_access_token(scope="https://www.googleapis.com/auth/cloud-platform"):
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
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
):
    if not (project and zone and instance):
        raise HTTPException(400, "PROJECT_ID/ZONE/INSTANCE not set")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start"
    return gce_post(url)

@app.post("/vm/stop")
def vm_stop(
    project: str = Query(default=PROJECT_ID),
    zone: str    = Query(default=ZONE),
    instance: str= Query(default=INSTANCE),
):
    if not (project and zone and instance):
        raise HTTPException(400, "PROJECT_ID/ZONE/INSTANCE not set")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop"
    return gce_post(url)
