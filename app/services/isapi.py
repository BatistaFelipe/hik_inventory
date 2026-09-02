"""Hikvision ISAPI client calls.

All DVR interaction lives here. Everything is read-only: snapshots, channel
listing, recording history and videoLoss configuration. No PUT/POST that
would mutate device configuration.
"""

import re
from datetime import date
from xml.etree import ElementTree as ET

import requests

from app.config import NS, RETENTION_MONTHS, TIMEOUT

_XML_DECL_RE = re.compile(rb"^\s*<\?xml[^?]*\?>")


def month_iter(months):
    """Yield (year, month) pairs going backwards from the current month."""
    today = date.today()
    year, month = today.year, today.month
    for _ in range(months):
        yield year, month
        month -= 1
        if month == 0:
            month = 12
            year -= 1


def _find_channels(root):
    """Return channel elements whether the DVR uses xmlns or not.

    Firmwares in the wild vary; a bare fallback keeps us functional instead
    of silently returning [] on an older box.
    """
    chans = root.findall("h:VideoInputChannel", NS)
    if chans:
        return chans, NS
    return root.findall(".//VideoInputChannel"), None


def _parse_isapi_xml(response, endpoint):
    """Parse ISAPI XML, working around mislabelled encodings.

    Some Hikvision firmwares declare ``encoding="UTF-8"`` but actually
    write channel names in cp1252 (e.g. ``Câmara``). The raw bytes fail
    UTF-8 decoding, so we retry as cp1252 with the XML declaration
    stripped — ``ET.fromstring`` on a ``str`` uses the string as-is.
    """
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as exc:
        try:
            fallback = _XML_DECL_RE.sub(b"", response.content, count=1)
            return ET.fromstring(fallback.decode("cp1252"))
        except (UnicodeDecodeError, ET.ParseError):
            pass

        ctype = response.headers.get("Content-Type", "?")
        body = response.content.decode("utf-8", errors="replace")
        lineno, col = getattr(exc, "position", (0, 0))
        lines = body.splitlines()
        offender = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        raise ET.ParseError(
            f"{endpoint} XML invalido (status={response.status_code}, "
            f"content-type={ctype}, erro linha {lineno} col {col}, "
            f"linha={offender!r}): {exc}"
        ) from exc


def list_channels(base, auth):
    """Discover configured video input channels instead of assuming 1..32."""
    url = f"{base}/ISAPI/System/Video/inputs/channels"
    r = requests.get(url, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    root = _parse_isapi_xml(r, "/ISAPI/System/Video/inputs/channels")
    chans, ns = _find_channels(root)
    ids = []
    for ch in chans:
        cid = ch.findtext("h:id", namespaces=ns) if ns else ch.findtext("id")
        if not cid:
            continue
        try:
            ids.append(int(cid))
        except ValueError:
            # XML in the wild carries stubs like <id></id> or <id>-</id>;
            # skip rather than blow up the whole device scan.
            continue
    return sorted(ids)


def get_snapshot(base, auth, channel):
    """Fetch a JPEG for one channel. Returns bytes or None."""
    url = f"{base}/ISAPI/Streaming/channels/{channel}01/picture"
    try:
        r = requests.get(url, auth=auth, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    ctype = r.headers.get("Content-Type", "")
    if r.status_code == 200 and ctype.startswith("image/"):
        return r.content
    return None


def recording_days(base, auth, channel):
    """Return the set of dates with recorded video and how many months failed.

    Returns ``(found, errors)`` so ``decide()`` can tell "the channel never
    recorded" (safe to disable) apart from "we couldn't reach the DVR to
    check" (must stay flagged for review). A silent ``set()`` would collapse
    both into EMPTY and disable a live channel on a flaky link.
    """
    track = channel * 100 + 1
    url = f"{base}/ISAPI/ContentMgmt/record/tracks/{track}/dailyDistribution"
    headers = {"Content-Type": "application/xml"}
    found = set()
    errors = 0

    for year, month in month_iter(RETENTION_MONTHS):
        body = (
            f'<trackDailyParam xmlns="{NS["h"]}">'
            f"<year>{year}</year><monthOfYear>{month}</monthOfYear>"
            f"</trackDailyParam>"
        )
        try:
            r = requests.post(url, auth=auth, data=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException:
            errors += 1
            continue
        if r.status_code != 200:
            errors += 1
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            errors += 1
            continue
        for day in root.iter(f"{{{NS['h']}}}day"):
            has_record = day.findtext("h:record", namespaces=NS) == "true"
            dom = day.findtext("h:dayOfMonth", namespaces=NS)
            if not (has_record and dom):
                continue
            try:
                found.add(date(year, month, int(dom)))
            except (ValueError, OverflowError):
                continue
    return found, errors


def video_loss_enabled(base, auth, channel):
    """Read the current videoLoss setting so the report shows the delta."""
    url = f"{base}/ISAPI/System/Video/inputs/channels/{channel}/videoLoss"
    try:
        r = requests.get(url, auth=auth, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return None
    # This endpoint uses xmlns="http://www.isapi.org/..." instead of the
    # hikvision.com namespace the other endpoints use — match any namespace.
    elem = root.find(".//{*}enabled")
    return elem is not None and (elem.text or "").strip() == "true"


def device_info(base, auth):
    """Read model/serial/firmware so the header confirms which box answered."""
    url = f"{base}/ISAPI/System/deviceInfo"
    r = requests.get(url, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    root = _parse_isapi_xml(r, "/ISAPI/System/deviceInfo")
    return {
        "name": root.findtext("h:deviceName", default="", namespaces=NS),
        "model": root.findtext("h:model", default="", namespaces=NS),
        "serial": root.findtext("h:serialNumber", default="", namespaces=NS),
        "firmware": root.findtext("h:firmwareVersion", default="", namespaces=NS),
    }
