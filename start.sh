#!/bin/bash
# Render start script
# Downloads tessdata on first run if needed

TESSDATA_DIR="${HOME}/.tessdata"
mkdir -p "${TESSDATA_DIR}"

# Download traineddata files if not present
if [ ! -f "${TESSDATA_DIR}/eng.traineddata" ]; then
    echo "Downloading eng.traineddata..."
    curl -sSL -o "${TESSDATA_DIR}/eng.traineddata" \
        "https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"
fi

if [ ! -f "${TESSDATA_DIR}/chi_tra.traineddata" ]; then
    echo "Downloading chi_tra.traineddata..."
    curl -sSL -o "${TESSDATA_DIR}/chi_tra.traineddata" \
        "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata"
fi

export TESSDATA_PREFIX="${TESSDATA_DIR}"

# Start with gunicorn
exec gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120
