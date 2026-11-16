# Third-party notices

PDF Distiller's own code is MIT-licensed (see [LICENSE](LICENSE)). It depends on the packages below,
installed from PyPI. All are compatible with MIT distribution.

| Package | License | Notes |
|---|---|---|
| [pikepdf](https://github.com/pikepdf/pikepdf) | MPL-2.0 | Used unmodified. Wheels bundle qpdf (Apache-2.0), zlib, libjpeg-turbo, OpenSSL and others; see its `third-party-licenses/`. |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Apache-2.0 / BSD-3-Clause | Wheels bundle PDFium (BSD-3-Clause) and its dependencies; see its `LICENSES/`. |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU (HPND) | |
| [NumPy](https://numpy.org) | BSD-3-Clause (+ bundled 0BSD, MIT, Zlib, CC0) | |
| [FastAPI](https://github.com/fastapi/fastapi) / [Starlette](https://github.com/encode/starlette) | MIT / BSD-3-Clause | |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | |
| [pywebview](https://github.com/r0x0r/pywebview) (optional) | BSD-3-Clause | Only for `run.py --window`. |

**MPL-2.0 (pikepdf):** file-level copyleft. Using it unmodified, as here, places no obligations on
PDF Distiller's own code. If pikepdf files are ever modified, those files must stay MPL-2.0 and their
source must be published.

**Packaged builds (.app / .exe):** binaries bundle the libraries above. Each release must ship their
license texts (the `licenses/` folders inside each package's `.dist-info`).

PyMuPDF (AGPL-3.0) is deliberately not used; see [docs/adr/0001-no-pymupdf.md](docs/adr/0001-no-pymupdf.md).
