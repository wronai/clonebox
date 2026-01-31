import json
import subprocess
import sys
from typing import Any, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="CloneBox Dashboard")


def _run_clonebox(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "clonebox"] + args,
        capture_output=True,
        text=True,
    )


def _render_table(title: str, headers: List[str], rows: List[List[str]]) -> str:
    head_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )

    return (
        f"<h2>{title}</h2>"
        "<table>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return """
<!DOCTYPE html>
<html>
<head>
  <title>CloneBox Dashboard</title>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; margin: 20px; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f6f6f6; }
    code { background: #f6f6f6; padding: 2px 4px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>CloneBox Dashboard</h1>
  <p>Auto-refresh every 5s. JSON endpoints: <code>/api/vms.json</code>, <code>/api/containers.json</code></p>

  <div id="vms" hx-get="/api/vms" hx-trigger="load, every 5s">Loading VMs...</div>
  <div id="containers" hx-get="/api/containers" hx-trigger="load, every 5s">Loading containers...</div>
</body>
</html>
"""


@app.get("/api/vms", response_class=HTMLResponse)
async def api_vms() -> str:
    proc = _run_clonebox(["list", "--json"])
    if proc.returncode != 0:
        return f"<pre>clonebox list failed:\n{proc.stderr}</pre>"

    try:
        items: List[dict[str, Any]] = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return f"<pre>Invalid JSON from clonebox list:\n{proc.stdout}</pre>"

    if not items:
        return "<h2>VMs</h2><p><em>No VMs found.</em></p>"

    rows = [[str(i.get("name", "")), str(i.get("state", "")), str(i.get("uuid", ""))] for i in items]
    return _render_table("VMs", ["Name", "State", "UUID"], rows)


@app.get("/api/containers", response_class=HTMLResponse)
async def api_containers() -> str:
    proc = _run_clonebox(["container", "ps", "--json", "-a"])
    if proc.returncode != 0:
        return f"<pre>clonebox container ps failed:\n{proc.stderr}</pre>"

    try:
        items: List[dict[str, Any]] = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return f"<pre>Invalid JSON from clonebox container ps:\n{proc.stdout}</pre>"

    if not items:
        return "<h2>Containers</h2><p><em>No containers found.</em></p>"

    rows = [
        [
            str(i.get("name", "")),
            str(i.get("image", "")),
            str(i.get("status", "")),
            str(i.get("ports", "")),
        ]
        for i in items
    ]
    return _render_table("Containers", ["Name", "Image", "Status", "Ports"], rows)


@app.get("/api/vms.json")
async def api_vms_json() -> JSONResponse:
    proc = _run_clonebox(["list", "--json"])
    if proc.returncode != 0:
        return JSONResponse({"error": proc.stderr, "stdout": proc.stdout}, status_code=500)

    try:
        return JSONResponse(json.loads(proc.stdout or "[]"))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json", "stdout": proc.stdout}, status_code=500)


@app.get("/api/containers.json")
async def api_containers_json() -> JSONResponse:
    proc = _run_clonebox(["container", "ps", "--json", "-a"])
    if proc.returncode != 0:
        return JSONResponse({"error": proc.stderr, "stdout": proc.stdout}, status_code=500)

    try:
        return JSONResponse(json.loads(proc.stdout or "[]"))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json", "stdout": proc.stdout}, status_code=500)


def run_dashboard(port: int = 8080) -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port)
