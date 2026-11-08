"""Synthetic fixture documents for Telangana ingestion tests. All text is invented placeholder content,
not legal text, and no fixture describes a real instrument."""

import zlib


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages, image_pages=(), listed_image_pages=()):
    """Minimal valid PDF. pages: list of lists of text lines (None or [] = no text).
    Pages whose index is in image_pages get a 1x1 image, like a scanned page; listed_image_pages only
    list the image in their resources without drawing it."""
    objects = {}
    n_pages = len(pages)
    font_id = 3
    image_id = 4
    first_page_id = 5
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{first_page_id + 2 * i} 0 R" for i in range(n_pages))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    pixel = zlib.compress(b"\x80")
    objects[image_id] = (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
                         b"/BitsPerComponent 8 /Filter /FlateDecode /Length " + str(len(pixel)).encode() +
                         b" >>\nstream\n" + pixel + b"\nendstream")
    for i, lines in enumerate(pages):
        page_id, content_id = first_page_id + 2 * i, first_page_id + 2 * i + 1
        ops = []
        if i in image_pages:
            ops.append("q 400 0 0 600 100 100 cm /Im1 Do Q")
        if lines:
            ops.append("BT /F1 10 Tf 50 780 Td")
            for line in lines:
                ops.append(f"({_escape(line)}) Tj 0 -14 Td")
            ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        xobject = f" /XObject << /Im1 {image_id} 0 R >>" if i in image_pages or i in listed_image_pages else ""
        resources = f"<< /Font << /F1 {font_id} 0 R >>{xobject} >>"
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources {resources} "
                            f"/Contents {content_id} 0 R >>").encode()
        objects[content_id] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for oid in range(1, size):
        out += f"{offsets[oid]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
