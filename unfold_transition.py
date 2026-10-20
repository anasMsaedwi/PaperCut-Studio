#!/usr/bin/env python
"""Command-line version of the unfold / crumple transition (same engine as the app).

    python unfold_transition.py                         # built-in demo picture -> unfold.mp4
    python unfold_transition.py --image photo.jpg --out reveal.mp4
    python unfold_transition.py --vertical --size 720 --seconds 6 --sheet contact.png
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

from export.mp4_writer import Mp4Writer
from export.utils import ensure_disk_space
from processing.crumple import TransitionRenderer
from processing.settings import Settings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="picture to reveal (default: built-in demo illustration)")
    ap.add_argument("--out", default="unfold.mp4")
    ap.add_argument("--size", type=int, choices=(720, 1080), default=1080, help="short side in pixels")
    ap.add_argument("--vertical", action="store_true", help="9:16 instead of 16:9")
    ap.add_argument("--seconds", type=float, default=8.5)
    ap.add_argument("--fps", type=int, choices=(24, 30), default=24)
    ap.add_argument("--hold", type=int, default=2, help="frames each stop-motion pose is held")
    ap.add_argument("--seed", type=int, default=7, help="changes the crumple pattern")
    ap.add_argument("--sheet", help="also save a contact-sheet PNG of 8 frames")
    a = ap.parse_args()

    s = Settings(aspect="9:16" if a.vertical else "16:9", resolution=a.size, fps=a.fps,
                 crumple_seed=a.seed, bg_mode="solid", bg_color=(62, 70, 86))
    size = s.frame_size()
    picture = None
    if a.image:
        try:
            with Image.open(a.image) as im:
                picture = np.array(ImageOps.exif_transpose(im).convert("RGB"))
        except (OSError, ValueError) as e:
            sys.exit(f"Could not read the image '{a.image}': {e}")

    print(f"Building paper model ({size[0]}x{size[1]}) ...")
    r = TransitionRenderer(picture, s, size, seconds=a.seconds, hold=a.hold)
    ensure_disk_space(a.out, 25_000_000 + int(a.seconds * 10_000_000))
    writer = Mp4Writer(a.out, size[0], size[1], a.fps)
    keep = set(np.linspace(0, r.n_frames - 1, 8).round().astype(int).tolist()) if a.sheet else set()
    kept, t0 = {}, time.time()
    try:
        for i in range(r.n_frames):
            f = r.frame(i)
            writer.write(f)
            if i in keep:
                kept[i] = cv2.resize(f, (480, int(480 * size[1] / size[0])), interpolation=cv2.INTER_AREA)
            if i % a.fps == 0:
                print(f"  frame {i}/{r.n_frames}  ({time.time() - t0:.0f}s)")
        writer.close()
    except BaseException:
        writer.abort()
        raise
    if a.sheet and kept:
        t = [kept[k] for k in sorted(kept)]
        Image.fromarray(np.vstack([np.hstack(t[:4]), np.hstack(t[4:8])])).save(a.sheet)
    print(f"Done: {a.out}  ({r.n_frames} frames, {a.seconds:.1f}s, {a.fps} fps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
