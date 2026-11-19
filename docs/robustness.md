# Robustness: damaged and unusual PDFs

Lecture slides are usually well-formed. Files that reach a public tool are not: password-protected
exports, half-downloaded files, decks produced by odd generators, scanned handouts. This page records
how PDF Distiller was tested against them and what it does with each kind.

## Method

Every file goes through the HTTP API the way the UI uses it, in its own process with a 120 s timeout
(`tools/corpus_check.py`):

open → summary at three levels → elements and preview of the first, middle and last page →
original preview → word count → export → grayscale 4-up export → re-open both exports and check
the page count.

A file **passes** when it works end to end, or when it is refused with a clear, translated message
(password-protected, empty, not a PDF, damaged beyond repair). A **failure** is an HTTP 500, a crash,
a timeout or an export that cannot be opened.

Two sets:

- **Synthetic** (`tests/weird_pdfs.py`, 40 files, part of `pytest`): encryption, truncation, broken
  xref, zero/inverted/absurd page boxes, rotation by 45°, garbage and unbalanced operators,
  undecodable streams, missing fonts and images, recursive and 60-deep form XObjects, singular and
  infinite matrices, CMYK/1-bit/indexed/16-bit/inline images, Type 3 and CID fonts, shadings and
  patterns, form fields, optional content, 1500 pages, linearised, PDF 2.0.
- **pdf.js test corpus** (1103 files, Mozilla, collected from real bug reports). Not stored in this
  repository; fetch it with
  `git clone --depth 1 --filter=blob:none --sparse https://github.com/mozilla/pdf.js && git -C pdf.js sparse-checkout set test/pdfs`
  and run `python tools/corpus_check.py pdf.js/test/pdfs`.

## Results (2026-11-19)

| | before | after |
|---|---:|---:|
| pdf.js corpus: works end to end | 1061 | **1080** |
| refused with a clear message | 29 | 20 |
| failures (500 / crash / timeout) | 13 | **3** |
| synthetic set: failures | 4 / 38 | **0 / 40** |

Of the 20 refusals, 13 are password-protected, 6 are damaged beyond what qpdf and pdfium can read,
1 is not a PDF. Median time per file 0.14 s, 95th percentile 1.1 s.

## What changed

- **One bad page doesn't sink the document.** A page whose content can't be analysed or rewritten is
  kept unchanged; the UI lists those pages.
- **Second-chance repair.** If qpdf can't open a file, pdfium (more lenient) rebuilds it page by page
  in a child process, so a native crash on a hostile file can't take the app down.
- **Exports are verified** by re-opening them; qpdf can write an unreadable xref stream for repaired
  input, in which case the file is saved again without object streams.
- **Guards:** zero-size and 2³¹-pt page boxes (render size is capped at 6000 px), inf/NaN
  coordinates, fuzzed XMP metadata, N-up of pages that can't be tiled (falls back to one per sheet).

## Remaining failures

All three are inside pdfium, the renderer, at its latest version (pypdfium2 5.15.2):

- `jpx_numcomps.pdf`: a malformed JPEG 2000 image aborts the process while rendering.
- `tiling-pattern-tiny-steps*.pdf`: a tiling pattern with microscopic steps takes minutes to render.

Fixing these for good means rendering in a separate, killable process. That is planned; until then
such a file can stop the local app, which then has to be restarted.
