"""Synthetic pathological PDFs: the files real users drop on the app that slide decks never contain.

Each builder returns bytes. `ALL` maps a name to (builder, expectation):
  "ok"     – must open, analyse and export without error
  "reject" – must be refused cleanly with a known error code (never a crash / 500)
"""
from __future__ import annotations

import io
import zlib

import make_samples
import pikepdf
from pikepdf import Array, Dictionary, Name, Pdf, Stream


def _save(pdf: Pdf, **kw) -> bytes:
    buf = io.BytesIO()
    pdf.save(buf, **kw)
    return buf.getvalue()


def _deck(n=2) -> Pdf:
    buf = io.BytesIO()
    make_samples.light_deck(n).save(buf)
    return Pdf.open(io.BytesIO(buf.getvalue()))


def _page(pdf: Pdf, content: bytes, box=(0, 0, 612, 792), **extra) -> Dictionary:
    d = Dictionary(Type=Name.Page, MediaBox=Array(list(box)), Contents=Stream(pdf, content), **extra)
    pdf.pages.append(pikepdf.Page(d))
    return d


# --------------------------------------------------------------------------- open problems
def encrypted_user_password():
    return _save(_deck(), encryption=pikepdf.Encryption(user="secret", owner="owner"))


def encrypted_owner_only():
    # opens without a password (most "protected" lecture PDFs are like this)
    return _save(_deck(), encryption=pikepdf.Encryption(user="", owner="owner",
                                                        allow=pikepdf.Permissions(extract=False, modify_other=False)))


def truncated():
    data = _save(_deck(3))
    return data[: len(data) // 2]


def broken_xref():
    data = bytearray(_save(_deck(2), object_stream_mode=pikepdf.ObjectStreamMode.disable))
    i = data.rfind(b"startxref")
    data[i + 10: i + 20] = b"9999999999"
    return bytes(data)


def garbage_before_header():
    return b"\x00" * 300 + b"junk junk\n" + _save(_deck(1))


def not_a_pdf():
    return b"PK\x03\x04 this is a zip pretending" + b"\x00" * 100


def empty_file():
    return b""


def zero_pages():
    pdf = Pdf.new()
    return _save(pdf)


# --------------------------------------------------------------------------- page geometry
def rotated_pages():
    pdf = _deck(4)
    for i, r in enumerate((90, 180, 270, -90)):
        pdf.pages[i].obj.Rotate = r
    return _save(pdf)


def rotate_not_multiple_of_90():
    pdf = _deck(1)
    pdf.pages[0].obj.Rotate = 45
    return _save(pdf)


def cropbox_offset_and_inverted_mediabox():
    pdf = _deck(2)
    pdf.pages[0].obj.CropBox = Array([100, 100, 500, 600])
    pdf.pages[1].obj.MediaBox = Array([612, 792, 0, 0])  # inverted corners
    return _save(pdf)


def zero_size_mediabox():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 0 0 10 10 re f", box=(0, 0, 0, 0))
    _page(pdf, b"BT /F1 12 Tf 72 720 Td (hi) Tj ET")
    return _save(pdf)


def missing_mediabox_inherited():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 50 50 200 200 re f")
    del pdf.pages[0].obj["/MediaBox"]
    pdf.Root.Pages.MediaBox = Array([0, 0, 595, 842])
    return _save(pdf)


def huge_page():
    pdf = Pdf.new()
    _page(pdf, b"0.2 g 0 0 14400 14400 re f 1 g 100 100 500 500 re f", box=(0, 0, 14400, 14400))
    return _save(pdf)


def userunit():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 10 10 50 50 re f", box=(0, 0, 200, 200), UserUnit=10)
    return _save(pdf)


# --------------------------------------------------------------------------- content problems
def empty_page_no_contents():
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    return _save(pdf)


def contents_array_split_mid_operator():
    pdf = Pdf.new()
    d = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))
    d.Contents = Array([Stream(pdf, b"0 0 1 rg 50 50 "), Stream(pdf, b"200 200 re f")])
    pdf.pages.append(pikepdf.Page(d))
    return _save(pdf)


def garbage_operators():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 1 2 3 re f foo bar (unclosed Tj ] ] >> 12 Q Q Q q q 1 0 0 0 0 0 cm 50 50 100 100 re f")
    return _save(pdf)


def unbalanced_q():
    pdf = Pdf.new()
    _page(pdf, b"q q q 0 0 1 rg 50 50 100 100 re f")
    _page(pdf, b"Q Q Q 1 0 0 rg 50 50 100 100 re f")
    return _save(pdf)


