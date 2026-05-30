"""
Google Sheets integration for passport scanner.
Supports two modes:
  A) Google Apps Script Webhook (simple - recommended!)
  B) gspread + Service Account (advanced)
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime


class GoogleSheetsWriter:
    """Write passport data to Google Sheets."""

    def __init__(self):
        self.webhook_url = os.environ.get('GOOGLE_SHEET_WEBHOOK_URL', '')
        self._webhook_ok = bool(self.webhook_url)

        # gspread fallback (legacy)
        self.credentials_json = os.environ.get('GOOGLE_SHEET_CREDENTIALS_JSON', '')
        self.sheet_id = os.environ.get('GOOGLE_SHEET_ID', '')
        self.gc = None
        self.sheet = None

    def is_connected(self):
        """Check if we have a working connection method."""
        if self._webhook_ok:
            return True
        if self.credentials_json and self.sheet_id:
            return self._connect_gspread()
        return False

    def connect(self):
        """Connect using available method."""
        if self._webhook_ok:
            return True
        if self.credentials_json:
            return self._connect_gspread()
        return False

    def _connect_gspread(self):
        """Connect via gspread service account (legacy)."""
        if self.gc:
            return True
        try:
            import gspread
            creds_dict = json.loads(self.credentials_json)
            self.gc = gspread.service_account_from_dict(creds_dict)
            if self.sheet_id:
                self.sheet = self.gc.open_by_key(self.sheet_id)
            return True
        except Exception as e:
            print(f"gspread connect error: {e}")
            return False

    def _call_webhook(self, data: dict) -> bool:
        """Send data to Google Apps Script webhook."""
        if not self.webhook_url:
            return False

        payload = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result.get('success', False)
        except Exception as e:
            print(f"Webhook error: {e}")
            return False

    def append_record(self, fields: dict, mrz_data: dict = None,
                      raw_text: str = '', mrz_lines: list = None):
        """Append a passport record to the sheet."""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        mrz1 = mrz_lines[0] if mrz_lines else ''
        mrz2 = mrz_lines[1] if mrz_lines and len(mrz_lines) > 1 else ''

        # Prepare data (same field names as Apps Script expects)
        data = {
            '掃描時間': now,
            '姓氏': fields.get('姓氏', ''),
            '名字': fields.get('名字', ''),
            '護照號碼': fields.get('護照號碼', ''),
            '國籍': fields.get('國籍', ''),
            '出生日期': fields.get('出生日期', ''),
            '性別': fields.get('性別', ''),
            '有效期限': fields.get('有效期限', ''),
            '個人ID': fields.get('個人ID', ''),
            '簽發日期': fields.get('簽發日期', ''),
            '出生地': fields.get('出生地', ''),
            '簽發機關': fields.get('簽發機關', ''),
            'MRZ第一行': mrz1,
            'MRZ第二行': mrz2,
            '原始OCR文字': (raw_text or '')[:500],
        }

        # Try webhook first (preferred, simpler method)
        if self._webhook_ok:
            return self._call_webhook(data)

        # Fallback to gspread
        try:
            if not self.sheet and not self._connect_gspread():
                return False
            ws = self.sheet.sheet1
            row = [data.get(k, '') for k in [
                '掃描時間', '姓氏', '名字', '護照號碼', '國籍',
                '出生日期', '性別', '有效期限', '個人ID',
                '簽發日期', '出生地', '簽發機關',
                'MRZ第一行', 'MRZ第二行', '原始OCR文字'
            ]]
            ws.append_row(row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            print(f"Append error: {e}")
            return False

    def get_all_records(self, limit=50):
        """Get recent records from gspread (webhook doesn't support readback)."""
        if not self._connect_gspread():
            return []
        try:
            if not self.sheet:
                return []
            ws = self.sheet.sheet1
            records = ws.get_all_records()
            return records[-limit:] if len(records) > limit else records
        except Exception:
            return []
