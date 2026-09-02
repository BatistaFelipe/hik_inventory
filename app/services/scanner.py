"""Per-channel and per-device scanning for the web UI.

Wraps the ISAPI calls and the verdict into work units the Flask app drives
with its own thread pool. Yields NDJSON so the browser can render channels
as they come back instead of waiting for the whole DVR.
"""

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from app.config import CHANNEL_WORKERS, RETENTION_MONTHS
from app.services.classifier import classify_frame
from app.services.isapi import (
    device_info,
    get_snapshot,
    list_channels,
    month_iter,
    recording_days,
    video_loss_enabled,
)
from app.services.verdict import decide

log = logging.getLogger(__name__)


def _exc_label(exc: BaseException) -> str:
    """Class name only. The full repr goes to the logger, not the browser."""
    return type(exc).__name__


def scan_one_channel(base, auth, channel):
    """Snapshot + recording history for a single channel."""
    jpeg = get_snapshot(base, auth, channel)
    frame_state = classify_frame(jpeg) if jpeg else "NO_RESPONSE"
    days, fetch_errors = recording_days(base, auth, channel)
    verdict, action = decide(frame_state, days, fetch_errors)

    first = min(days).isoformat() if days else ""
    last = max(days).isoformat() if days else ""
    span = (max(days) - min(days)).days + 1 if days else 0

    return {
        "type": "channel",
        "channel": channel,
        "frame_state": frame_state,
        "recorded_days": len(days),
        "first_recording": first,
        "last_recording": last,
        "span_days": span,
        "videoloss_enabled": video_loss_enabled(base, auth, channel),
        "verdict": verdict,
        "action": action,
        "thumb": ("data:image/jpeg;base64," + base64.b64encode(jpeg).decode()) if jpeg else None,
    }


def scan_stream(host, port, user, password, on_done=None):
    """Yield NDJSON lines as each channel finishes, so the grid fills in live.

    ``on_done`` is an optional callback invoked with (device_info, host, port,
    done_msg) once the scan is complete. Errors raised by the callback are
    caught and attached to the ``done`` message as ``report_error``.
    """
    base = f"http://{host}:{port}"
    auth = HTTPDigestAuth(user, password)

    def line(obj):
        return json.dumps(obj) + "\n"

    try:
        info = device_info(base, auth)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        hint = " — usuario ou senha incorretos" if code == 401 else ""
        yield line({"type": "error", "message": f"HTTP {code}{hint}"})
        return
    except requests.RequestException as exc:
        log.warning("device_info failed for %s: %r", host, exc)
        yield line({"type": "error", "message": f"sem resposta: {_exc_label(exc)}"})
        return
    except ET.ParseError as exc:
        log.warning("device_info parse failed for %s: %s", host, exc)
        yield line({"type": "error", "message": f"resposta nao e ISAPI valido: {exc}"})
        return

    try:
        channels = list_channels(base, auth)
    except requests.RequestException as exc:
        log.warning("list_channels request failed for %s: %r", host, exc)
        yield line({"type": "error", "message": f"falha ao listar canais: {_exc_label(exc)}"})
        return
    except ET.ParseError as exc:
        log.warning("list_channels parse failed for %s: %s", host, exc)
        yield line({"type": "error", "message": f"falha ao listar canais: {exc}"})
        return

    yield line({"type": "device", "host": host, "port": port, "channels": channels, **info})

    results = []
    with ThreadPoolExecutor(max_workers=CHANNEL_WORKERS) as pool:
        futures = {pool.submit(scan_one_channel, base, auth, c): c for c in channels}
        for fut in as_completed(futures):
            channel = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                log.warning("scan_one_channel failed for %s ch%s: %r", host, channel, exc)
                row = {
                    "type": "channel",
                    "channel": channel,
                    "frame_state": "ERROR",
                    "verdict": "ERROR",
                    "action": "review",
                    "recorded_days": 0,
                    "first_recording": "",
                    "last_recording": "",
                    "span_days": 0,
                    "videoloss_enabled": None,
                    "thumb": None,
                    "error": _exc_label(exc),
                }
            results.append(row)
            yield line(row)

    firsts = [r["first_recording"] for r in results if r["first_recording"]]
    lasts = [r["last_recording"] for r in results if r["last_recording"]]
    oldest = min(firsts) if firsts else ""

    # A window-edge hit means real retention may be longer than we looked back.
    window_start = min(date(y, m, 1) for y, m in month_iter(RETENTION_MONTHS)).isoformat()

    done_msg = {
        "type": "done",
        "channels": len(results),
        "in_use": sum(
            1 for r in results if r["verdict"] in ("IN_USE", "CAMERA_BLIND", "CAMERA_DOWN")
        ),
        "empty": sum(1 for r in results if r["verdict"] == "EMPTY"),
        "review": sum(1 for r in results if r["action"] == "review"),
        "oldest_recording": oldest,
        "newest_recording": max(lasts) if lasts else "",
        "retention_days": (date.fromisoformat(max(lasts)) - date.fromisoformat(oldest)).days + 1
        if firsts and lasts
        else 0,
        "window_limited": bool(oldest) and oldest <= window_start,
        "window_months": RETENTION_MONTHS,
    }

    if on_done is not None:
        # Copy so the callback can't mutate what the browser sees, and vice
        # versa: an error attached below stays local to the wire payload.
        report_msg = dict(done_msg)
        try:
            on_done(info, host, port, done_msg)
        except Exception as exc:
            log.exception("on_done callback failed for %s", host)
            report_msg["report_error"] = f"nao foi possivel gravar relatorio: {_exc_label(exc)}"
        yield line(report_msg)
    else:
        yield line(done_msg)
