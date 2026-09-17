"""One test per bug found while diagnosing the original.

    python test_extract.py                      # the rebuilt extractor
    python test_extract.py original.data_extractor   # the original, for proof

The second command is the point of this file: a suite that the broken code
passes is decorative. Every test below is named after a real failure, and the
original fails or errors on all but one of them.

No pytest, no network, no fixtures on disk. Runs in about two seconds.
"""

import importlib
import io
import sys
import traceback

import fitz
from PIL import Image, ImageDraw

# argv[1] names the module to test, so the same suite can be pointed at
# backend/original/data_extractor.py for the comparison. Skip anything starting
# with "-": under `python -m pytest -q` this file is imported with pytest's own
# flags still in sys.argv, and argv[1] is "-q", which is not a module.
_arg = sys.argv[1] if len(sys.argv) > 1 else None
MODULE = _arg if _arg and not _arg.startswith("-") else "data_extractor"
mod = importlib.import_module(MODULE)
IS_ORIGINAL = "original" in MODULE


# ---------------------------------------------------------------- adapters
# The original only exposed data_extraction(path) and only accepted a path, so
# the same assertions are run through a thin shim that writes a temp file.

def extract(data: bytes, filename: str):
    if hasattr(mod, "extract"):
        return mod.extract(data, filename)
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), filename)
    with open(path, "wb") as f:
        f.write(data)
    return mod.data_extraction(path)


def pages_of(result):
    """Page count, however the module reports it."""
    return result.get("page_count", 1)


def tables(text):
    fn = getattr(mod, "extract_tables", None) or mod.extract_tables_from_text
    return fn(text)


# ---------------------------------------------------------------- fixtures

def make_pdf(pages_text):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def make_image(lines, size=(1000, 400)):
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 40), line, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_scanned_pdf(lines):
    """A PDF with no text layer — a picture of a page, which is what a scanner
    produces and what the original silently rejected."""
    png = make_image(lines)
    doc = fitz.open()
    page = doc.new_page(width=1000, height=400)
    page.insert_image(page.rect, stream=png)
    data = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------- the bugs

def test_txt_is_actually_supported():
    """BUG: .txt was in the allowlist, in the frontend accept list and in the
    error message, but was routed to the image decoder. Every .txt upload died
    with a misleading 'No text could be extracted'."""
    result = extract(b"Name: John Smith\nDate: 12/05/2024\n", "note.txt")
    assert "John Smith" in result["entities"]["names"], result["entities"]


def test_every_pdf_page_is_read():
    """BUG: only page 0 was ever read, and anything longer than one page was
    rejected outright. The one real document in the repo was 7 pages."""
    data = make_pdf(["Alpha page one", "Beta page two", "Gamma page three"])
    result = extract(data, "multi.pdf")
    assert pages_of(result) == 3, f"3 pages in, {pages_of(result)} out"
    joined = " ".join(result["structure"])
    for word in ("Alpha", "Beta", "Gamma"):
        assert word in joined, f"page containing {word} was dropped"


def test_scanned_pdf_falls_back_to_ocr():
    """BUG: PDFs only ever went to the text-layer reader. A scanned PDF has no
    text layer, so it failed — even though OCR lived in the same file."""
    result = extract(make_scanned_pdf(["Invoice", "Name: Alice Brown"]), "scan.pdf")
    joined = " ".join(result["structure"])
    assert "Alice" in joined, joined[:200]


def test_full_month_names_are_dates():
    """BUG: the month pattern was (?:Jan|Feb|...) with no suffix, so it matched
    'Jan 5, 2024' but not 'January 5, 2024' — the commoner spelling."""
    dates = mod.extract_entities("Signed on January 5, 2024 in Hyderabad")["dates"]
    assert any("January" in d for d in dates), dates


def test_iso_dates_are_dates():
    """BUG: no pattern covered 2024-01-05, the format every export produces."""
    dates = mod.extract_entities("Created 2024-01-05 by the system")["dates"]
    assert "2024-01-05" in dates, dates


def test_output_order_is_deterministic():
    """BUG: list(set(...)) — Python randomises str hashing per process, so the
    same document returned differently ordered entities on every run, and no
    result could be diffed or regression-tested."""
    text = "Meeting on 01/02/2024 and 03/04/2024 and 05/06/2024 and 07/08/2024"
    first = mod.extract_entities(text)["dates"]
    assert first == sorted(first, key=text.index), \
        f"{first} is not in document order"


def test_prose_colons_are_not_table_rows():
    """BUG: any line containing ':' became a table row, so timestamps and
    ordinary sentences filled the table with junk."""
    text = ("12:30\n"
            "Note that the following applies to every applicant who has: read this\n"
            "Name: Bob Lee")
    found = tables(text)
    rows = found[0]["rows"] if found else []
    assert rows == [["Name", "Bob Lee"]], rows


def test_empty_document_raises():
    """Held from the original, which got this right: an unreadable file must
    raise, not return an empty result that looks like a clean extraction."""
    try:
        extract(b"   \n  \n", "blank.txt")
    except Exception:
        return
    raise AssertionError("empty document returned a result instead of raising")


def test_unsupported_type_says_so():
    """BUG: a .docx (or anything else) produced 'No text could be extracted',
    which blames the document instead of naming the real reason."""
    try:
        extract(b"PK\x03\x04nonsense", "report.docx")
    except Exception as e:
        assert "docx" in str(e).lower() or "supported" in str(e).lower(), str(e)
        return
    raise AssertionError("unsupported type was accepted")


def test_one_size_limit():
    """BUG: Flask allowed 16MB, the UI advertised 16MB, and the extractor
    rejected anything over 10MB — so a 12MB upload passed validation and then
    failed deep in extraction."""
    assert mod.MAX_BYTES == 16 * 1024 * 1024


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    print(f"running {len(TESTS)} tests against {MODULE}\n")
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as e:
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {type(e).__name__}: {e}")
            if not IS_ORIGINAL:
                traceback.print_exc()
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    if failed and not IS_ORIGINAL:
        raise SystemExit(1)
    if IS_ORIGINAL and not failed:
        raise SystemExit("the original passed every test — the suite proves nothing")


if __name__ == "__main__":
    main()
