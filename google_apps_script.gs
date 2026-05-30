/**
 * 小柴子護照掃描器 - Google 試算表 Webhook
 * 
 * 💡 使用方式：
 * 1. 建立一個新的 Google 試算表
 * 2. 點選「延伸功能」→「Apps Script」
 * 3. 把這段程式碼全部貼進去，覆蓋預設內容
 * 4. 按「部署」→「新增部署作業」→「網頁應用程式」
 * 5. 執行身分選「我」→「誰可以存取」選「任何人」
 * 6. 按「部署」，複製產生的網址
 * 7. 把網址貼到 Render 的環境變數 GOOGLE_SHEET_WEBHOOK_URL
 */

// 當有新資料 POST 進來時觸發
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // 如果第一列還沒有標題，自動建立
    if (sheet.getLastRow() === 0) {
      const headers = [
        '掃描時間', '姓氏', '名字', '護照號碼', '國籍',
        '出生日期', '性別', '有效期限', '個人ID',
        '簽發日期', '出生地', '簽發機關',
        'MRZ第一行', 'MRZ第二行', '原始OCR文字'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    }
    
    // 組合資料列
    const row = [
      data.掃描時間 || new Date().toLocaleString('zh-TW', {timeZone:'Asia/Taipei'}),
      data.姓氏 || '',
      data.名字 || '',
      data.護照號碼 || '',
      data.國籍 || '',
      data.出生日期 || '',
      data.性別 || '',
      data.有效期限 || '',
      data.個人ID || '',
      data.簽發日期 || '',
      data.出生地 || '',
      data.簽發機關 || '',
      data.MRZ第一行 || '',
      data.MRZ第二行 || '',
      (data.原始OCR文字 || '').substring(0, 500)
    ];
    
    // 寫入下一行
    sheet.appendRow(row);
    
    return ContentService
      .createTextOutput(JSON.stringify({ success: true }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// 測試用：GET 請求顯示當前資料
function doGet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const data = sheet.getDataRange().getValues();
  
  let html = '<html><body style="font-family:sans-serif;">';
  html += '<h2>📋 護照掃描紀錄</h2>';
  html += '<p>共 ' + (data.length - 1) + ' 筆資料</p>';
  html += '<table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px;">';
  
  for (let r = 0; r < Math.min(data.length, 51); r++) {
    html += '<tr>';
    for (let c = 0; c < data[r].length; c++) {
      const tag = r === 0 ? 'th' : 'td';
      html += '<' + tag + '>' + (data[r][c] || '') + '</' + tag + '>';
    }
    html += '</tr>';
  }
  
  html += '</table></body></html>';
  return HtmlService.createHtmlOutput(html);
}
