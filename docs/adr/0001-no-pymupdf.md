# ADR 0001: pikepdf + pypdfium2 instead of PyMuPDF

- **Status:** accepted
- **Date:** 2026-11 (recorded after the fact; the decision dates from the first prototype)

## Context

PDF Distiller has to do three things with a PDF:

1. **Walk and rewrite page content streams** at the operator level: find each image, fill, stroke and
   shading, decide whether to drop it, and write a new stream without it. The same walk must assign the
   same element ids in analysis and in rewriting (see `ARCHITECTURE.md`).
2. **Render pages** fast for the live preview (~10 ms per page) and for the ink estimate.
3. **Extract text** with correct font decoding for the word counter.

The project is MIT-licensed and meant to stay usable anywhere, including as a hosted web version
later on.

## Options

| | PyMuPDF (fitz) | pikepdf + pypdfium2 | pypdf alone |
|---|---|---|---|
| License | **AGPL-3.0** or a paid commercial license | MPL-2.0 + Apache-2.0/BSD-3 | BSD-3 |
| Content stream access | yes (`get_drawings`, `clean_contents`, raw `xref` streams) | yes, via qpdf (`parse_content_stream`, `unparse_content_stream`) | yes, slower |
| Rendering | yes (MuPDF) | yes (PDFium, the Chrome engine) | no |
| Text extraction | very good | good (PDFium) | fair |
| Dependencies | one | two | one, but needs a renderer anyway |

## Decision

Use **pikepdf** (qpdf) to parse and rewrite content streams, and **pypdfium2** (PDFium) to render
and extract text. Do not use PyMuPDF.

The deciding factor is the license. Under the AGPL, offering PDF Distiller as a network service
would require publishing the full source of that service under the AGPL, and anyone embedding the
engine would inherit the same terms. A commercial MuPDF license avoids that, but it would make a
free tool depend on a paid agreement. With pikepdf and pypdfium2 the whole stack stays permissive:
MIT for our code, and only file-level copyleft (MPL-2.0) for pikepdf, used unmodified.

## Consequences

- **We maintain our own content stream interpreter** (`distill_core/interpreter.py`, ~1000 lines):
  graphics state, CTM, clipping, colour spaces, text positioning, Form XObjects. That is the main cost.
  It is also the core of the product: the id-stable analysis/rewrite pass would have been custom code
  on top of PyMuPDF too.
- Each document is opened twice (qpdf for structure, PDFium for pixels and text). Memory use is
  higher but stays well within limits for lecture decks; 500 pages analyse in about 2.4 s.
- PDFium is not thread-safe, so every render goes through one lock (`PDFIUM_LOCK`).
- Commercial use, a hosted version and packaged binaries are all possible without changing the
  license or buying one. Packaged builds must ship the bundled libraries' license texts
  (see `THIRD_PARTY_NOTICES.md`).
- Revisit only if a capability is needed that neither qpdf nor PDFium provides and the project's
  license goals have changed.
