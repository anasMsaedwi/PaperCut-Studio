# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [1.0.0] - 2026-10-20
### Added
- Desktop app (PySide6): import with drag & drop, local background removal (optional rembg),
  paper edge (smooth / cut / torn), paper texture, soft shadow, live preview.
- Animation styles: subtle jitter, stop-motion, floating, bounce, gradual reveal.
- Export: PNG (transparent supported) and H.264 MP4 (16:9 / 9:16, 720p / 1080p, 24 / 30 FPS, 3-10 s, green chroma key).
- Unfold / crumple transition: a crumpled sheet unfolds to reveal a picture, then crumples away
  (preview + MP4 export in the app, and `unfold_transition.py` on the command line).
- App icon, README artwork, CI workflow and test suite.
