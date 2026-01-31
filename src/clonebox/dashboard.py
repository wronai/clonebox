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
    head_html = "".join(
        f'<th class="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>'
        for h in headers
    )
    body_html = "".join(
        '<tr class="hover:bg-gray-700 transition-colors">'
        + "".join(f'<td class="px-4 py-3 whitespace-nowrap">{c}</td>' for c in row)
        + "</tr>"
        for row in rows
    )

    return (
        f'<h2 class="text-xl font-semibold text-cyan-400 mb-4 flex items-center gap-2">'
        f'{"🖥️" if "VM" in title else "🐳"} {title}</h2>'
        '<div class="overflow-x-auto">'
        '<table class="min-w-full divide-y divide-gray-700">'
        f'<thead class="bg-gray-900"><tr>{head_html}</tr></thead>'
        f'<tbody class="divide-y divide-gray-700">{body_html}</tbody>'
        "</table></div>"
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CloneBox Dashboard</title>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .htmx-request { opacity: 0.5; transition: opacity 200ms ease-in; }
  </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">
    <header class="mb-8">
      <h1 class="text-3xl font-bold text-cyan-400 flex items-center gap-3">
        <span class="text-4xl">📦</span> CloneBox Dashboard
      </h1>
      <p class="text-gray-400 mt-2">
        Auto-refresh every 3s &bull;
        <code class="bg-gray-800 px-2 py-1 rounded text-sm">/api/vms.json</code>
        <code class="bg-gray-800 px-2 py-1 rounded text-sm ml-1">/api/containers.json</code>
      </p>
    </header>

    <div class="grid gap-6">
      <section class="bg-gray-800 rounded-lg p-6 shadow-lg">
        <div id="vms" hx-get="/api/vms" hx-trigger="load, every 3s">
          <div class="animate-pulse text-gray-500">Loading VMs...</div>
        </div>
      </section>

      <section class="bg-gray-800 rounded-lg p-6 shadow-lg">
        <div id="containers" hx-get="/api/containers" hx-trigger="load, every 3s">
          <div class="animate-pulse text-gray-500">Loading containers...</div>
        </div>
      </section>
    </div>

    <footer class="mt-8 text-center text-gray-500 text-sm">
      CloneBox v1.1 &bull; <a href="https://github.com/wronai/clonebox" class="text-cyan-400 hover:underline">GitHub</a>
    </footer>
  </div>
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
        return '<h2 class="text-xl font-semibold text-cyan-400 mb-4">🖥️ VMs</h2><p class="text-gray-500 italic">No VMs found.</p>'

    rows = [
        [str(i.get("name", "")), str(i.get("state", "")), str(i.get("uuid", ""))] for i in items
    ]
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
        return '<h2 class="text-xl font-semibold text-cyan-400 mb-4">🐳 Containers</h2><p class="text-gray-500 italic">No containers found.</p>'

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
