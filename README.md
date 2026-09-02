# hik_inventory

Read-only inventory of analog channels on Hikvision DVRs. For every channel of a
DVR, it decides whether a camera is physically connected by cross-referencing
two independent signals — the current snapshot and the recording history — so a
dead camera is never mistaken for an empty channel.

Nothing is ever written to the DVRs. All ISAPI calls are strictly read-only.

## Entry point

Single-device Flask UI on `127.0.0.1:5000` (`hik_web.py`). Streams NDJSON per
channel so the grid fills in live in the browser.

## Setup

Windows (bash shell):

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements-dev.txt
```

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements.txt` pins the four runtime packages (`flask`, `requests`,
`pillow`, `numpy`); `requirements-dev.txt` adds `ruff`. There is no test suite
and no build step.

## Usage

```bash
python hik_web.py
# open http://127.0.0.1:5000
```

Fill in IP, port, user and password, hit **Verificar**, and the page streams
back a live contact sheet plus a retention summary. Devices whose retention
window is below 30 days are automatically added to
`low_retention_report.json` and shown at `/relatorio`.

The Flask app binds `127.0.0.1` on purpose: it forwards DVR credentials to a
device on the local network, so it must not be reachable from outside the
machine.

## Verdicts

`app.services.verdict.decide()` combines the snapshot state with the
recording history:

| Snapshot            | Recording           | Fetch errors | Verdict                 | Action  |
| ------------------- | ------------------- | ------------ | ----------------------- | ------- |
| any                 | never               | > 0          | UNKNOWN                 | review  |
| NO_SIGNAL / none    | never               | 0            | EMPTY                   | disable |
| any                 | had it, not recent  | any          | CAMERA_DOWN             | enable  |
| BLACK               | recent              | any          | CAMERA_BLIND            | enable  |
| OK                  | recent              | any          | IN_USE                  | enable  |
| OK / BLACK          | never               | 0            | NO_RECORDING_BUT_VIDEO  | review  |
| anything else       | —                   | —            | UNKNOWN                 | review  |

## Layout

MVC-ish structure under `app/`:

```text
hik_inventory/
├── hik_web.py                  # entry point (web wrapper, calls create_app)
├── low_retention_report.json   # persistence file for the report (runtime, gitignored)
├── requirements.txt            # pinned runtime deps
├── requirements-dev.txt        # runtime + ruff
├── pyproject.toml              # ruff config
└── app/
    ├── config.py               # thresholds, workers, retention, ISAPI namespace
    ├── models/                 # low-retention report store
    ├── services/               # classifier, ISAPI, verdict, scanner
    ├── controllers/            # Flask blueprint
    ├── views/templates/        # HTML pages (served as static text)
    └── web_app.py              # create_app() factory + security headers
```

## Linting

Ruff handles both linting and formatting (config in `pyproject.toml`):

```bash
ruff check .              # lint
ruff check --fix .        # lint + auto-fix
ruff format .             # format in place
ruff format --check .     # dry-run
```

## Configuration

No environment variables. All tunables live in `app/config.py`:

| Constant                   | Default | Meaning                                                              |
| -------------------------- | ------- | -------------------------------------------------------------------- |
| `TIMEOUT`                  | `8`     | Per-request HTTP timeout, seconds.                                   |
| `CHANNEL_WORKERS`          | `6`     | Channels scanned in parallel within one device.                      |
| `RETENTION_MONTHS`         | `2`     | How far back to query `dailyDistribution`.                           |
| `RECENT_DAYS`              | `3`     | A recording counts as "recent" if within this many days.             |
| `RED_RATIO_MIN`            | `0.004` | Minimum red-pixel ratio to consider a frame the Hikvision splash.    |
| `SPLASH_LUMA_MAX`          | `60`    | Max mean luma for a splash frame.                                    |
| `BLACK_LUMA_MAX`           | `20`    | Max mean luma for a `BLACK` frame.                                   |
| `BLACK_STD_MAX`            | `8`     | Max luma std-dev for a `BLACK` frame.                                |
| `RETENTION_THRESHOLD_DAYS` | `30`    | Devices below this retention window get logged to the JSON report.   |

## Constraints

- HTTP only. No HTTPS support in the ISAPI client.
- HTTP Digest auth only. Hikvision DVRs do not accept Basic.
- `hik_web.py` must stay bound to loopback — it forwards raw DVR credentials.
- All DVR interaction is read-only. Do not add mutating ISAPI PUT/POST calls
  without an explicit request.
- The splash-vs-blind classification heuristic is empirical and version-
  sensitive; tune thresholds in `app/config.py` against real captures rather
  than rewriting the classifier.
