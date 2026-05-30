"""
Passport OCR Engine
- Uses tesserocr (bundled Tesseract C library) for OCR
- Manual MRZ detection and parsing (no passporteye dependency)
- Supports both visual zone and MRZ zone extraction
"""

import re
import os
import cv2
import numpy as np
from datetime import datetime


# Set tessdata path for tesserocr
_TESSDATA_DIR = os.path.expanduser('~/.tessdata')
os.environ.setdefault('TESSDATA_PREFIX', _TESSDATA_DIR)

from tesserocr import PyTessBaseAPI, PSM, OEM


class PassportOCR:
    """Extract passport data from an image using tesserocr."""

    def __init__(self, lang='chi_tra+eng'):
        self.lang = lang
        self._ensure_tessdata()

    def _ensure_tessdata(self):
        """Ensure tessdata directory exists."""
        if not os.path.exists(_TESSDATA_DIR):
            os.makedirs(_TESSDATA_DIR, exist_ok=True)

        # Check at least eng.traineddata exists
        eng_path = os.path.join(_TESSDATA_DIR, 'eng.traineddata')
        if not os.path.exists(eng_path):
            import urllib.request
            print("Downloading eng.traineddata...")
            url = 'https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata'
            urllib.request.urlretrieve(url, eng_path)

        # Check chi_tra
        chi_path = os.path.join(_TESSDATA_DIR, 'chi_tra.traineddata')
        if not os.path.exists(chi_path):
            import urllib.request
            print("Downloading chi_tra.traineddata...")
            url = 'https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata'
            urllib.request.urlretrieve(url, chi_path)

    def extract(self, image_path: str) -> dict:
        """
        Extract passport data from image.
        Returns dict with all recognized fields.
        """
        img = cv2.imread(str(image_path))
        if img is None:
            return {'error': 'Could not read image file'}

        result = {
            'success': False,
            'mrz_data': None,
            'visual_zone': {},
            'raw_text': '',
            'fields': {}
        }

        # Step 1: Pre-process image
        processed = self._preprocess(img)

        # Step 2: Extract MRZ from bottom portion
        mrz_data, mrz_text = self._extract_mrz(img, processed)
        if mrz_data:
            result['mrz_data'] = mrz_data
            result['fields'].update(self._mrz_to_fields(mrz_data))

        # Step 3: Extract visual zone text
        visual_text = self._extract_visual_zone(processed)
        result['raw_text'] = mrz_text + '\n' + visual_text
        visual_fields = self._parse_visual_zone(visual_text)
        result['visual_zone'] = visual_fields

        # Merge fields (MRZ is more reliable, don't override with visual)
        for k, v in visual_fields.items():
            if k not in result['fields'] or not result['fields'].get(k):
                result['fields'][k] = v

        result['success'] = bool(result['fields'])
        return result

    def _preprocess(self, img):
        """Pre-process image for better OCR."""
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, h=10)

        # Adaptive threshold
        binary = cv2.adaptiveThreshold(
            denoised, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31, C=10
        )

        # Deskew
        coords = np.column_stack(np.where(binary > 0))
        if len(coords) > 100:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) > 0.5:
                h, w = binary.shape
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                binary = cv2.warpAffine(
                    binary, M, (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE
                )

        # Resize for better OCR
        h, w = binary.shape
        if h < 1200:
            scale = 1400 / h
            binary = cv2.resize(binary, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_CUBIC)

        return binary

    def _extract_mrz(self, img, processed):
        """
        Extract MRZ from the bottom portion of the passport image.
        Uses tesserocr with MRZ-specific settings.
        """
        h, w = processed.shape

        # Try multiple crop ratios for the MRZ zone (bottom of passport)
        for bottom_ratio in [0.55, 0.50, 0.45, 0.40]:
            bottom_crop = int(h * bottom_ratio)
            mrz_region = processed[bottom_crop:h, :]

            temp_path = '/tmp/_mrz_region.png'
            cv2.imwrite(temp_path, mrz_region)

            try:
                # OCR with MRZ-optimized settings
                with PyTessBaseAPI(lang='eng', psm=PSM.SINGLE_BLOCK,
                                   oem=OEM.LSTM_ONLY) as api:
                    api.SetImageFile(temp_path)
                    # Only allow characters valid in MRZ
                    api.SetVariable('tessedit_char_whitelist',
                                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<')
                    text = api.GetUTF8Text().strip()

                # Look for 2-line MRZ pattern
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                mrz_lines = [l for l in lines if len(l) >= 40 and '<' in l]

                if len(mrz_lines) >= 2:
                    mrz_text = '\n'.join(mrz_lines[:2])
                    parsed = self._parse_mrz_lines(mrz_lines[0], mrz_lines[1])
                    if parsed:
                        parsed['lines'] = mrz_lines[:2]
                        return parsed, mrz_text

            except Exception:
                pass

        return None, ''

    def _parse_mrz_lines(self, line1, line2):
        """
        Parse ICAO 9303 standard MRZ lines (TD3 format).
        Line 1: P<ISSUER<SURNAME<<GIVEN<NAMES<<<<<
        Line 2: PASSPORT_NO<ISSUER<BIRTH_DATE<SEX<EXPIRY_DATE<<<NATIONALITY<<<
        """
        try:
            result = {}

            # Line 1 parsing: P<COUNTRY<SURNAME<<GIVEN<<NAMES...
            # Type
            result['type'] = line1[0] if len(line1) > 0 else ''

            # Country / Issuer (chars 2-5)
            result['country'] = line1[2:5] if len(line1) > 5 else ''

            # Name: everything after first < until the filler <s
            name_part = line1[5:] if len(line1) > 5 else ''
            # Split by << which separates surname from given names
            name_parts = [p for p in re.split(r'<{2,}', name_part) if p.strip('<>')]
            if name_parts:
                # First part is surname, rest are given names
                result['surname'] = name_parts[0].strip('<')
                if len(name_parts) > 1:
                    given_parts = [p.strip('<') for p in name_parts[1:]]
                    result['names'] = ' '.join(given_parts)

            # Line 2 parsing
            if len(line2) >= 44:
                # Passport number (chars 0-8)
                pn = line2[0:9].strip('<')
                result['passport_number'] = pn

                # Issuer / Nationality - different MRZ versions handle differently
                # Check digit for passport number (char 9)
                # Nationality (chars 10-12)
                result['nationality'] = line2[10:13].strip('<')

                # Date of birth (chars 13-18, YYMMDD)
                bd = line2[13:19]
                if len(bd) == 6 and bd[:3].isdigit():
                    result['birth_date_raw'] = bd
                    yy, mm, dd = bd[:2], bd[2:4], bd[4:6]
                    # 出生日期：YY>目前年→19XX（不可能未來出生），否則20XX
                    yyyy = '19' + yy if int(yy) > 26 else '20' + yy
                    if mm.isdigit() and dd.isdigit():
                        result['birth_date'] = f'{yyyy}-{mm}-{dd}'

                # Check digit for DOB (char 19)
                # Sex (char 20)
                result['sex'] = line2[20] if len(line2) > 20 else ''

                # Expiry date (chars 21-26, YYMMDD)
                ed = line2[21:27]
                if len(ed) == 6 and ed[:3].isdigit():
                    result['expiry_raw'] = ed
                    yy, mm, dd = ed[:2], ed[2:4], ed[4:6]
                    # 有效期限：一律用20XX（現代護照都是2000年後簽發）
                    yyyy = '20' + yy
                    if mm.isdigit() and dd.isdigit():
                        result['expiration_date'] = f'{yyyy}-{mm}-{dd}'

                # Check digit for expiry (char 27)
                # Personal number (chars 28-42)
                pn_field = line2[28:42].strip('<')
                if pn_field:
                    result['personal_number'] = pn_field

            return result

        except Exception:
            return None

    def _mrz_to_fields(self, mrz_data):
        """Convert MRZ data to user-friendly Chinese field names."""
        fields = {}
        if mrz_data.get('surname'):
            fields['姓氏'] = mrz_data['surname']
        if mrz_data.get('names'):
            fields['名字'] = mrz_data['names']
        if mrz_data.get('passport_number'):
            fields['護照號碼'] = mrz_data['passport_number']
        if mrz_data.get('nationality'):
            fields['國籍'] = {'TWN': '台灣', 'CHN': '中國', 'USA': '美國',
                            'JPN': '日本', 'KOR': '韓國', 'GBR': '英國',
                            'CAN': '加拿大', 'AUS': '澳洲'}.get(
                mrz_data['nationality'], mrz_data['nationality'])
        if mrz_data.get('birth_date'):
            fields['出生日期'] = mrz_data['birth_date']
        if mrz_data.get('sex'):
            sex_map = {'M': '男', 'F': '女', '<': '未指定'}
            fields['性別'] = sex_map.get(mrz_data['sex'], mrz_data['sex'])
        if mrz_data.get('expiration_date'):
            fields['有效期限'] = mrz_data['expiration_date']
        if mrz_data.get('personal_number'):
            fields['個人ID'] = mrz_data['personal_number']
        return fields

    def _extract_visual_zone(self, processed):
        """Extract text from the visual zone (top ~60%) of the passport."""
        h, w = processed.shape
        top_h = int(h * 0.62)
        visual = processed[0:top_h, :]

        temp_path = '/tmp/_visual_zone.png'
        cv2.imwrite(temp_path, visual)

        try:
            with PyTessBaseAPI(lang=self.lang, psm=PSM.AUTO,
                               oem=OEM.LSTM_ONLY) as api:
                api.SetImageFile(temp_path)
                text = api.GetUTF8Text().strip()
                return text
        except Exception:
            return ''

    def _parse_visual_zone(self, text):
        """Parse text from visual zone into structured fields."""
        fields = {}
        if not text:
            return fields

        lines = [l.strip() for l in text.split('\n') if l.strip()]
        full_text = '\n'.join(lines)

        # Common passport visual zone field patterns
        patterns = {
            '護照號碼': [
                r'PASS[E]?PORT\s*NO[.:]?\s*(\w{5,})',
                r'No[.:]\s*([A-Z0-9]{5,})',
                r'護照號碼[：:]\s*(\w+)',
            ],
            '姓氏': [
                r'Surname[.:]?\s*([A-Za-z\s\-]+?)(?:\n|$)',
                r'姓[：:]?\s*([A-Za-z\u4e00-\u9fff\s\-]+?)(?:\n|$)',
                r'Last\s*Name[.:]?\s*([A-Za-z\s\-]+?)(?:\n|$)',
            ],
            '名字': [
                r'Given\s*Names?[.:]?\s*([A-Za-z\s\-]+?)(?:\n|$)',
                r'名[：:]?\s*([A-Za-z\u4e00-\u9fff\s\-]+?)(?:\n|$)',
                r'First\s*Name[.:]?\s*([A-Za-z\s\-]+?)(?:\n|$)',
            ],
            '出生日期': [
                r'Date\s*of\s*Birth[.:]?\s*([\d\.\-\/]+)',
                r'出生日期[：:]?\s*([\d\.\-\/]+)',
                r'DOB[.:]?\s*([\d\.\-\/]+)',
            ],
            '性別': [
                r'Sex[.:]?\s*([MFmf男女])',
                r'性別[：:]?\s*([MFmf男女])',
                r'Gender[.:]?\s*([MFmf男女])',
            ],
            '國籍': [
                r'Nationality[.:]?\s*(.+?)(?:\n|$)',
                r'國籍[：:]?\s*(.+?)(?:\n|$)',
            ],
            '有效期限': [
                r'Date\s*of\s*Expir(?:y|ation)[.:]?\s*([\d\.\-\/]+)',
                r'有效期限[：:]?\s*([\d\.\-\/]+)',
                r'Expir(?:y|ation)\s*Date[.:]?\s*([\d\.\-\/]+)',
            ],
            '簽發日期': [
                r'Date\s*of\s*Issue[.:]?\s*([\d\.\-\/]+)',
                r'簽發日期[：:]?\s*([\d\.\-\/]+)',
                r'Issue\s*Date[.:]?\s*([\d\.\-\/]+)',
            ],
            '出生地': [
                r'Place\s*of\s*Birth[.:]?\s*(.+?)(?:\n|$)',
                r'出生地[：:]?\s*(.+?)(?:\n|$)',
            ],
            '簽發機關': [
                r'Authorit(?:y|ies)[.:]?\s*(.+?)(?:\n|$)',
                r'簽發機關[：:]?\s*(.+?)(?:\n|$)',
                r'Issuing\s*Authorit(?:y|ies)[.:]?\s*(.+?)(?:\n|$)',
            ],
        }

        for field_name, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, full_text, re.IGNORECASE)
                if m:
                    value = m.group(1).strip().rstrip(',;:')
                    if value and len(value) < 100:
                        fields[field_name] = value
                        break

        return fields
