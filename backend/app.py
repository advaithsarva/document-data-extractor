"""HTTP wrapper around data_extractor.extract.

Uploads are held in memory and never written to disk. The original saved every
upload to static/files/, deleted it afterwards, and swept the folder for files
older than an hour — three moving parts whose only job was to undo each other,
and which still left a user's document sitting in the repo when extraction
raised. Nothing to clean up if nothing is written.
"""

import logging
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

from data_extractor import ALLOWED_EXTENSIONS, MAX_BYTES, extract

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES

# Only the dev frontend by default. Set CORS_ORIGINS="https://your.app" to deploy.
CORS(app, origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","))


@app.get("/health")
def health():
    return jsonify({"status": "ok", "max_bytes": MAX_BYTES,
                    "formats": sorted(ALLOWED_EXTENSIONS)})


@app.post("/upload")
def upload_file():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        data = extract(file.read(), file.filename)
    except ValueError as e:
        # Everything the caller can fix: wrong type, too big, no text in it.
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Extraction failed for %s", file.filename)
        return jsonify({"error": f"Error processing file: {e}"}), 500

    return jsonify({"success": True, "filename": file.filename, "data": data})


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File too large. Maximum size is "
                             f"{MAX_BYTES // (1024 * 1024)}MB"}), 413


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


if __name__ == "__main__":
    # debug=True exposes the Werkzeug console; never on by default, and never
    # together with the 0.0.0.0 bind the original shipped with.
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
