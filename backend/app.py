from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime
from flask_cors import CORS  # Import CORS from flask_cors

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'static/files'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff'}

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_files():
    """Clean up old uploaded files to prevent storage issues."""
    try:
        upload_folder = app.config['UPLOAD_FOLDER']
        current_time = datetime.now().timestamp()

        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path):
                file_time = os.path.getmtime(file_path)
                # Remove files older than 1 hour
                if current_time - file_time > 3600:
                    os.remove(file_path)
                    logger.info(f"Removed old file: {filename}")
    except Exception as e:
        logger.error(f"Error cleaning up files: {e}")

@app.route('/upload', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        try:
            # Check if file is in request
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400

            file = request.files['file']

            # Check if file was selected
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            # Check if file type is allowed
            if not allowed_file(file.filename):
                return jsonify({'error': 'File type not allowed. Supported formats: PDF, PNG, JPG, JPEG, GIF, BMP, TIFF'}), 400

            if file:
                # Clean up old files periodically
                cleanup_old_files()

                # Secure the filename
                filename = secure_filename(file.filename)

                # Add timestamp to avoid conflicts
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{timestamp}{ext}"

                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # Save the file
                file.save(file_path)
                logger.info(f"File saved: {filename}")

                # Import and call the data extraction function
                try:
                    from data_extractor import data_extraction
                    result = data_extraction(file_path)

                    # Clean up the uploaded file after processing
                    try:
                        os.remove(file_path)
                        logger.info(f"Cleaned up file: {filename}")
                    except Exception as e:
                        logger.warning(f"Could not clean up file {filename}: {e}")

                    return jsonify({
                        'success': True,
                        'filename': filename,
                        'data': result
                    })

                except ImportError as e:
                    logger.error(f"Could not import data_extractor: {e}")
                    return jsonify({'error': 'Data extraction module not found'}), 500

                except Exception as e:
                    logger.error(f"Error during data extraction: {e}")
                    # Clean up file on error
                    try:
                        os.remove(file_path)
                    except:
                        pass
                    return jsonify({'error': f'Error processing file: {str(e)}'}), 500

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return jsonify({'error': 'An unexpected error occurred'}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
