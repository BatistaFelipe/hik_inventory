"""Low-retention report persistence.

Devices whose retention window falls below ``RETENTION_THRESHOLD_DAYS`` are
saved to a small JSON file next to the web app. Dedupe is by serial number
(fallback host:port).
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from app.config import RETENTION_THRESHOLD_DAYS


class LowRetentionReport:
    """Thread-safe JSON-backed store of low-retention observations."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    # -- persistence ------------------------------------------------------

    def _load(self) -> dict:
        if not self.path.exists():
            return {"entries": []}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or "entries" not in data:
                return {"entries": []}
            return data
        except (OSError, json.JSONDecodeError):
            return {"entries": []}

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    # -- read -------------------------------------------------------------

    def all(self) -> dict:
        with self._lock:
            return self._load()

    # -- write ------------------------------------------------------------

    @staticmethod
    def _entry_key(device_info: dict, host: str, port: str) -> str:
        serial = (device_info.get("serial") or "").strip()
        return serial if serial else f"{host}:{port}"

    def record(self, device_info: dict, host: str, port: str, summary: dict) -> None:
        """Persist a device whose retention window is below the threshold.

        Dedupe by serial (fallback host:port). Existing entries are updated
        with the newest observation while keeping the original first_seen
        timestamp.
        """
        retention_days = summary.get("retention_days") or 0
        if retention_days <= 0 or retention_days >= RETENTION_THRESHOLD_DAYS:
            return

        key = self._entry_key(device_info, host, port)
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            data = self._load()
            entries = data["entries"]
            existing = next((e for e in entries if e.get("key") == key), None)

            record = {
                "key": key,
                "name": device_info.get("name", ""),
                "host": host,
                "port": port,
                "model": device_info.get("model", ""),
                "serial": device_info.get("serial", ""),
                "firmware": device_info.get("firmware", ""),
                "channels": summary.get("channels", 0),
                "in_use": summary.get("in_use", 0),
                "empty": summary.get("empty", 0),
                "review": summary.get("review", 0),
                "retention_days": retention_days,
                "oldest_recording": summary.get("oldest_recording", ""),
                "newest_recording": summary.get("newest_recording", ""),
                "window_limited": summary.get("window_limited", False),
                "last_seen": now,
            }

            if existing:
                record["first_seen"] = existing.get("first_seen", now)
                entries.remove(existing)
            else:
                record["first_seen"] = now

            entries.append(record)
            entries.sort(key=lambda e: e.get("retention_days", 0))
            self._save(data)

    def clear(self) -> None:
        with self._lock:
            self._save({"entries": []})

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._load()
            data["entries"] = [e for e in data["entries"] if e.get("key") != key]
            self._save(data)
