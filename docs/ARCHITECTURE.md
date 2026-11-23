# Architecture

This document is for contributors, human or AI.
**Read it before changing anything; `python -m pytest -q` must pass after every change.**

## Layers

```
distill_core/        UI-independent engine (plain Python library)
  model.py           Settings, tiers (tier_settings), Overrides, PageOp, Element
  interpreter.py     Content stream interpreter: analysis + rewrite (CRITICAL)
  classify.py        Element classes and removal decisions (fast, no re-reading)
  images.py          Graying / fading the remaining images
  imgfeat.py         Image content analysis: text score, photo regions (tile heuristic, no OCR)
  pageops.py         Delete/reorder/rotate pages, N-up
  engine.py          DistillDocument: the only public API
app/
  server.py          FastAPI, 127.0.0.1 only. No business logic.
  static/            index.html + style.css + app.js + i18n/*.json (no build step)
run.py               Starts the server; --window opens a pywebview window (always in packaged builds)
packaging/build.py   PyInstaller build: macOS .app/.dmg, Windows .exe
tests/               make_samples.py (synthetic slides), test_core.py, test_server.py, test_i18n.py
profiles/            Built-in profiles (JSON). User profiles: ~/.pdf-distiller/profiles
docs/                README assets, ADRs
```

A new front end (desktop app, web service, batch job) = calling `DistillDocument`.
Do not make the engine depend on a UI.

## Flow

1. `analyze()` walks every page's content stream **without rendering** and records each visual element
   (`image`, `fill`, `stroke`, `shading`) with its box, area share, luminance and a **signature**.
   Uses multiple processes from 120 pages up.
2. `decide(settings, overrides)` classifies: `white`, `background`, `repeated`, `large`, `other`, and
   produces the element ids (`"<page>-<seq>"`) to remove on each page. The result is cached.
3. `distill_pages()` runs the same interpreter in rewrite mode and drops the elements whose id is listed.

## Critical rules

- **Id consistency:** analysis and rewrite share the same `PageWalker._walk` code. The element counter must
  advance in the same order in both passes. If one pass counts an element kind and the other skips it, the
  wrong element is removed. `test_ids_are_stable_between_passes` catches this.
- **Removing a path = replacing its painting operator with `n`.** Path construction and clipping (`W`) are
  kept; otherwise clipping breaks and hidden content can become visible.
- **White fills (luminance > 0.95) are never removed.** They use no ink, and removing them uncovers what
  is underneath.
- **Form XObjects are shared.** A changed form is never modified in place; a new copy is created and cached
  by content hash (the same theme on 500 pages becomes one copy). Do not touch the original form.
- **Text colour:** colour operators inside text are not changed. Before each show operator (`Tj/TJ/'/"`)
  `0 g` is inserted when needed, then the original colour is restored (`Color.restore`). If a kept dark
  backdrop sits behind it (backdrops), light text stays as it is.
- **Grayscale:** numeric `rg/k/sc/scn` colours become `g`; the `Color.dirty` flag makes sure the `cs`
  operator is rewritten before the next `sc/scn` once the colour space has diverged from the original.
- **Text boxes:** every `Tj/TJ/'/"` is measured with the font widths (`FontInfo`); consecutive pieces
  side by side on the same baseline become one box (`_text_piece`). Id `"<page>-t<seq>"`, separate from
  the graphics counter. Signature = content hash (font + size + raw bytes) + start position.
- **Removing text = making it invisible** (`3 Tr` … original `Tr`). Taking text out of the stream would
  shift later pieces on the same line; invisible text keeps the advance.
- **Tiers never remove text.** Text is only removed by a selection (`elements`, `signatures`, `regions`)
  or by the `remove_repeated_text` setting. Region rules (`regions`) are in view coordinates and only
  apply to text boxes.
- **Cropping = a PDF clip path.** The image's `Do` is wrapped as `q <path> W n … Do Q`; the image is not
  re-encoded. Polygons are stored in the image's unit square (`decide_full` → `clips`), so "all pages"
  also works for copies of the same image placed differently. *keep* polygons are given the same winding
  and joined (nonzero); each *erase* polygon is its own even-odd clip (their intersection is the
  complement of the union). User crops arrive in view coordinates and are converted with `view_to_user`
  + the inverse CTM.
- **Images containing text:** `imgfeat` inspects images larger than 2% of the page once (by signature)
  during analysis; those with a text score ≥ 0.6 get the `text_image` class and are not removed by tiers.
  Exception: an image with mean ink ≥ `PHOTO_INK` (0.30) is a photo, whatever its tiles say. Dark photos
  (cars, machines) fool the tile test; real tables and formulas are mostly white paper.
- **Ink report:** `ink_report()` estimates every printed page analytically (kept element area × darkness,
  no rendering, ~ms for 500 pages) and lists the kept elements that cost the most ink. Pages above
  `INK_HEAVY_PAGE` get a warning in the UI. The rendered gauge (`ink_estimate`) stays the reference for the
  overall saving; the report is for "where is the ink going".
- **Selection in the UI** is by the smallest element at the clicked point (`hitsAt`), not DOM order.
- **Word counter** gets its text from pdfium (which decodes font encodings); text in removed boxes is
  subtracted from the count.
- **pdfium is not thread-safe:** every render runs under `PDFIUM_LOCK`.

## Licensing

PyMuPDF is deliberately not used (AGPL); see [docs/adr/0001-no-pymupdf.md](adr/0001-no-pymupdf.md).
Dependencies and their licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Check the license
before adding a dependency.

## Working with smaller models

- UI change → `app/static/*` only. Do not touch the engine files.
- UI text → `app/static/i18n/{en,de,tr}.json` (all three) + `data-i18n="<key>"` in HTML
  (for attributes: `data-i18n-title`, `-aria-label`, `-placeholder`, `-alt`) or `t("<key>", {n})` in JS.
  Plurals use `<key>_one`. The server never returns error text, only an `"error.<name>"` key.
  A built-in profile's file name is its id; the display name comes from the `profile.<id>` key.
  `tests/test_i18n.py` catches missing/extra keys and mismatched placeholders.
- New setting → `Settings` field + `classify.py` rule + `index.html` control (wired automatically via
  `data-s="<field>"`) + a test.
- Changes to `interpreter.py` should be made with the strongest model available, with a new test.
- Lint: `ruff check .` (config in `pyproject.toml`). CI runs ruff and pytest on Linux, macOS and Windows.

## Roadmap

- Editing crops with handles in the preview, region selection for images, drag-and-drop page order,
  page cropping, merging/splitting PDFs, classification tuning on real PDFs.
- Batch processing (folder + profile), packaged app (.app / .exe), a web version (same API, with file
  size and session limits).
