"""Everything pdfium does, in a separate, killable process.

pdfium is native code. A few hostile files abort it (a malformed JPEG 2000 image) or keep it busy for
minutes (a tiling pattern with microscopic steps). Run in the app's own process, such a file stops the
whole app. Here a child process draws pages and reads their text; if it crashes or runs past its time
limit, it is killed and restarted, the caller gets None, and the app keeps running.

    svc = RenderService()
    png = svc.png(key, data, page, width)      # None: the page could not be drawn
    ink = svc.ink(key, data, page, width)      # ink coverage 0..1, or None
    txt = svc.text(key, data, page, box)       # page text (or only the text inside box), or None
    n = svc.pages(data)                        # page count, or None: pdfium cannot read the file
    svc.drop(key)

`key` names a PDF the child keeps open (one per document, and short-lived ones for previews); its bytes
are sent only the first time, or again after a restart or after the child let it go to make room.
"""
from __future__ import annotations

import io
import logging
import multiprocessing as mp
import threading
import uuid
from collections import OrderedDict

import numpy as np

log = logging.getLogger("distill")

MAX_RENDER_SIDE = 6000  # px; longest side of any rendered page image
RENDER_TIMEOUT = 20.0   # s per page; the slowest real slide measured renders in well under 2 s
MAX_OPEN = 16           # PDFs the child keeps open; an older one is sent again when it is needed

# pdfium is not thread-safe. Only the in-process fallback (no child process possible) needs this lock.
PDFIUM_LOCK = threading.RLock()


# ----------------------------------------------------------------------------- pdfium work (any process)
def render_page(doc, i: int, width: int):
    """PIL image of page i, `width` px wide (long side capped at MAX_RENDER_SIDE)."""
    page = doc[i]
    try:
        w, h = page.get_size()
        # cap the long side: a page of 595 x 2^31 pt (seen in the wild) would otherwise exhaust memory
        scale = max(min(width / max(w, 1.0), MAX_RENDER_SIDE / max(h, 1.0)), 0.0001)
        try:
            bitmap = page.render(scale=scale)
        except ValueError:  # invalid page box (pdfium: "Crop exceeds page dimensions"): show a blank sheet
            from PIL import Image
            tall = min(int(width * abs(h) / max(abs(w), 1.0)), MAX_RENDER_SIDE)
            return Image.new("RGB", (max(int(width), 1), max(tall, 1)), "white")
        img = bitmap.to_pil().copy()  # own the pixels so the bitmap can be freed now
        bitmap.close()
        return img
    finally:
        page.close()


def page_text(doc, i: int, box=None, boxes=None):
    """Text of page i; with box (x0, y0, x1, y1 in PDF user space) only the text inside it.
    With boxes (a list of such boxes) a list of texts, one per box: the page's text layer is built once for
    all of them (built once per box, a page of 825 OCR words took 1.5 s)."""
    page = doc[i]
    tp = page.get_textpage()
    try:
        if boxes is not None:
            return [tp.get_text_bounded(*b) for b in boxes]
        return tp.get_text_bounded(*box) if box else tp.get_text_range()
    finally:
        tp.close()
        page.close()


def ink_coverage(img) -> float:
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    return float((765.0 - a.sum(axis=2)).mean() / 765.0)


def to_png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _work(doc, op: str, args):
    if op == "png":
        return to_png(render_page(doc, *args))
    if op == "ink":
        return ink_coverage(render_page(doc, *args))
    if op == "text":
        return page_text(doc, *args)
    if op == "count":
        return len(doc)
    raise ValueError(f"unknown operation {op!r}")


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
            elif key not in docs:  # let go to make room: the parent sends the bytes again
                conn.send(("missing", None))
            else:
                docs.move_to_end(key)
                conn.send(("ok", _work(docs[key], op, msg[2:])))
        except Exception as e:  # a Python-level error (bad page box, unreadable file...): report, keep serving
            if op != "drop":
                conn.send(("err", f"{type(e).__name__}: {e}"))


