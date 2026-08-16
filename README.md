# Document Data Extractor

Upload a PDF, a scan or a photo of a document and get back the names, dates,
places, emails, phone numbers and `Label: value` tables it contains, as JSON.

Flask + PyMuPDF + Tesseract + spaCy on the backend, React on the front.

**Measured on 30 seeded synthetic forms across all three input paths: recall
1.00 on every field, precision 0.91–1.00, 0 failures in 90 documents.**
Full numbers, method and known failures in [RESULTS.md](RESULTS.md).

---

## What it does

```
        PDF                     scan / photo              .txt
         │                           │                      │
   text layer?  ──no──►  render at 200 DPI ──► Tesseract    │
         │ yes                                    │         │
         ▼                                        ▼         ▼
                    list[str] — one string per page
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        regex fields         spaCy NER          Label: value
        dates, emails,      people, places        tables
        phones, labels
```

The rule the whole thing turns on:

> **`extract_pages(data, filename) -> list[str]`, one string per page, in
> order — and no input format is allowed to skip extraction because of its
> extension alone.**

Text comes from whatever the bytes actually hold. A PDF page with no text layer
is rendered and OCR'd; a PDF with 40 pages returns 40 strings. Uploads are held
in memory and never written to disk.

---

## Running it

**Prerequisites:** Python 3.10+, Node 18+, and the
[Tesseract OCR binary](https://github.com/UB-Mannheim/tesseract/wiki) on your
`PATH`.

```bash
# backend
cd backend
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python app.py                       # http://127.0.0.1:5000

# frontend, in a second terminal
cd frontend
npm install
npm start                           # http://localhost:3000
```

Or skip the server entirely:

```bash
cd backend
python data_extractor.py invoice.pdf     # prints the JSON
```

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5000` | bind address |
| `FLASK_DEBUG` | off | `1` enables the Werkzeug debugger — never in production |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated allowed origins |
| `SPACY_MODEL` | `en_core_web_sm` | `en_core_web_trf` for the transformer |
| `REACT_APP_API_URL` | `http://127.0.0.1:5000` | backend the UI talks to |

### API

```
GET  /health   → {status, max_bytes, formats}
POST /upload   multipart form-data, field name "file"
               → 200 {success, filename, data:{page_count, entities, structure, tables}}
               → 400 anything the caller can fix (wrong type, too big, no text)
               → 413 over 16MB
               → 500 anything else
```

Supported: `pdf png jpg jpeg gif bmp tiff txt`, up to 16MB.

---

## Tests

```bash
cd backend
python test_extract.py                          # 10/10
python test_extract.py original.data_extractor  # 1/10
```

Plain asserts, no pytest, no network, about two seconds. Each test is named
after a defect found in the original, and the second command is the proof the
suite is worth having — the code it replaced fails nine of them.

---

## What was wrong before

The previous version ran without ever raising an error, and did not work.

`data_extraction()` chose its strategy from the file extension and hard-coded
exactly one strategy per extension. That single decision produced most of the
failures:

- **`.txt` was accepted and could never succeed.** It was in the backend
  allowlist, in the frontend `accept` attribute and in the error message, and
  it was routed to `cv2.imread`, which cannot read text files. Every `.txt`
  upload died with `No text could be extracted from the file` — an error that
  blames the document.
- **Scanned PDFs failed the same way.** PDFs only ever went to the text-layer
  reader, so a scan came back empty, even though OCR was in the same module.
- **Multi-page PDFs were refused outright.** The one real document in the repo
  was 7 pages.
- **Every failure returned the same message**, so these were indistinguishable.

A second root cause sat in `clean_ocr_text`, which collapsed *all* whitespace
including newlines. A form became one run-on line, which caused two more
failures at once: the `Name:` regex ran past the end of its own field and
captured `John Smith Date`, and spaCy — which uses line breaks as sentence
boundaries — returned `Vikram Bose Date` as a person.

The rest, each now covered by a test: `list(set(...))` made output order change
between runs; the month pattern matched `Jan` but not `January`; there was no
ISO date pattern; every line containing a colon became a table row, timestamps
included; and the size limit was 16MB in Flask and 10MB in the extractor, so a
12MB file passed validation and then failed deep in extraction.

Also fixed, not correctness but worth naming: `debug=True` with a `0.0.0.0`
bind shipped the Werkzeug console to the local network, `CORS(app)` allowed
every origin, and a hardcoded `SECRET_KEY` sat in the source for a feature the
app never used. Uploads were saved to `static/files/`, deleted afterwards and
swept hourly — three moving parts undoing each other, which still left a user's
document in the repo when extraction raised. Nothing is written to disk now.

`opencv-python` was dropped: Pillow ships with `pytesseract` and does
everything the image path needed.

The original extractor is preserved in `backend/original/` as the record of all
of this, and as the target the test suite runs against.
