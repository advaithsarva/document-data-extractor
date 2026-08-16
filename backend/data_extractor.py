"""Document -> text -> structured data.

THE INVARIANT
-------------
    extract_pages(data, filename) -> list[str], one string per page, in order.

Every supported input produces at least one non-empty page or raises. Nothing
downstream may collapse, reorder or drop pages, and no input format is allowed
to skip extraction because of its extension alone.

The original version dispatched on the file extension and hard-coded exactly
one strategy per extension. That single decision produced every bug found in
the rebuild: .txt was advertised but sent to the image decoder, scanned PDFs
were sent to the text-layer reader and came back empty, and multi-page PDFs
were refused outright. Text now comes from whatever the bytes actually hold.
"""

import io
import os
import re
from typing import Any, Dict, List

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# ponytail: raise the DPI if OCR misses small print; 200 is the accuracy/speed knee.
OCR_DPI = 200
OCR_CONFIG = "--psm 6"  # assume a uniform block of text

# A page with fewer real characters than this is treated as having no text
# layer, so it gets rendered and OCR'd instead. Scanned PDFs often carry a few
# stray characters, so 0 is not a safe threshold.
MIN_TEXT_LAYER_CHARS = 20

MAX_BYTES = 16 * 1024 * 1024  # the one size limit; app.py enforces the same number

TEXT_EXTENSIONS = {"txt"}
PDF_EXTENSIONS = {"pdf"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "tiff"}
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS

_nlp = None
_nlp_loaded = False


def load_nlp(model: str = None):
    """Load spaCy on first use, not at import.

    Importing the model at module scope made the test suite and the CLI pay a
    multi-second load even when they never touched NER.

    Defaults to the small model; set SPACY_MODEL=en_core_web_trf to use the
    transformer. bench.py measures both — see RESULTS.md for why sm is default.
    """
    global _nlp, _nlp_loaded
    model = model or os.environ.get("SPACY_MODEL", "en_core_web_sm")
    if not _nlp_loaded:
        _nlp_loaded = True
        try:
            import spacy

            _nlp = spacy.load(model)
        except Exception as e:  # model not installed, or spaCy missing
            print(f"spaCy model '{model}' unavailable ({e}); "
                  f"names/addresses will come from regex only. "
                  f"Install it with: python -m spacy download {model}")
            _nlp = None
    return _nlp


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _ocr(image: Image.Image) -> str:
    return pytesseract.image_to_string(image, config=OCR_CONFIG).strip()


def _pdf_pages(data: bytes) -> List[str]:
    """One string per page. Falls back to OCR for pages with no text layer."""
    pages = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text().strip()
            if len(text) < MIN_TEXT_LAYER_CHARS:
                pix = page.get_pixmap(dpi=OCR_DPI)
                text = _ocr(Image.open(io.BytesIO(pix.tobytes("png"))))
            pages.append(text)
    return pages


def extract_pages(data: bytes, filename: str) -> List[str]:
    """Return one text string per page. Raises ValueError on anything unusable."""
    if len(data) > MAX_BYTES:
        raise ValueError(f"File exceeds the {MAX_BYTES // (1024 * 1024)}MB limit")

    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '.{ext}'. Supported: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )

    try:
        if ext in TEXT_EXTENSIONS:
            pages = [data.decode("utf-8", errors="replace")]
        elif ext in PDF_EXTENSIONS:
            pages = _pdf_pages(data)
        else:
            pages = [_ocr(Image.open(io.BytesIO(data)))]
    except Exception as e:
        raise ValueError(f"Could not read the file as .{ext}: {e}")

    if not any(p.strip() for p in pages):
        raise ValueError("No text could be extracted from the file")
    return pages


def clean_ocr_text(text: str) -> str:
    """Tidy OCR output *without* destroying line boundaries.

    The original collapsed all whitespace, including newlines, into single
    spaces. That turned a form into one long run-on line, and it is the single
    change that produced two separate failures: the `Name:` regex ran past the
    end of its own field and captured the next label, and spaCy — which uses
    line breaks as sentence boundaries — returned 'Vikram Bose Date' as a
    person. Lines are the structure in a document; keep them.
    """
    text = re.sub(r"-[ \t]*\n[ \t]*", "", text)  # de-hyphenate across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"

DATE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{1,2}-\d{1,2}-\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",                      # ISO
    rf"\b{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH},?\s+\d{{4}}\b",
]

