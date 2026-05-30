"""
Google Sheets integration for passport scanner.
Uses gspread with a service account.
"""

import os
import json
import gspread
from datetime import datetime


class GoogleSheetsWriter:
    """Write passport data to Google Sheets."""

    def __init__(self, credentials_path=None):
        self.credentials_path = credentials_path or os.environ.get(
            'GOOGLE_SHEET_CREDENTIALS'
        )
        self.sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        self.gc = None
        self.sheet = None

    def is_connected(self):
        """Check if we have an active connection."""
        return self.gc is not None

    def connect(self):
        """Connect to Google Sheets API."""
        if self.gc:
            return True

        try:
            # Try from env var (JSON string)
            creds_json = os.environ.get('GOOGLE_SHEET_CREDENTIALS_JSON')
            if creds_json:
                creds_dict = json.loads(creds_json)
                self.gc = gspread.service_account_from_dict(creds_dict)
                return True

            # Try from file path
            if self.credentials_path and os.path.exists(self.credentials_path):
                self.gc = gspread.service_account(filename=self.credentials_path)
                return True

            return False
        except Exception as e:
            print(f"Google Sheets connect error: {e}")
            return False

    def get_or_create_sheet(self, title='護照掃描紀錄'):
        """Get existing sheet or create a new one."""
        if not self.connect():
            return False

        try:
            if self.sheet_id:
                self.sheet = self.gc.open_by_key(self.sheet_id)
            else:
                # Try to find by title
                try:
                    self.sheet = self.gc.open(title)
                except gspread.SpreadsheetNotFound:
                    self.sheet = self.gc.create(title)
                    # Also store the sheet ID
                    self.sheet_id = self.sheet.id
                    os.environ['GOOGLE_SHEET_ID'] = self.sheet.id

            # Ensure header row exists
            ws = self.sheet.sheet1
            if not ws.get_all_values():
                headers = [
                    '掃描時間', '姓氏', '名字', '護照號碼', '國籍',
                    '出生日期', '性別', '有效期限', '個人ID',
                    '簽發日期', '出生地', '簽發機關',
                    'MRZ第一行', 'MRZ第二行', '原始OCR文字'
                ]
                ws.append_row(headers)
                ws.format('1:1', {'textFormat': {'bold': True}})

            return True
        except Exception as e:
            print(f"Sheet access error: {e}")
            return False

    def append_record(self, fields: dict, mrz_data: dict = None,
                      raw_text: str = '', mrz_lines: list = None):
        """Append a passport record to the sheet."""
        if not self.sheet:
            if not self.get_or_create_sheet():
                return False

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        mrz1 = mrz_lines[0] if mrz_lines else (mrz_data.get('lines', [''])[0] if mrz_data else '')
        mrz2 = mrz_lines[1] if mrz_lines and len(mrz_lines) > 1 else (
            mrz_data.get('lines', ['', ''])[1] if mrz_data else ''
        )

        row = [
            now,
            fields.get('姓氏', fields.get('surname', '')),
            fields.get('名字', fields.get('names', '')),
            fields.get('護照號碼', fields.get('passport_number', '')),
            fields.get('國籍', fields.get('nationality', '')),
            fields.get('出生日期', fields.get('birth_date', '')),
            fields.get('性別', fields.get('sex', '')),
            fields.get('有效期限', fields.get('expiration_date', '')),
            fields.get('個人ID', fields.get('personal_number', '')),
            fields.get('簽發日期', ''),
            fields.get('出生地', ''),
            fields.get('簽發機關', ''),
            mrz1,
            mrz2,
            raw_text[:500] if raw_text else '',
        ]

        try:
            ws = self.sheet.sheet1
            ws.append_row(row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            print(f"Append error: {e}")
            return False

    def get_all_records(self, limit=50):
        """Get recent records from the sheet."""
        if not self.connect():
            return []

        try:
            if not self.sheet:
                # Try to open by ID first, then by title
                if self.sheet_id:
                    self.sheet = self.gc.open_by_key(self.sheet_id)
                else:
                    try:
                        self.sheet = self.gc.open('護照掃描紀錄')
                    except gspread.SpreadsheetNotFound:
                        return []
            ws = self.sheet.sheet1
            records = ws.get_all_records()
            return records[-limit:] if len(records) > limit else records
        except Exception:
            return []