# ----------------------------------------------------------------------------- parent side
class _Missing(Exception):
    """The child no longer holds this document."""


class RenderService:
    """One child shared by every document. Calls are serialised (pdfium is single-threaded anyway)."""

    def __init__(self, timeout: float = RENDER_TIMEOUT):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc = None
        self._conn = None
        self._loaded: set = set()
        self._broken = False  # the child cannot start here: work in this process instead
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
        if self._proc is not None and self._proc.pid is not None:  # pid None: start() itself failed
            self._proc.kill()
            self._proc.join(2)
        if self._conn is not None:
            self._conn.close()
        self._proc = self._conn = None
        self._loaded.clear()

    def _call(self, msg):
        self._conn.send(msg)
        if not self._conn.poll(self.timeout):
            raise TimeoutError(f"pdfium took over {self.timeout:.0f} s")
        status, value = self._conn.recv()
        if status == "missing":
            raise _Missing
        if status != "ok":
            raise RuntimeError(value)
        return value

    def _send(self, op: str, key: str, data: bytes, page: int, args):
        if key not in self._loaded:
            self._call(("load", key, data))
            self._loaded.add(key)
        try:
            return self._call((op, key, page, *args))
        except _Missing:
            self._loaded.discard(key)
            self._call(("load", key, data))
            self._loaded.add(key)
            return self._call((op, key, page, *args))

    def _run(self, op: str, key: str, data: bytes, page: int, *args):
        with self._lock:
            if self._broken:
                return self._local(op, data, page, *args)
            if (key, page) in self._bad:
                return None
            if self._proc is None or not self._proc.is_alive():
                self._kill()
                try:
                    self._start()
                except Exception as e:  # cannot spawn here (restricted environment): stay in-process
                    log.warning("render process unavailable (%s); working in-process", e)
                    self._kill()
                    self._broken = True
                    return self._local(op, data, page, *args)
            try:
                return self._send(op, key, data, page, args)
            except RuntimeError as e:  # the child answered with an error: it is still healthy
                log.warning("page %d: pdfium could not %s it: %s", page + 1, "draw" if op in ("png", "ink") else "read", e)
                return None
            except (OSError, EOFError, TimeoutError) as e:  # crashed or stuck: start over next time
                log.warning("pdfium stopped on page %d (%s); restarting it", page + 1, e)
                self._kill()
                self._bad.add((key, page))
                return None

    @staticmethod
    def _local(op, data, page, *args):
        import pypdfium2 as pdfium
        with PDFIUM_LOCK:
            try:
                doc = pdfium.PdfDocument(data)
            except pdfium.PdfiumError:
                return None
            try:
                return _work(doc, op, (page, *args) if op != "count" else ())
            except Exception as e:
                log.warning("page %d: pdfium failed in-process: %s", page + 1, e)
                return None
            finally:
                doc.close()

    def png(self, key: str, data: bytes, page: int, width: int) -> bytes | None:
        return self._run("png", key, data, page, width)

    def ink(self, key: str, data: bytes, page: int, width: int) -> float | None:
        return self._run("ink", key, data, page, width)

    def text(self, key: str, data: bytes, page: int, box=None) -> str | None:
        return self._run("text", key, data, page, tuple(box) if box else None)

    def texts(self, key: str, data: bytes, page: int, boxes) -> list[str] | None:
        """Text inside each of several boxes on one page, in one call."""
        return self._run("text", key, data, page, None, [tuple(b) for b in boxes])

    def pages(self, data: bytes, keep: str | None = None) -> int | None:
        """Page count as pdfium reads the file; None if it cannot (or crashes on it).
        keep: open it under this key and leave it open (the document's own key: its bytes are sent once)."""
        key = keep or f"probe:{uuid.uuid4().hex[:8]}"
        if keep:
            self.drop(keep)  # a key that held other bytes (repaired copy) must be sent again
        try:
            return self._run("count", key, data, 0)
        finally:
            if not keep:
                self.drop(key)

    def failed(self, key: str, page: int) -> bool:
        """Whether this page already crashed or timed out pdfium."""
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
