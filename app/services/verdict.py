"""Verdict logic.

Cross-references the current snapshot state with the recording history to
avoid mistaking a dead camera for an empty channel.
"""

from datetime import date

from app.config import RECENT_DAYS


def decide(frame_state, days, fetch_errors=0):
    """Combine snapshot state and recording history into a verdict.

    ``fetch_errors`` is the number of month-buckets that failed to answer
    (network error, non-200, malformed XML). If any bucket failed *and* we
    have no recordings, we cannot honestly say the channel is EMPTY —
    downgrade to UNKNOWN so a flaky link does not disable a live channel.
    """
    today = date.today()
    recent = any((today - d).days <= RECENT_DAYS for d in days)
    ever = bool(days)

    if not ever and fetch_errors > 0:
        return "UNKNOWN", "review"

    # A channel with no snapshot at all and no recording anywhere in the
    # retention window has no camera on it. Some DVRs return the Hikvision
    # splash for an unused BNC, others return nothing; both mean empty.
    if not ever and frame_state in ("NO_SIGNAL", "NO_RESPONSE"):
        return "EMPTY", "disable"
    if ever and not recent:
        return "CAMERA_DOWN", "enable"
    if recent and frame_state == "BLACK":
        return "CAMERA_BLIND", "enable"
    if recent and frame_state == "OK":
        return "IN_USE", "enable"
    if not ever and frame_state in ("OK", "BLACK"):
        return "NO_RECORDING_BUT_VIDEO", "review"
    return "UNKNOWN", "review"
