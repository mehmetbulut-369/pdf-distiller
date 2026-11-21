"""Hammer one document from several threads, the way the UI does when you jump to a page
(original + processed render + element text arrive at once). A pdfium object freed outside
PDFIUM_LOCK shows up here as a hard crash (SIGTRAP/SIGSEGV), not as a test failure.

    MallocScribble=1 python tools/stress_concurrency.py lecture.pdf
"""
from __future__ import annotations

import random
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from distill_core.engine import DistillDocument  # noqa: E402
from distill_core.model import Overrides, Settings  # noqa: E402


def main(path: str, rounds: int = 1500) -> None:
    d = DistillDocument(Path(path).read_bytes(), Path(path).name)
    d.analyze()
    s, ov = Settings(), Overrides()
    els = [e for p in d.pages for e in p.elements if e.kind == "text"] or [e for p in d.pages for e in p.elements]

    def text():
        for _ in range(rounds):
            e = random.choice(els)
            d._el_text.pop(e.id, None)
            d._page_text.pop(e.page, None)
            d.element_text(e)
            d.page_text(e.page)

    def original():
        for _ in range(rounds // 10):
            d.render_original(random.randrange(d.n_pages), 300)

    def processed():
        for _ in range(rounds // 20):
            d.render_processed(random.randrange(d.n_pages), s, ov, 300)

    threads = [threading.Thread(target=f) for f in (text, text, text, original, original, processed, processed)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"OK: {d.n_pages} pages, {len(els)} elements")


if __name__ == "__main__":
    main(sys.argv[1])
