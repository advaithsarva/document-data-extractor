# Document Data Extractor

Upload a PDF, scan, photo, or text document and get back the names, dates, places, emails, phone numbers, and `Label: value` tables found in it as JSON.

The backend uses Flask, PyMuPDF, Tesseract, and spaCy. The frontend is built with React.

**Measured on 30 seeded synthetic forms across all three input paths: recall was 1.00 for every field, precision ranged from 0.91–1.00, and there were 0 failures across 90 documents.**

See [RESULTS.md](RESULTS.md) for the complete measurements, test method, and known failures.

---

## What it does

```text
        PDF                  scan / photo                 .txt
         │                        │                         │
   text layer? ──no──► render at 200 DPI ──► Tesseract      │
         │ yes                    │                         │
         ▼                        ▼                         ▼
                  list[str] — one string per page
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       regex fields       spaCy NER        Label: value
       dates, emails,     people, places      tables
       phones, labels
```

The key rule is:

> **`extract_pages(data, filename) -> list[str]` returns one string per page, in order. No input format is allowed to skip extraction just because of its file extension.**

The extractor uses the content actually present in the uploaded bytes. A PDF with a text layer is read directly. A PDF without one is rendered and passed through OCR. A 40-page PDF produces 40 page strings.

Uploads stay in memory and are never written to disk.

---

## Running it

**Prerequisites:** Python 3.10+, Node 18+, and the [Tesseract OCR binary](https://github.com/UB-Mannheim/tesseract/wiki) available on your `PATH`.

```bash
# backend
cd backend
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python app.py                       # http://127.0.0.1:5000

# frontend, in a second terminal
cd frontend
npm install
npm start                            # http://localhost:3000
```

You can also run the extractor without starting the server:

```bash
cd backend
python data_extractor.py invoice.pdf     # prints the JSON
```

### Configuration

| Variable            | Default                 | Purpose                                                          |
| ------------------- | ----------------------- | ---------------------------------------------------------------- |
| `HOST` / `PORT`     | `127.0.0.1` / `5000`    | Bind address                                                     |
| `FLASK_DEBUG`       | off                     | `1` enables the Werkzeug debugger — never use this in production |
| `CORS_ORIGINS`      | `http://localhost:3000` | Comma-separated list of allowed origins                          |
| `SPACY_MODEL`       | `en_core_web_sm`        | Set to `en_core_web_trf` to use the transformer model            |
| `REACT_APP_API_URL` | `http://127.0.0.1:5000` | Backend URL used by the UI                                       |

### API

```text
GET  /health
     → {status, max_bytes, formats}

POST /upload
     multipart form-data, field name "file"

     → 200 {success, filename, data:{page_count, entities, structure, tables}}
     → 400 anything the caller can fix (wrong type, too big, no text)
     → 413 over 16MB
     → 500 anything else
```

Supported formats: `pdf`, `png`, `jpg`, `jpeg`, `gif`, `bmp`, `tiff`, and `txt`. Maximum upload size is 16MB.

---

## Tests

```bash
cd backend

python test_extract.py
# 10/10

python test_extract.py original.data_extractor
# 1/10
```

The tests use plain asserts rather than pytest. They make no network requests and take about two seconds to run.

Each test corresponds to a defect found in the original implementation. The second command runs the same suite against the original extractor. It fails nine of the ten tests, which is why the suite is useful beyond simply checking that the new code runs.

---

## What was wrong before

The previous version ran without raising errors, but the extraction itself did not work correctly.

`data_extraction()` selected its strategy from the file extension and assigned one fixed strategy to each extension. Most of the failures came from that decision.

* **`.txt` files were accepted but could never succeed.** They appeared in the backend allowlist, the frontend `accept` attribute, and the error message, but the extractor sent them to `cv2.imread`, which cannot read text files. Every `.txt` upload ended with `No text could be extracted from the file`, making the error look like a problem with the document.

* **Scanned PDFs failed for the same basic reason.** PDFs were always sent to the text-layer reader. A scanned PDF therefore returned no text, even though OCR support already existed in the module.

* **Multi-page PDFs were rejected.** The only actual document in the repository was seven pages long.

* **Every failure returned the same error message.** There was no way to tell these different failure cases apart.

There was another problem in `clean_ocr_text`. It collapsed all whitespace, including newlines. That turned a form into one continuous line and caused two additional failures. The `Name:` regex could run past the end of its field and capture `John Smith Date`. spaCy also uses line breaks as sentence boundaries, so removing them caused `Vikram Bose Date` to be returned as a person.

The remaining defects are each covered by a test:

* `list(set(...))` made the output order change between runs.
* The month pattern matched `Jan` but not `January`.
* There was no ISO date pattern.
* Every line containing a colon was treated as a table row, including timestamps.
* Flask enforced a 16MB size limit while the extractor enforced 10MB. A 12MB file could therefore pass the first check and fail later during extraction.

A few non-correctness issues were fixed as well. `debug=True` combined with a `0.0.0.0` bind exposed the Werkzeug console to the local network. `CORS(app)` allowed requests from any origin. A hardcoded `SECRET_KEY` was also present in the source even though the application never used the feature that required it.

Uploads were previously saved under `static/files/`, deleted afterward, and swept hourly. Those mechanisms overlapped without solving the underlying problem: if extraction raised an exception, a user's document could still remain in the repository.

Uploads now stay entirely in memory and are never written to disk.

`opencv-python` was also removed. Pillow, which is already used with `pytesseract`, provides everything required by the image-processing path.

The original extractor remains in `backend/original/`. It serves as a record of the previous implementation and as the target used by the test suite for regression comparison.
