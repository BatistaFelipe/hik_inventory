"""Flask blueprint: routes for the single-device web UI.

- ``GET  /``                    main scan page
- ``GET  /relatorio``           low-retention report page
- ``POST /api/scan``            NDJSON stream: one channel per line
- ``GET  /api/relatorio``       full report as JSON
- ``POST /api/relatorio/clear`` wipe the report
- ``POST /api/relatorio/delete`` drop a single entry by key
"""

import ipaddress
import json
import re
from pathlib import Path

from flask import Blueprint, Response, current_app, request

from app.services.scanner import scan_stream

bp = Blueprint("web", __name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "views" / "templates"

# Reject IANA link-local range so a browser drive-by can't pivot to the AWS
# / GCE metadata service (169.254.169.254) via this loopback proxy.
_BLOCKED_NETS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-\.]{0,253}[A-Za-z0-9])?$")


def _render(name):
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _validate_target(host: str, port: str) -> str | None:
    """Return a human-readable error, or None if host/port look legal."""
    if not host:
        return "informe o IP"
    if len(host) > 255:
        return "host invalido"
    try:
        port_int = int(port)
    except (TypeError, ValueError):
        return "porta invalida"
    if not 1 <= port_int <= 65535:
        return "porta fora do intervalo"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME_RE.match(host):
            return "host invalido"
        return None
    if any(addr in net for net in _BLOCKED_NETS):
        return "host bloqueado (link-local)"
    return None


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


@bp.get("/")
def index():
    return Response(_render("index.html"), mimetype="text/html")


@bp.get("/relatorio")
def report_page():
    return Response(_render("report.html"), mimetype="text/html")


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


@bp.post("/api/scan")
def api_scan():
    # No force=True: a proper JSON Content-Type is required so a cross-origin
    # <form> POST cannot silently drive the scanner from another tab.
    payload = request.get_json(silent=True) or {}
    host = (payload.get("host") or "").strip()
    port = (payload.get("port") or "80").strip()
    user = (payload.get("user") or "").strip()
    password = payload.get("password") or ""

    err = _validate_target(host, port)
    if err:
        return Response(
            json.dumps({"type": "error", "message": err}),
            mimetype="application/x-ndjson",
        )

    report = current_app.config["REPORT"]
    return Response(
        scan_stream(host, port, user, password, on_done=report.record),
        mimetype="application/x-ndjson",
    )


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


@bp.get("/api/relatorio")
def api_report_list():
    report = current_app.config["REPORT"]
    return Response(json.dumps(report.all(), ensure_ascii=False), mimetype="application/json")


@bp.post("/api/relatorio/clear")
def api_report_clear():
    current_app.config["REPORT"].clear()
    return Response(json.dumps({"ok": True}), mimetype="application/json")


@bp.post("/api/relatorio/delete")
def api_report_delete():
    payload = request.get_json(silent=True) or {}
    key = (payload.get("key") or "").strip()
    if not key:
        return Response(
            json.dumps({"ok": False, "error": "key obrigatoria"}),
            mimetype="application/json",
            status=400,
        )
    current_app.config["REPORT"].delete(key)
    return Response(json.dumps({"ok": True}), mimetype="application/json")
