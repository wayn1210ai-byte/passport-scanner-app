import os
import sys

# Patch: TESSDATA_PREFIX setup before any tesserocr import
_TESSDATA = os.path.expanduser('~/.tessdata')
os.environ.setdefault('TESSDATA_PREFIX', _TESSDATA)

# Ensure tessdata exists (will be downloaded on first OCR run)
os.makedirs(_TESSDATA, exist_ok=True)

"""
Passport Scanner App - Flask Backend
Scan passport photos, extract data, save to Google Sheets
"""

import json
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from passport_ocr import PassportOCR
from google_sheets import GoogleSheetsWriter

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'passport-scanner-secret-2026')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

ocr_engine = PassportOCR()
sheets_writer = GoogleSheetsWriter()


@app.route('/')
def index():
    """Main page with upload and camera capture."""
    sheet_ok = sheets_writer.is_connected()
    if not sheet_ok:
        sheet_ok = sheets_writer.connect()
    return render_template('index.html', sheet_ok=sheet_ok)


@app.route('/scan', methods=['POST'])
def scan():
    """Handle image upload and process passport OCR."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Empty file'}), 400

    filename = secure_filename(file.filename)
    if not filename:
        filename = 'passport_scan.png'
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(filepath)

    try:
        app.logger.info(f"Processing: {filepath}")
        result = ocr_engine.extract(filepath)

        # Write to Google Sheets if connected
        sheet_written = False
        if result['success'] and sheets_writer.connect():
            try:
                mrz_data = result.get('mrz_data') or {}
                mrz_lines = mrz_data.get('lines') if mrz_data else None
                sheet_written = sheets_writer.append_record(
                    fields=result['fields'],
                    mrz_data=mrz_data,
                    raw_text=result.get('raw_text', ''),
                    mrz_lines=mrz_lines
                )
            except Exception as e:
                app.logger.error(f"Sheet write error: {e}")
                sheet_written = False

        return jsonify({
            'success': result['success'],
            'fields': result.get('fields', {}),
            'mrz_data': result.get('mrz_data'),
            'visual_zone': result.get('visual_zone', {}),
            'raw_text': result.get('raw_text', '')[:500],
            'sheet_written': sheet_written,
            'error': result.get('error')
        })

    except Exception as e:
        app.logger.error(f"Scan error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass


@app.route('/records')
def records():
    """View recent scan records."""
    try:
        all_records = sheets_writer.get_all_records(limit=50)
        return render_template('records.html', records=all_records,
                             count=len(all_records))
    except Exception as e:
        return render_template('records.html', records=[], count=0, error=str(e))


@app.route('/setup')
def setup_guide():
    """Setup guide for Google Sheets."""
    return render_template('setup.html')


@app.route('/api/health')
def health():
    """Health check endpoint."""
    sheet_ok = sheets_writer.connect() if sheets_writer else False
    return jsonify({
        'status': 'ok',
        'google_sheets': sheet_ok,
        'tesseract': True,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
