# Results

Every number below comes from a command in this file, run on this machine: Windows 11, Python 3.12, Tesseract 5.x, `SEED = 42`, with 30 documents.

---

## 1. The test suite: old code vs. rebuilt code

```bash
cd backend

python test_extract.py
# rebuilt extractor

python test_extract.py original.data_extractor
# the version this replaced
```

| Target                                   |      Passed |
| ---------------------------------------- | ----------: |
| Rebuilt extractor                        | **10 / 10** |
| Original extractor (`backend/original/`) |  **1 / 10** |

The original code passes `test_empty_document_raises`. Refusing an unreadable document was already the correct behaviour, so that part was kept.

The other nine tests correspond to specific defects in the original:

| Test                                   | What the original did                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------- |
| `test_txt_is_actually_supported`       | `.txt` was advertised in three places but sent to the image decoder, so every upload failed |
| `test_every_pdf_page_is_read`          | Read only page 0 and rejected PDFs with more than one page                                  |
| `test_scanned_pdf_falls_back_to_ocr`   | PDFs only used the text layer, so scanned PDFs returned nothing                             |
| `test_full_month_names_are_dates`      | Matched `Jan 5, 2024` but not `January 5, 2024`                                             |
| `test_iso_dates_are_dates`             | Had no pattern for `2024-01-05`                                                             |
| `test_output_order_is_deterministic`   | Used `list(set(...))`, so the output order could change between runs                        |
| `test_prose_colons_are_not_table_rows` | Treated any line containing a colon as a table row, including timestamps                    |
| `test_unsupported_type_says_so`        | Reported a document extraction failure instead of identifying the unsupported file type     |
| `test_one_size_limit`                  | Flask allowed 16MB while the extractor rejected files over 10MB                             |

---

## 2. Extraction accuracy

```bash
cd backend

python bench.py
# default: en_core_web_sm

SPACY_MODEL=en_core_web_trf python bench.py
# transformer, for comparison
```

The benchmark uses 30 seeded synthetic forms. Each form is tested through all three input paths: a PDF with a text layer, the same page as a scanned PDF without a text layer, and the same page as a PNG.

### Default model: `en_core_web_sm`

| Path               | Field     | Recall | Precision |
| ------------------ | --------- | -----: | --------: |
| PDF (text layer)   | names     |   1.00 |      0.97 |
|                    | dates     |   1.00 |      1.00 |
|                    | addresses |   1.00 |      0.91 |
|                    | emails    |   1.00 |      1.00 |
|                    | phones    |   1.00 |      1.00 |
| PDF (scanned, OCR) | names     |   1.00 |      1.00 |
|                    | dates     |   1.00 |      1.00 |
|                    | addresses |   1.00 |      0.94 |
|                    | emails    |   1.00 |      1.00 |
|                    | phones    |   1.00 |      1.00 |
| PNG image (OCR)    | names     |   1.00 |      1.00 |
|                    | dates     |   1.00 |      1.00 |
|                    | addresses |   1.00 |      0.94 |
|                    | emails    |   1.00 |      1.00 |
|                    | phones    |   1.00 |      1.00 |

There were **0 extraction failures across 90 documents**.

Median latency was **0.016 s** for a PDF with a text layer, **0.74 s** for a PNG, and **0.93 s** for a scanned PDF.

### Why `en_core_web_sm` is the default

The original implementation preferred `en_core_web_trf` and fell back to `sm`. The two were measured side by side:

| Model             | Name precision | Address precision | Median s (PDF text) |
| ----------------- | -------------: | ----------------: | ------------------: |
| `en_core_web_sm`  |       **0.97** |              0.91 |           **0.016** |
| `en_core_web_trf` |           0.73 |          **1.00** |               0.114 |

The transformer finds every place name in this benchmark, but it also labels roughly a quarter of its person results incorrectly. It is about 7× slower and uses roughly 400MB more model memory.

For that reason, `sm` is the default. `SPACY_MODEL=en_core_web_trf` is still available when the transformer is preferred.

---

## 3. How to read these numbers

**The documents are synthetic.** `bench.py` generates them from a fixed word list, so every proper noun in the fixtures is ground truth and nothing outside that list appears. That makes the measured precision an **upper bound**. A real document containing company names, headings, chart labels, and other text will produce a lower precision score.

Recall is the more useful number here because it measures how often a field that is known to be present is actually found.

**The 1.00 recall is also partly a property of the fixtures.** The forms use labelled fields such as `Name:` and `City:`, which the regex layer can read directly.

When those labels are removed, recall depends on spaCy alone. For `addresses`, that produced a recall of only **0.10** before the labelled-field patterns were added. That was the largest measured improvement in this rebuild.

---

## 4. Where it still fails

The following command runs the extractor against the real seven-page document that was used during the original project. The old implementation rejected it outright:

```bash
cd backend

python data_extractor.py path/to/report.pdf
```

The rebuilt extractor gets **7/7 pages**, with 63 structural lines and 5 table rows.

There are still a few known problems:

* **Chart-heavy pages can produce junk names.** Pages dominated by figures may have only a thin text layer, causing them to fall through to OCR. OCR can turn axis labels and legends into fragments such as `Lr edterans` and `Hay 0h`, which spaCy may then classify as people. There is currently no filter for this. A confidence threshold or minimum dictionary-word ratio would be a reasonable next experiment.

* **`et al.` citations can become names.** `Wodzinski et al.` and `Alqahtani et al.` are returned as people. They are valid surnames, but they are not people fields in the context of a form-extraction tool.

* **`Kaggle` is returned as a person.** This appears to be a model limitation rather than a defect in the extraction code.

The date extractor returned nothing for this document, which is expected because the document contains no dates.
