import requests
from fastapi import FastAPI, HTTPException, Query
import os
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request

app = FastAPI()

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

def gce_req(method, url):
    token = get_access_token()
    r = requests.request(method, url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 300:
        raise HTTPException(status_code=500, detail=r.text)
    return r.json()

@app.post("/vm/start")
def vm_start(project: str = Query(default=PROJECT_ID),
             zone: str    = Query(default=ZONE),
             instance: str= Query(default=INSTANCE)):
    if not (project and zone and instance):
        raise HTTPException(400, "PROJECT_ID/ZONE/INSTANCE not set")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start"
    return gce_req("POST", url)

@app.post("/vm/stop")
def vm_stop(project: str = Query(default=PROJECT_ID),
            zone: str    = Query(default=ZONE),
            instance: str= Query(default=INSTANCE)):
    if not (project and zone and instance):
        raise HTTPException(400, "PROJECT_ID/ZONE/INSTANCE not set")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop"
    return gce_req("POST", url)

@app.get("/vm/status")
def vm_status(project: str = Query(default=PROJECT_ID),
              zone: str    = Query(default=ZONE),
              instance: str= Query(default=INSTANCE)):
    if not (project and zone and instance):
        raise HTTPException(400, "PROJECT_ID/ZONE/INSTANCE not set")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{instance}"
    j = gce_req("GET", url)
    return {"name": instance, "zone": zone, "status": j.get("status", "UNKNOWN")}
