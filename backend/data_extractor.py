import os
import re
from typing import Dict, Any, List
import cv2
import pytesseract
import fitz  # PyMuPDF
# Try to load a better spaCy model
try:
    import spacy
    nlp = spacy.load("en_core_web_trf")  # Transformer model
except OSError:
    print("Transformer model not found, falling back to en_core_web_sm. For better accuracy, run:")
    print("python -m spacy download en_core_web_trf")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("Error: spaCy model 'en_core_web_sm' not found. Install it with:")
        print("python -m spacy download en_core_web_sm")
        nlp = None

def clean_ocr_text(text: str) -> str:
    """Clean OCR text to improve NER performance."""
    text = re.sub(r'-\s*\n', '', text)  # Fix hyphenation across lines
    text = re.sub(r'\s+', ' ', text)    # Collapse multiple spaces/newlines
    return text.strip()

def ocr_extract_text(image_path: str) -> str:
    """Extract text from an image using OpenCV and Pytesseract."""
    try:
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not read image file: {image_path}")
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(
            gray_image,
            config="--psm 6"  # Assume uniform block of text
        )
        return text.strip()
    except Exception as e:
        print(f"Error in OCR extraction: {e}")
        return ""

def extract_tables_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract tables from text using pattern matching."""
    tables = []
    lines = text.split("\n")
    potential_table_lines = []
    for line in lines:
        line = line.strip()
        if line and ':' in line:
            potential_table_lines.append(line)
    if potential_table_lines:
        headers = ["Field", "Value"]
        rows = []
        for line in potential_table_lines:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                rows.append([key, value])
        if rows:
            tables.append({"headers": headers, "rows": rows})
    return tables

def extract_names_with_regex(text: str) -> List[str]:
    """Extract probable names using regex patterns."""
    patterns = [
        r'Name\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'Mr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'Ms\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
    ]
    names = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        names.extend(matches)
    return names

def extract_entities(text: str) -> Dict[str, List[str]]:
    """Extract entities from text using spaCy and regex patterns."""
    entities = {"names": [], "dates": [], "addresses": []}
    cleaned_text = clean_ocr_text(text)
    date_patterns = [
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',
        r'\b\d{1,2}-\d{1,2}-\d{4}\b',
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b',
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b'
    ]
    for pattern in date_patterns:
        matches = re.findall(pattern, cleaned_text, re.IGNORECASE)
        entities["dates"].extend(matches)
    entities["dates"] = list(set(entities["dates"]))
    if nlp:
        try:
            doc = nlp(cleaned_text)
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    entities["names"].append(ent.text)
                elif ent.label_ in ["GPE", "LOC", "FAC"]:
                    entities["addresses"].append(ent.text)
        except Exception as e:
            print(f"Error in spaCy processing: {e}")
    regex_names = extract_names_with_regex(cleaned_text)
    entities["names"].extend(regex_names)
    entities["names"] = list(set(entities["names"]))
    entities["addresses"] = list(set(entities["addresses"]))
    return entities

def data_extraction(file_path: str) -> Dict[str, Any]:
    """Extract data from a PDF or image file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if os.path.getsize(file_path) > 10 * 1024 * 1024:
        raise ValueError("File size exceeds 10MB")
    text = ""
    try:
        if file_path.lower().endswith(".pdf"):
            doc = fitz.open(file_path)
            if doc.page_count > 1:
                raise ValueError("Only single-page PDFs are supported")
            page = doc.load_page(0)
            text = page.get_text()
            doc.close()
        else:
            text = ocr_extract_text(file_path)
    except Exception as e:
        raise RuntimeError(f"Error processing file: {e}")
    if not text.strip():
        raise ValueError("No text could be extracted from the file")
    tables = extract_tables_from_text(text)
    entities = extract_entities(text)
    lines = text.split("\n")
    structure = [line.strip() for line in lines if line.strip()]
    return {
        "entities": entities,
        "structure": structure,
        "tables": tables
    }

def main():
    """Example usage with error handling."""
    file_path = "path_to_your_file.pdf"  # Update this path
    try:
        result = data_extraction(file_path)
        print("=== EXTRACTION RESULTS ===")
        print(f"Entities found: {len(result['entities']['names'])} names, "
              f"{len(result['entities']['dates'])} dates, "
              f"{len(result['entities']['addresses'])} addresses")
        print(f"\nStructure: {len(result['structure'])} lines")
        print(f"Tables: {len(result['tables'])} found")
        from pprint import pprint
        pprint(result)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
