"""Snapshot classification.

Given the raw JPEG bytes of a channel picture, decide whether we are looking
at a live camera, a blind (dark and flat) camera, the Hikvision "no signal"
splash, or an unreadable frame.
"""

import io

import numpy as np
from PIL import Image

from app.config import (
    BLACK_LUMA_MAX,
    BLACK_STD_MAX,
    RED_RATIO_MIN,
    SPLASH_LUMA_MAX,
)


def classify_frame(jpeg_bytes):
    """Return OK, BLACK, NO_SIGNAL or UNREADABLE for a snapshot."""
    try:
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB").resize((320, 180))
    except Exception:
        return "UNREADABLE"

    a = np.asarray(img).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b

    red_ratio = ((r > 90) & (r - g > 50) & (r - b > 50)).mean()

    if red_ratio > RED_RATIO_MIN and luma.mean() < SPLASH_LUMA_MAX:
        return "NO_SIGNAL"
    if luma.mean() < BLACK_LUMA_MAX and luma.std() < BLACK_STD_MAX:
        return "BLACK"
    return "OK"
