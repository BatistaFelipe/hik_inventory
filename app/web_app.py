"""Flask application factory.

The report backing file lives next to the project root by default, so it
persists across restarts and stays out of the ``app/`` package.
"""

from pathlib import Path

from flask import Flask

from app.controllers.web_routes import bp
from app.models.report import LowRetentionReport

DEFAULT_REPORT_FILE = Path(__file__).resolve().parent.parent / "low_retention_report.json"

# Defense in depth: even if a XSS payload slipped past the JS escaping in
# templates/*.html, these headers narrow the blast radius (no inline scripts
# from third parties, no framing, no MIME sniffing).
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}


def create_app(report_file: Path = DEFAULT_REPORT_FILE) -> Flask:
    app = Flask(__name__)
    app.config["REPORT"] = LowRetentionReport(report_file)
    app.register_blueprint(bp)

    @app.after_request
    def _apply_security_headers(response):
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    return app