def bad_stream_filter():
    pdf = Pdf.new()
    d = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))
    s = Stream(pdf, b"\x00\x01garbage not flate")
    s.Filter = Name.FlateDecode
    d.Contents = s
    pdf.pages.append(pikepdf.Page(d))
    _page(pdf, b"0 0 1 rg 50 50 100 100 re f")
    return _save(pdf)


def missing_xobject_resource():
    pdf = Pdf.new()
    _page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q /Fm9 Do 0 0 1 rg 50 50 100 100 re f")
    return _save(pdf)


def missing_font():
    pdf = Pdf.new()
    _page(pdf, b"BT /F9 12 Tf 72 720 Td (no such font) Tj [(a) -200 (b)] TJ ET")
    return _save(pdf)


def recursive_form_xobject():
    pdf = Pdf.new()
    form = Stream(pdf, b"0 0 1 rg 0 0 10 10 re f /Fm0 Do")
    form.Type, form.Subtype, form.BBox = Name.XObject, Name.Form, Array([0, 0, 100, 100])
    form.Resources = Dictionary(XObject=Dictionary(Fm0=form))
    _page(pdf, b"/Fm0 Do", Resources=Dictionary(XObject=Dictionary(Fm0=form)))
    return _save(pdf)


def deeply_nested_forms():
    pdf = Pdf.new()
    inner = None
    for _ in range(60):
        f = Stream(pdf, b"0.5 g 0 0 10 10 re f" + (b" /Fm0 Do" if inner is not None else b""))
        f.Type, f.Subtype, f.BBox = Name.XObject, Name.Form, Array([0, 0, 100, 100])
        if inner is not None:
            f.Resources = Dictionary(XObject=Dictionary(Fm0=inner))
        inner = f
    _page(pdf, b"/Fm0 Do", Resources=Dictionary(XObject=Dictionary(Fm0=inner)))
    return _save(pdf)


def singular_matrices():
    pdf = Pdf.new()
    img = Stream(pdf, b"\xff\x00\x00" * 4)
    img.Type, img.Subtype, img.Width, img.Height = Name.XObject, Name.Image, 2, 2
    img.ColorSpace, img.BitsPerComponent = Name.DeviceRGB, 8
    _page(pdf, b"q 0 0 0 0 0 0 cm /Im0 Do Q q 1e30 0 0 1e30 0 0 cm /Im0 Do Q q 100 0 0 100 50 50 cm /Im0 Do Q",
          Resources=Dictionary(XObject=Dictionary(Im0=img)))
    return _save(pdf)


def nan_and_huge_numbers():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 99999999999999999999 50 1e400 -1e400 re f 1 0 0 rg 50 50 100 100 re f")
    return _save(pdf)


def broken_image_data():
    pdf = Pdf.new()
    img = Stream(pdf, b"\x00" * 10)  # far too short for 400x300 RGB
    img.Type, img.Subtype, img.Width, img.Height = Name.XObject, Name.Image, 400, 300
    img.ColorSpace, img.BitsPerComponent = Name.DeviceRGB, 8
    jpg = Stream(pdf, b"\xff\xd8\xff\xe0 not really a jpeg")
    jpg.Type, jpg.Subtype, jpg.Width, jpg.Height = Name.XObject, Name.Image, 400, 300
    jpg.ColorSpace, jpg.BitsPerComponent, jpg.Filter = Name.DeviceRGB, 8, Name.DCTDecode
    _page(pdf, b"q 500 0 0 400 50 50 cm /Im0 Do Q q 500 0 0 300 50 400 cm /Im1 Do Q",
          Resources=Dictionary(XObject=Dictionary(Im0=img, Im1=jpg)))
    return _save(pdf)