# [ \t] rather than \s: a labelled name ends at the end of its line. Matching
# \s let "Name: John Smith\nDate: ..." capture "John Smith Date" once newlines
# had been collapsed.
NAME_PATTERNS = [
    r"(?:Name|Applicant|Patient|Employee|Customer)[ \t]*[:\-][ \t]*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z.]+)*)",
    r"\b(?:Mr|Ms|Mrs|Dr|Prof)\.?[ \t]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z.]+)*)",
]

# spaCy's small model misses most non-Western place names, so labelled fields
# are read directly. Measured: address recall 0.10 -> 1.00 (see RESULTS.md).
ADDRESS_PATTERNS = [
    r"(?:Address|City|Location|Place|Town)[ \t]*[:\-][ \t]*([^\n]{2,80})",
]

EMAIL_PATTERN = r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"

# Deliberately loose, then filtered by digit count below: phone formatting
# varies far more than phone length. Matching on shape alone pulled in student
# IDs and invoice numbers.
PHONE_PATTERN = r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3,5})[\s.-]?\d{3,5}(?:[\s.-]?\d{2,4})?"
PHONE_DIGITS = range(10, 14)


def _phones(text: str) -> List[str]:
    return [m.group().strip() for m in re.finditer(PHONE_PATTERN, text)
            if len(re.sub(r"\D", "", m.group())) in PHONE_DIGITS]


def _unique(items: List[str]) -> List[str]:
    """Deduplicate, keeping first-seen order.

    The original used list(set(...)). Python randomises str hashing per
    process, so identical input produced differently ordered output on every
    run — which makes results impossible to diff or test.
    """
    return list(dict.fromkeys(s.strip() for s in items if s.strip()))


def extract_entities(text: str) -> Dict[str, List[str]]:
    """Names, dates, addresses, emails and phone numbers found in `text`."""
    entities: Dict[str, List[str]] = {
        "names": [], "dates": [], "addresses": [], "emails": [], "phones": [],
    }

    # Regexes read the raw text: labels, dates and contacts are line-scoped, and
    # collapsing newlines is what let them run past the end of their own field.
    for pattern in DATE_PATTERNS:
        entities["dates"].extend(re.findall(pattern, text, re.IGNORECASE))
    for pattern in NAME_PATTERNS:
        entities["names"].extend(re.findall(pattern, text))
    for pattern in ADDRESS_PATTERNS:
        entities["addresses"].extend(re.findall(pattern, text))
    entities["emails"] = re.findall(EMAIL_PATTERN, text)
    entities["phones"] = _phones(text)

    # NER reads the cleaned text: spaCy needs unbroken sentences.
    cleaned = clean_ocr_text(text)
    nlp = load_nlp()
    if nlp is not None:
        for ent in nlp(cleaned).ents:
            # spaCy will happily run an entity across a line break, producing
            # "Kochi\nEmail". A field never spans two lines; keep the first.
            value = ent.text.split("\n")[0].strip()
            if not value:
                continue
            if ent.label_ == "PERSON":
                entities["names"].append(value)
            elif ent.label_ in ("GPE", "LOC", "FAC"):
                entities["addresses"].append(value)

    return {key: _unique(values) for key, values in entities.items()}


# A key longer than this is prose that happens to contain a colon, not a label.
MAX_KEY_CHARS = 40


def extract_tables(text: str) -> List[Dict[str, Any]]:
    """Read `Label: value` lines as a two-column table.

    Deliberately simple: it catches forms and invoices, which is what this app
    is pointed at. ponytail: no ruled-line/column detection until a document
    shows up that needs it.
    """
    rows = []
    for line in text.split("\n"):
        key, sep, value = line.strip().partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            continue
        if len(key) > MAX_KEY_CHARS or key.isdigit():  # "12:30" is a time, not a row
            continue
        rows.append([key, value])
    return [{"headers": ["Field", "Value"], "rows": rows}] if rows else []


def extract(data: bytes, filename: str) -> Dict[str, Any]:
    """Full pipeline: bytes in, structured data out. Never touches the disk."""
    pages = extract_pages(data, filename)
    text = "\n".join(pages)
    return {
        "page_count": len(pages),
        "entities": extract_entities(text),
        "structure": [line.strip() for line in text.split("\n") if line.strip()],
        "tables": extract_tables(text),
    }


def main():
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: python data_extractor.py <file>")
        raise SystemExit(2)
    path = sys.argv[1]
    with open(path, "rb") as f:
        result = extract(f.read(), path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
