"""Measure extraction accuracy on documents whose contents we know.

    python bench.py                     # default: en_core_web_sm
    SPACY_MODEL=en_core_web_trf python bench.py

Generates seeded synthetic forms, renders each one down all three input paths
(PDF with a text layer, scanned PDF with none, and a plain image), and scores
what came back against the values it put in.

Honest reading of these numbers, repeated in RESULTS.md: the documents are
synthetic and every proper noun in them is ground truth, so precision here is
an upper bound. Recall is the number worth trusting — it says how often a
field that is definitely present is actually found.
"""

import io
import json
import os
import random
import statistics
import sys
import time

import fitz
from PIL import Image

from data_extractor import extract

SEED = 42
N_DOCS = 30

FIRST = ["Ananya", "Rahul", "Priya", "Vikram", "Meera", "Arjun", "Kavya", "Rohit",
         "Sneha", "Karthik", "Divya", "Aditya", "Nisha", "Suresh", "Pooja"]
LAST = ["Sharma", "Reddy", "Nair", "Kapoor", "Menon", "Iyer", "Chopra", "Bose",
        "Rao", "Verma", "Joshi", "Patel", "Gupta", "Malhotra", "Sethi"]
CITIES = ["Hyderabad", "Bangalore", "Chennai", "Mumbai", "Pune", "Kolkata",
          "Delhi", "Jaipur", "Kochi", "Ahmedabad"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Filler that contains no proper nouns, so anything the extractor reports
# beyond the planted values is a genuine false positive.
FILLER = [
    "this form must be completed in full before it is submitted.",
    "please retain a copy of this document for your own records.",
    "any correction should be initialled in the margin of the page.",
    "processing usually takes between three and five working days.",
]


def make_document(rng):
    """Return (lines, truth) for one synthetic form."""
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    city = rng.choice(CITIES)
    day, month, year = rng.randint(1, 28), rng.randint(1, 12), rng.randint(2019, 2025)
    date_style = rng.choice(["slash", "iso", "long"])
    if date_style == "slash":
        date = f"{day:02d}/{month:02d}/{year}"
    elif date_style == "iso":
        date = f"{year}-{month:02d}-{day:02d}"
    else:
        date = f"{MONTHS[month - 1]} {day}, {year}"
    email = f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com"
    phone = f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}"

    lines = [
        "APPLICATION RECORD",
        "",
        f"Name: {name}",
        f"Date: {date}",
        f"City: {city}",
        f"Email: {email}",
        f"Phone: {phone}",
        "",
        rng.choice(FILLER),
        rng.choice(FILLER),
    ]
    truth = {"names": [name], "dates": [date], "addresses": [city],
             "emails": [email], "phones": [phone]}
    return lines, truth


def as_pdf(lines):
    doc = fitz.open()
    page = doc.new_page()
    y = 90
    for line in lines:
        if line:
            page.insert_text((72, y), line, fontsize=13, fontname="helv")
        y += 26
    data = doc.tobytes()
    doc.close()
    return data


def render(pdf_bytes, dpi=200):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.load_page(0).get_pixmap(dpi=dpi).tobytes("png")


def as_scanned_pdf(pdf_bytes):
    """Same page, but as a picture of itself — no text layer at all."""
    png = render(pdf_bytes)
    width, height = Image.open(io.BytesIO(png)).size
    doc = fitz.open()
    page = doc.new_page(width=width * 72 / 200, height=height * 72 / 200)
    page.insert_image(page.rect, stream=png)
    data = doc.tobytes()
    doc.close()
    return data


def score(found, expected):
    """A planted value counts as found if it appears inside any returned value.

    Substring rather than equality because OCR and NER legitimately return
    'Ananya Sharma' inside 'Ananya Sharma Date' style fragments; counting those
    as misses would measure formatting, not extraction.
    """
    hits = sum(1 for want in expected if any(want in got for got in found))
    matched = sum(1 for got in found if any(want in got for want in expected))
    return hits, len(expected), matched, len(found)


def run():
    rng = random.Random(SEED)
    docs = [make_document(rng) for _ in range(N_DOCS)]
    fields = ["names", "dates", "addresses", "emails", "phones"]
    paths = {
        "pdf_text":    lambda pdf: (pdf, "doc.pdf"),
        "pdf_scanned": lambda pdf: (as_scanned_pdf(pdf), "scan.pdf"),
        "image_png":   lambda pdf: (render(pdf), "scan.png"),
    }

    report = {"model": os.environ.get("SPACY_MODEL", "en_core_web_sm"),
              "seed": SEED, "documents": N_DOCS, "paths": {}}

    for path_name, build in paths.items():
        tally = {f: [0, 0, 0, 0] for f in fields}  # hits, expected, matched, returned
        times, failures = [], 0
        for lines, truth in docs:
            data, filename = build(as_pdf(lines))
            start = time.perf_counter()
            try:
                result = extract(data, filename)
            except Exception as e:
                failures += 1
                print(f"  {path_name}: extraction failed: {e}", file=sys.stderr)
                continue
            times.append(time.perf_counter() - start)
            for field in fields:
                got = result["entities"].get(field, [])
                for i, value in enumerate(score(got, truth[field])):
                    tally[field][i] += value

        report["paths"][path_name] = {
            "failures": failures,
            "median_seconds": round(statistics.median(times), 3) if times else None,
            "fields": {
                f: {
                    "recall": round(t[0] / t[1], 3) if t[1] else None,
                    "precision": round(t[2] / t[3], 3) if t[3] else None,
                    "returned": t[3],
                }
                for f, t in tally.items()
            },
        }
    return report


def main():
    report = run()
    print(json.dumps(report, indent=2))
    print(f"\n{'path':<13} {'field':<11} {'recall':>7} {'precision':>10} {'median s':>9}")
    for path_name, path in report["paths"].items():
        for field, s in path["fields"].items():
            print(f"{path_name:<13} {field:<11} {str(s['recall']):>7} "
                  f"{str(s['precision']):>10} {str(path['median_seconds']):>9}")


if __name__ == "__main__":
    main()