def exotic_image_colorspaces():
    pdf = Pdf.new()
    w, h = 64, 64
    cmyk = Stream(pdf, zlib.compress(bytes([0, 0, 0, 200]) * w * h))
    cmyk.Type, cmyk.Subtype, cmyk.Width, cmyk.Height = Name.XObject, Name.Image, w, h
    cmyk.ColorSpace, cmyk.BitsPerComponent, cmyk.Filter = Name.DeviceCMYK, 8, Name.FlateDecode
    one_bit = Stream(pdf, bytes([0b10101010]) * (w // 8) * h)
    one_bit.Type, one_bit.Subtype, one_bit.Width, one_bit.Height = Name.XObject, Name.Image, w, h
    one_bit.ImageMask, one_bit.BitsPerComponent = True, 1
    idx = Stream(pdf, bytes(range(4)) * (w * h // 4))
    idx.Type, idx.Subtype, idx.Width, idx.Height = Name.XObject, Name.Image, w, h
    idx.ColorSpace = Array([Name.Indexed, Name.DeviceRGB, 3, pikepdf.String(b"\x00\x00\x00\xff\x00\x00\x00\xff\x00\x00\x00\xff")])
    idx.BitsPerComponent = 8
    sixteen = Stream(pdf, b"\x80\x00" * w * h)
    sixteen.Type, sixteen.Subtype, sixteen.Width, sixteen.Height = Name.XObject, Name.Image, w, h
    sixteen.ColorSpace, sixteen.BitsPerComponent = Name.DeviceGray, 16
    _page(pdf, b"q 300 0 0 300 0 0 cm /A Do Q q 300 0 0 300 300 0 cm 0 0 1 rg /B Do Q "
               b"q 300 0 0 300 0 400 cm /C Do Q q 300 0 0 300 300 400 cm /D Do Q",
          Resources=Dictionary(XObject=Dictionary(A=cmyk, B=one_bit, C=idx, D=sixteen)))
    return _save(pdf)


def inline_images():
    pdf = Pdf.new()
    _page(pdf, b"q 200 0 0 200 100 100 cm BI /W 4 /H 4 /CS /G /BPC 8 ID \x00\x40\x80\xff"
               b"\x00\x40\x80\xff\x00\x40\x80\xff\x00\x40\x80\xff EI Q 0 0 1 rg 400 400 50 50 re f")
    return _save(pdf)


def type3_and_cid_text():
    pdf = Pdf.new()
    glyph = Stream(pdf, b"1000 0 0 0 750 750 d1 0 0 750 750 re f")
    t3 = Dictionary(Type=Name.Font, Subtype=Name.Type3, FontBBox=Array([0, 0, 750, 750]),
                    FontMatrix=Array([0.001, 0, 0, 0.001, 0, 0]), FirstChar=65, LastChar=65,
                    Widths=Array([1000]), Encoding=Dictionary(Type=Name.Encoding, Differences=Array([65, Name.sq])),
                    CharProcs=Dictionary(sq=glyph))
    cid = Dictionary(Type=Name.Font, Subtype=Name.Type0, BaseFont=Name("/NoSuchCID"), Encoding=Name("/Identity-H"),
                     DescendantFonts=Array([Dictionary(Type=Name.Font, Subtype=Name.CIDFontType2,
                                                       BaseFont=Name("/NoSuchCID"),
                                                       CIDSystemInfo=Dictionary(Registry=pikepdf.String("Adobe"),
                                                                                Ordering=pikepdf.String("Identity"),
                                                                                Supplement=0),
                                                       W=Array([0, Array([500, 600])]))]))
    _page(pdf, b"BT /T3 24 Tf 72 700 Td (AAA) Tj /C 12 Tf 0 -40 Td <00010002> Tj ET",
          Resources=Dictionary(Font=Dictionary(T3=t3, C=cid)))
    return _save(pdf)


def shadings_and_patterns():
    pdf = Pdf.new()
    fn = Dictionary(FunctionType=2, Domain=Array([0, 1]), C0=Array([0, 0, 1]), C1=Array([1, 0, 0]), N=1)
    sh = Dictionary(ShadingType=2, ColorSpace=Name.DeviceRGB, Coords=Array([0, 0, 612, 792]), Function=fn,
                    Extend=Array([True, True]))
    pat = Dictionary(Type=Name.Pattern, PatternType=2, Shading=sh)
    _page(pdf, b"/Sh0 sh /Pattern cs /P0 scn 50 50 300 300 re f /Pattern CS /P0 SCN 5 w 400 400 100 100 re S",
          Resources=Dictionary(Shading=Dictionary(Sh0=sh), Pattern=Dictionary(P0=pat)))
    return _save(pdf)


def annotations_forms_links():
    pdf = _deck(1)
    ap = Stream(pdf, b"1 0 0 rg 0 0 100 20 re f")
    ap.Type, ap.Subtype, ap.BBox = Name.XObject, Name.Form, Array([0, 0, 100, 20])
    widget = Dictionary(Type=Name.Annot, Subtype=Name.Widget, FT=Name.Tx, T=pikepdf.String("name"),
                        Rect=Array([100, 100, 200, 120]), AP=Dictionary(N=ap))
    link = Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([0, 0, 50, 50]),
                      A=Dictionary(S=Name.URI, URI=pikepdf.String("https://example.org")))
    pdf.pages[0].obj.Annots = pdf.make_indirect(Array([pdf.make_indirect(widget), pdf.make_indirect(link)]))
    pdf.Root.AcroForm = Dictionary(Fields=Array([pdf.pages[0].obj.Annots[0]]))
    return _save(pdf)


def optional_content_layers():
    pdf = Pdf.new()
    ocg = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=pikepdf.String("Hidden")))
    pdf.Root.OCProperties = Dictionary(OCGs=Array([ocg]), D=Dictionary(OFF=Array([ocg])))
    _page(pdf, b"/OC /L0 BDC 1 0 0 rg 0 0 612 792 re f EMC 0 0 1 rg 50 50 100 100 re f",
          Resources=Dictionary(Properties=Dictionary(L0=ocg)))
    return _save(pdf)


def shared_resources_many_pages():
    """Same content stream object on every page (some generators do this)."""
    pdf = Pdf.new()
    content = Stream(pdf, b"0.1 0.1 0.4 rg 0 0 612 792 re f 1 g 50 50 100 100 re f")
    for _ in range(30):
        pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]),
                                                 Contents=content)))
    return _save(pdf)


