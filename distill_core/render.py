"""Page rendering in a separate, killable process.

pdfium is native code. A few hostile files abort it (a malformed JPEG 2000 image) or keep it busy for
minutes (a tiling pattern with microscopic steps). Rendered in the app's own process, such a file stops
the whole app. Here a child process renders; if it crashes or runs past its time limit, it is killed and
restarted, the caller gets None, and the app keeps running.

    svc = RenderService()
    png = svc.png(key, data, page, width)      # None: the page could not be drawn
    ink = svc.ink(key, data, page, width)      # ink coverage 0..1, or None
    svc.drop(key)

`key` names a PDF the child keeps open (one per document, and short-lived ones for previews); its bytes
are sent only the first time, or again after a restart.
"""
from __future__ import annotations

import io
import logging
import multiprocessing as mp
import threading
from collections import OrderedDict

import numpy as np

log = logging.getLogger("distill")

MAX_RENDER_SIDE = 6000  # px; longest side of any rendered page image
RENDER_TIMEOUT = 20.0   # s per page; the slowest real slide measured renders in well under 2 s
MAX_OPEN = 16           # PDFs the child keeps open (8 documents + previews)


# ----------------------------------------------------------------------------- drawing (any process)
def render_page(doc, i: int, width: int):
    """PIL image of page i, `width` px wide (long side capped at MAX_RENDER_SIDE)."""
    page = doc[i]
    w, h = page.get_size()
    # cap the long side: a page of 595 x 2^31 pt (seen in the wild) would otherwise exhaust memory
    scale = max(min(width / max(w, 1.0), MAX_RENDER_SIDE / max(h, 1.0)), 0.0001)
    try:
        bitmap = page.render(scale=scale)
        img = bitmap.to_pil().copy()  # own the pixels so the bitmap can be freed now
        bitmap.close()
        page.close()
        return img
    except ValueError:  # invalid page box (pdfium: "Crop exceeds page dimensions"): show a blank sheet
        page.close()
        from PIL import Image
        tall = min(int(width * abs(h) / max(abs(w), 1.0)), MAX_RENDER_SIDE)
        return Image.new("RGB", (max(int(width), 1), max(tall, 1)), "white")


def ink_coverage(img) -> float:
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    return float((765.0 - a.sum(axis=2)).mean() / 765.0)


def to_png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _child(conn) -> None:
    import pypdfium2 as pdfium
    docs: OrderedDict = OrderedDict()
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        op, key = msg[0], msg[1]
        try:
            if op == "load":
                docs[key] = pdfium.PdfDocument(msg[2])
                while len(docs) > MAX_OPEN:
                    docs.popitem(last=False)[1].close()
                conn.send(("ok", None))
            elif op == "drop":
                d = docs.pop(key, None)
                if d is not None:
                    d.close()
            elif op in ("png", "ink"):
                docs.move_to_end(key)
                img = render_page(docs[key], msg[2], msg[3])
                conn.send(("ok", to_png(img) if op == "png" else ink_coverage(img)))
        except Exception as e:  # a Python-level error (bad page box, unknown key...): report, keep serving
            if op != "drop":
                conn.send(("err", f"{type(e).__name__}: {e}"))


# ----------------------------------------------------------------------------- parent side
class RenderService:
    """One render child shared by every document. Calls are serialised (pdfium is single-threaded anyway)."""

    def __init__(self, timeout: float = RENDER_TIMEOUT):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc = None
        self._conn = None
        self._loaded: set = set()
        self._broken = False  # the child cannot start here: render in this process instead
        self._bad: set = set()  # (key, page) that crashed or timed out: not tried again

    def _start(self) -> None:
        ctx = mp.get_context("spawn")  # fork is unsafe with threads (the server's thread pool)
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_child, args=(child,), daemon=True, name="pdf-render")
        self._proc.start()
        child.close()
        self._conn = parent
        self._loaded.clear()

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(2)
        if self._conn is not None:
            self._conn.close()
        self._proc = self._conn = None
        self._loaded.clear()

    def _call(self, msg):
        self._conn.send(msg)
        if not self._conn.poll(self.timeout):
            raise TimeoutError(f"render took over {self.timeout:.0f} s")
        status, value = self._conn.recv()
        if status != "ok":
            raise RuntimeError(value)
        return value

    def _run(self, op: str, key: str, data: bytes, page: int, width: int):
        with self._lock:
            if self._broken:
                return self._local(op, data, page, width)
            if (key, page) in self._bad:
                return None
            if self._proc is None or not self._proc.is_alive():
                self._kill()
                try:
                    self._start()
                except Exception as e:  # cannot spawn here (restricted environment): stay in-process
                    log.warning("render process unavailable (%s); rendering in-process", e)
                    self._kill()
                    self._broken = True
                    return self._local(op, data, page, width)
            try:
                if key not in self._loaded:
                    self._call(("load", key, data))
                    self._loaded.add(key)
                return self._call((op, key, page, width))
            except RuntimeError as e:  # the child answered with an error: it is still healthy
                log.warning("page %d could not be drawn: %s", page + 1, e)
                return None
            except (OSError, EOFError, TimeoutError) as e:  # crashed or stuck: start over next time
                log.warning("renderer stopped on page %d (%s); restarting it", page + 1, e)
                self._kill()
                self._bad.add((key, page))
                return None

    @staticmethod
    def _local(op, data, page, width):
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        try:
            img = render_page(doc, page, width)
        finally:
            doc.close()
        return to_png(img) if op == "png" else ink_coverage(img)

    def png(self, key: str, data: bytes, page: int, width: int) -> bytes | None:
        return self._run("png", key, data, page, width)

    def ink(self, key: str, data: bytes, page: int, width: int) -> float | None:
        return self._run("ink", key, data, page, width)

    def failed(self, key: str, page: int) -> bool:
        """Whether this page already crashed or timed out the renderer."""
        return (key, page) in self._bad

    def drop(self, key: str) -> None:
        with self._lock:
            self._bad = {b for b in self._bad if b[0] != key}
            if key in self._loaded:
                self._loaded.discard(key)
                try:
                    self._conn.send(("drop", key))
                except (OSError, AttributeError):
                    pass

    def close(self) -> None:
        with self._lock:
            self._kill()


_service: RenderService | None = None
_service_lock = threading.Lock()


def service() -> RenderService:
    global _service
    with _service_lock:
        if _service is None:
            _service = RenderService()
        return _service
