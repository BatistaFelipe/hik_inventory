#!/usr/bin/env python3
"""Local web UI for checking one Hikvision DVR at a time.

Fill in IP, port, user and password, hit Verificar, and it streams back a
contact sheet of every channel plus a retention summary.

The scan runs server-side because browsers cannot do HTTP Digest auth
cross-origin against the DVR.

    pip install -r requirements-dev.txt
    python hik_web.py
    # open http://127.0.0.1:5000

Bind address is loopback on purpose: the app forwards DVR credentials, so
it should not be reachable from the network.

Implementation lives under ``app/`` (MVC layout). This script is only a
thin entry point.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.web_app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