def many_tiny_elements():
    ops = b"".join(b"%d %d 2 2 re f " % (x * 3, y * 3) for x in range(150) for y in range(150))
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg " + ops)
    return _save(pdf)


def many_pages():
    pdf = Pdf.new()
    for _ in range(1500):
        _page(pdf, b"0.1 0.1 0.4 rg 0 0 612 792 re f 1 g 50 50 500 600 re f BT 0 g 12 Tf 72 720 Td ET")
    return _save(pdf, object_stream_mode=pikepdf.ObjectStreamMode.generate)


def linearized_with_objstreams():
    return _save(_deck(3), linearize=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)


def absurd_page_height():
    pdf = Pdf.new()
    _page(pdf, b"0 0 1 rg 50 50 200 200 re f", box=(0, 0, 595, 2147483648))
    return _save(pdf)


def page_tree_loop():
    """qpdf refuses a /Pages tree that contains itself; pdfium reads it (second-chance repair)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 2 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>"]
    content = b"0 0 1 rg 50 50 200 200 re f"
    objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    out, offs = bytearray(b"%PDF-1.7\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def pdf_version_2():
    return _save(_deck(1), force_version="2.0")


ALL = {
    "encrypted_user_password": (encrypted_user_password, "reject"),
    "encrypted_owner_only": (encrypted_owner_only, "ok"),
    "truncated": (truncated, "ok-or-reject"),
    "broken_xref": (broken_xref, "ok"),
    "garbage_before_header": (garbage_before_header, "ok"),
    "not_a_pdf": (not_a_pdf, "reject"),
    "empty_file": (empty_file, "reject"),
    "zero_pages": (zero_pages, "reject"),
    "rotated_pages": (rotated_pages, "ok"),
    "rotate_not_multiple_of_90": (rotate_not_multiple_of_90, "ok"),
    "cropbox_offset_and_inverted_mediabox": (cropbox_offset_and_inverted_mediabox, "ok"),
    "zero_size_mediabox": (zero_size_mediabox, "ok"),
    "missing_mediabox_inherited": (missing_mediabox_inherited, "ok"),
    "huge_page": (huge_page, "ok"),
    "userunit": (userunit, "ok"),
    "empty_page_no_contents": (empty_page_no_contents, "ok"),
    "contents_array_split_mid_operator": (contents_array_split_mid_operator, "ok"),
    "garbage_operators": (garbage_operators, "ok"),
    "unbalanced_q": (unbalanced_q, "ok"),
    "bad_stream_filter": (bad_stream_filter, "ok"),
    "missing_xobject_resource": (missing_xobject_resource, "ok"),
    "missing_font": (missing_font, "ok"),
    "recursive_form_xobject": (recursive_form_xobject, "ok"),
    "deeply_nested_forms": (deeply_nested_forms, "ok"),
    "singular_matrices": (singular_matrices, "ok"),
    "nan_and_huge_numbers": (nan_and_huge_numbers, "ok"),
    "broken_image_data": (broken_image_data, "ok"),
    "exotic_image_colorspaces": (exotic_image_colorspaces, "ok"),
    "inline_images": (inline_images, "ok"),
    "type3_and_cid_text": (type3_and_cid_text, "ok"),
    "shadings_and_patterns": (shadings_and_patterns, "ok"),
    "annotations_forms_links": (annotations_forms_links, "ok"),
    "optional_content_layers": (optional_content_layers, "ok"),
    "shared_resources_many_pages": (shared_resources_many_pages, "ok"),
    "many_tiny_elements": (many_tiny_elements, "ok"),
    "many_pages": (many_pages, "ok"),
    "linearized_with_objstreams": (linearized_with_objstreams, "ok"),
    "pdf_version_2": (pdf_version_2, "ok"),
    "absurd_page_height": (absurd_page_height, "ok"),
    "page_tree_loop": (page_tree_loop, "ok-or-reject"),
}
