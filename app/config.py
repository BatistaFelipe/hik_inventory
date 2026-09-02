"""Shared constants for the Hikvision inventory tools.

All thresholds, worker counts and namespace values live here so that the
CLI and the web app share exactly the same behaviour.
"""

NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}
TIMEOUT = 8

CHANNEL_WORKERS = 6

RETENTION_MONTHS = 2
RECENT_DAYS = 3

# Frame classification thresholds. The Hikvision "no signal" splash is a
# saturated red logo on a dark background; a live-but-blind camera is dark
# and flat with no red at all.
RED_RATIO_MIN = 0.004
SPLASH_LUMA_MAX = 60
BLACK_LUMA_MAX = 20
BLACK_STD_MAX = 8

# A device is added to the low-retention report if its measured retention
# window is strictly below this threshold (in days).
RETENTION_THRESHOLD_DAYS = 30
