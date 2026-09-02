> This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Read-only inventory of analog channels on Hikvision DVRs. For every channel of a DVR, decide whether a camera is physically connected. Nothing is ever written to the DVR.

Single-device Flask web UI on `127.0.0.1:5000` (`hik_web.py`). Streams NDJSON per channel so the grid fills in live. Replaces the add-to-iVMS / look / remove-from-iVMS loop.

The entry point (`hik_web.py`) is a thin wrapper — the actual logic lives under `app/`.

## Commands

Windows (bash shell):

```bash
# Activate the existing venv
source .venv/Scripts/activate

# Install runtime + dev deps (pinned)
pip install -r requirements-dev.txt

# Web UI (loopback only — it forwards DVR credentials)
python hik_web.py
# then open http://127.0.0.1:5000

# Linter (ruff — config in pyproject.toml)
ruff check .                # lint
ruff check --fix .          # lint + auto-fix
ruff format .               # format in place
ruff format --check .       # format check without writing
```

There are no tests and no build step.

## Architecture

MVC layout under `app/`:

```text
hik_inventory/
├── hik_web.py                  # entry point (web wrapper, calls create_app)
├── low_retention_report.json   # persistence file for the report (runtime, gitignored)
├── requirements.txt            # pinned runtime deps
├── requirements-dev.txt        # runtime + ruff
└── app/
    ├── config.py               # constants (NS, TIMEOUT, thresholds, workers, retention)
    ├── models/
    │   └── report.py           # LowRetentionReport (JSON, thread-safe)
    ├── services/               # business logic
    │   ├── classifier.py       # classify_frame()
    │   ├── isapi.py            # list_channels, get_snapshot, recording_days,
    │   │                       # video_loss_enabled, device_info, month_iter
    │   ├── verdict.py          # decide()
    │   └── scanner.py          # scan_one_channel / scan_stream (NDJSON generator)
    ├── views/
    │   └── templates/
    │       ├── index.html      # main scan page (served as static text)
    │       └── report.html     # low-retention report page
    ├── controllers/
    │   └── web_routes.py       # Flask blueprint (pages + /api/scan + /api/relatorio*)
    └── web_app.py              # create_app() factory + security headers
```

### The verdict is a cross-reference, not a single signal

A dead camera must never be misread as an empty channel. `app.services.verdict.decide()` combines two independent signals:

1. **Current snapshot** (JPEG from `ISAPI/Streaming/channels/<ch>01/picture`) classified by `classify_frame()` as `OK`, `BLACK`, `NO_SIGNAL`, or `UNREADABLE`. `NO_SIGNAL` is the Hikvision splash (red logo on dark background) — detection thresholds are `RED_RATIO_MIN`, `SPLASH_LUMA_MAX`, `BLACK_LUMA_MAX`, `BLACK_STD_MAX` (in `app/config.py`).
2. **Recording history** over `RETENTION_MONTHS` (from `ISAPI/ContentMgmt/record/tracks/<ch*100+1>/dailyDistribution`). "Recent" means within `RECENT_DAYS`. `recording_days()` returns `(days, fetch_errors)` so a flaky link is not collapsed into "never recorded".

Verdict matrix (see `decide()`):

| Snapshot            | Recording           | Fetch errors | Verdict                 | Action  |
| ------------------- | ------------------- | ------------ | ----------------------- | ------- |
| any                 | never               | > 0          | UNKNOWN                 | review  |
| NO_SIGNAL / none    | never               | 0            | EMPTY                   | disable |
| any                 | had it, not recent  | any          | CAMERA_DOWN             | enable  |
| BLACK               | recent              | any          | CAMERA_BLIND            | enable  |
| OK                  | recent              | any          | IN_USE                  | enable  |
| OK / BLACK          | never               | 0            | NO_RECORDING_BUT_VIDEO  | review  |
| anything else       | —                   | —            | UNKNOWN                 | review  |

Any change to thresholds, verdict names, or the `action` field ripples into the web UI colours — `COLORS` in the JS inside `app/views/templates/index.html`. Keep them in sync.

### Concurrency

Single thread pool: `CHANNEL_WORKERS = 6` — channels within one device scanned in parallel. A failing channel is caught and turned into an `ERROR` row rather than killing the whole scan.

### ISAPI conventions

- Base URL: `http://<ip>:<port>` (no HTTPS support in this codebase).
- Auth: `HTTPDigestAuth` — Hikvision DVRs do not accept Basic.
- XML namespace: `http://www.hikvision.com/ver20/XMLSchema`, bound as `h:` via `NS`. `list_channels()` falls back to a namespace-less XPath so older firmwares still work.
- Channel ID convention: snapshot uses `<ch>01` (e.g. `301` for channel 3), record track uses `<ch>*100 + 1` (e.g. `301` for channel 3). These are Hikvision quirks, not typos.
- All ISAPI XML is parsed from `r.content` (bytes) so a DVR without a charset header does not break UTF-8 declarations.

### Web UI transport

`/api/scan` returns `application/x-ndjson`. Message types: `device` (once, up front, with the channel list so the UI knows the total), `channel` (one per finished channel, contains the base64 thumbnail), `done` (summary with retention window). `window_limited=true` on `done` means the oldest recording hit the edge of the retention lookback window — actual retention may be longer than reported.

The `done` message is also passed to `LowRetentionReport.record()` via the `on_done` callback in `scan_stream()`; devices whose retention window is below `RETENTION_THRESHOLD_DAYS` (30 days) get persisted to `low_retention_report.json`.

`/api/scan` and `/api/relatorio/delete` require a JSON `Content-Type` (no `force=True` on `get_json`) and `/api/scan` validates the target host (rejects link-local / non-numeric ports, requires a legal hostname or IP) before opening the ISAPI socket. Server-provided values are HTML-escaped before hitting `innerHTML`; a hostile DVR cannot inject `<script>` into the operator's browser.

## Constraints

- The Flask app binds `127.0.0.1` on purpose: it forwards DVR credentials to a device on the local network. Do not change the bind address without adding auth in front of it.
- All DVR interaction is strictly read-only. Do not add ISAPI PUT/POST calls that mutate device configuration without an explicit request.
- The DVR splash-vs-blind heuristic is empirical and version-sensitive. If classification drifts, tune the thresholds in `app/config.py` against real captures rather than rewriting the classifier.
- The `app/views/templates/*.html` files are served as static text via `Response(mimetype="text/html")`, **not** through Jinja rendering — the CSS uses raw `{}` characters that would clash with Jinja syntax. Do not add `render_template` calls unless you also escape the `{}` blocks.
