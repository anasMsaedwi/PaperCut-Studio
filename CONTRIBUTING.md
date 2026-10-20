# Contributing

Thanks for helping to improve PaperCut Studio!

## Set up
```bash
git clone https://github.com/YOUR_USERNAME/papercut-studio.git
cd papercut-studio
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

## Before you open a pull request
1. Run the tests: `python -m unittest discover -s tests -v`
   (GUI tests run headless: set `QT_QPA_PLATFORM=offscreen`).
2. Keep the layers separate: `processing/` has no Qt imports, `export/` has no UI code, `ui/` has no image maths.
3. Describe what changed and add a line to `CHANGELOG.md`.

## Ideas that would help
- Presets (save / load settings), undo / redo, batch processing.
- More paper styles, more animation styles, image-sequence / ProRes 4444 export.
- Testing on Windows and macOS and reporting what you find.

## Artwork
`python tools/make_assets.py` regenerates the icon, banner, demo GIF and screenshot.
