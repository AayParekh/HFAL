"""Make a transparent PNG from two screenshots of the same page: one on white, one on black.

    uv run --no-project --with pillow --with numpy python -I docs/figures/transparent.py ON_WHITE ON_BLACK OUT

A pixel the page leaves empty is white in one and black in the other; a fully painted pixel is the same in both. The
difference gives each pixel's opacity, and the black shot divided by that opacity gives its colour (difference
matting). Text edges keep their smooth anti-aliasing.
"""
import sys

import numpy as np
from PIL import Image

white = np.asarray(Image.open(sys.argv[1]).convert("RGB"), dtype=np.float64)
black = np.asarray(Image.open(sys.argv[2]).convert("RGB"), dtype=np.float64)
alpha = np.clip(1 - (white - black).mean(axis=2) / 255, 0, 1)
safe = np.where(alpha > 0, alpha, 1)[..., None]
rgb = np.clip(black / safe, 0, 255)
out = np.dstack([rgb, alpha * 255]).round().astype(np.uint8)
Image.fromarray(out, "RGBA").save(sys.argv[3], optimize=True)
print(f"wrote {sys.argv[3]}")
