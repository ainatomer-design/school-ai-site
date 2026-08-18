// ============================================================
// Google Apps Script — שרת-ענן לניהול הגדרות אתר בית הספר
// ============================================================
//
// הוראות הגדרה (עשה פעם אחת):
// -------------------------------------------------------
// 1. פתח את script.google.com
// 2. לחץ "פרויקט חדש" ותן לו שם (למשל: "ניהול אתר בי"ס")
// 3. מחק את הקוד הקיים והדבק קוד זה
// 4. צור Google Sheet חדש ב-drive.google.com
// 5. מתוך ה-URL של הגיליון, העתק את ה-ID
//    (הסדרה הארוכה בין /d/ ל-/edit)
// 6. הכנס את ה-ID בשורה SPREADSHEET_ID למטה
// 7. לחץ "שמור" (Ctrl+S)
// 8. לחץ "פרסם" > "פרסם כאפליקציית אינטרנט"
//    - בחר: "הפעל כ: אני (כתובת המייל שלך)"
//    - בחר: "מי יכול לגשת: כל אחד (גם אנונימי)"
// 9. לחץ "פרסם" ואשר את ההרשאות
// 10. העתק את כתובת ה-Web App URL
//     (נראה כך: https://script.google.com/macros/s/.../exec)
// 11. הכנס אותה בלוח הבקרה (admin-panel.html) > "Apps Script"
// ============================================================

// ✏️ הכנס כאן את ה-ID של Google Sheet שלך
const SPREADSHEET_ID = 'הכנס_כאן_את_ה_ID_של_גוגל_שיטס';

// שם הגיליון לאחסון ההגדרות (אל תשנה)
const SHEET_NAME = 'הגדרות_אתר';

// ============================================================
// פונקציה ראשית — מגיבה לבקשות GET (קריאת הגדרות)
// ============================================================
function doGet(e) {
  // הוסף CORS headers לאפשר גישה מ-Google Sites
  const output = handleGet(e);
  return output;
}

function handleGet(e) {
  const action = (e && e.parameter && e.parameter.action) || 'getSettings';

  try {
    if (action === 'getSettings') {
      return jsonResponse(getSettings());
    }

    if (action === 'ping') {
      return jsonResponse({
        success: true,
        message: 'שרת ניהול אתר בית הספר פעיל ✓',
        timestamp: new Date().toISOString()
      });
    }

    return jsonResponse({ success: false, error: 'פעולה לא מוכרת: ' + action });

  } catch (err) {
    return jsonResponse({ success: false, error: err.message });
  }
}

// ============================================================
// פונקציה ראשית — מגיבה לבקשות POST (שמירת הגדרות)
// ============================================================
function doPost(e) {
  try {
    const body   = JSON.parse(e.postData.contents);
    const action = body.action;

    if (action === 'saveSettings') {
      return jsonResponse(saveSettings(body.settings));
    }

    return jsonResponse({ success: false, error: 'פעולה לא מוכרת' });

  } catch (err) {
    return jsonResponse({ success: false, error: err.message });
  }
}

// ============================================================
// קריאת הגדרות מהגיליון
// ============================================================
function getSettings() {
  try {
    const sheet = getOrCreateSheet();
    const data  = sheet.getDataRange().getValues();
    const settings = {};

    // שורה 0 = כותרות, מתחילים משורה 1
    for (let i = 1; i < data.length; i++) {
      const key   = String(data[i][0]).trim();
      const value = String(data[i][1]).trim();
      if (key) settings[key] = value;
    }

    return {
      success: true,
      settings: Object.keys(settings).length > 0 ? settings : getDefaultSettings(),
      lastUpdated: PropertiesService.getScriptProperties().getProperty('lastUpdated') || '',
      source: 'sheets'
    };

  } catch (err) {
    // במקרה של שגיאה — החזר הגדרות ברירת מחדל
    return {
      success: true,
      settings: getDefaultSettings(),
      lastUpdated: '',
      source: 'defaults',
      warning: 'שגיאה בגיליון, הוחזרו הגדרות ברירת מחדל: ' + err.message
    };
  }
}

// ============================================================
// שמירת הגדרות לגיליון
// ============================================================
function saveSettings(settings) {
  if (!settings || typeof settings !== 'object') {
    return { success: false, error: 'הגדרות לא תקינות' };
  }

  const sheet = getOrCreateSheet();

  // ניקוי תוכן קיים
  sheet.clearContents();

  // כותרות עמודות
  sheet.getRange(1, 1, 1, 3).setValues([['מפתח', 'ערך', 'עודכן']]);
  sheet.getRange(1, 1, 1, 3).setFontWeight('bold');
  sheet.getRange(1, 1, 1, 3).setBackground('#e8f0fe');

  // כתיבת כל ההגדרות כ-key: value
  const now  = new Date().toLocaleString('he-IL');
  const rows = flattenSettings(settings, now);

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, 3).setValues(rows);
  }

  // עיצוב הגיליון
  sheet.setColumnWidth(1, 200);
  sheet.setColumnWidth(2, 400);
  sheet.setColumnWidth(3, 160);

  // שמירת חותמת זמן
  const timestamp = new Date().toISOString();
  PropertiesService.getScriptProperties().setProperty('lastUpdated', timestamp);

  return {
    success: true,
    message: 'ההגדרות נשמרו בהצלחה ✓',
    rowsWritten: rows.length,
    timestamp: timestamp
  };
}

// ============================================================
// המרת אובייקט הגדרות לשורות פשוטות key-value
// ============================================================
function flattenSettings(obj, timestamp, prefix) {
  prefix = prefix || '';
  const rows = [];

  for (const key in obj) {
    if (!obj.hasOwnProperty(key)) continue;
    const fullKey = prefix ? prefix + '.' + key : key;
    const value   = obj[key];

    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      // אובייקט מקונן — שטח רקורסיבית
      const nested = flattenSettings(value, timestamp, fullKey);
      rows.push.apply(rows, nested);
    } else if (Array.isArray(value)) {
      // מערך — שמור כ-JSON
      rows.push([fullKey, JSON.stringify(value), timestamp]);
    } else {
      rows.push([fullKey, String(value), timestamp]);
    }
  }

  return rows;
}

// ============================================================
// פתיחה/יצירה של גיליון ההגדרות
// ============================================================
function getOrCreateSheet() {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  let   sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    // כותרת ראשונה
    sheet.getRange('A1').setValue('מפתח');
    sheet.getRange('B1').setValue('ערך');
    sheet.getRange('C1').setValue('עודכן');
    sheet.getRange(1, 1, 1, 3).setFontWeight('bold').setBackground('#e8f0fe');
  }

  return sheet;
}

// ============================================================
// עזר — יצירת תגובת JSON
// ============================================================
function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

// ============================================================
// הגדרות ברירת מחדל
// ============================================================
function getDefaultSettings() {
  return {
    // ===== צבעים =====
    'colors.primary':   '#1a73e8',
    'colors.secondary': '#fbbc04',
    'colors.accent':    '#34a853',
    'colors.bg':        '#f8f9fa',

    // ===== פרטי בית הספר =====
    'school.name':  'בית ספר שלנו',
    'school.year':  'תשפ"ה',
    'school.motto': '',
    'school.email': '',

    // ===== כפתורים מהירים =====
    'links': JSON.stringify([
      { icon: '📅', text: 'מערכת שעות',    url: '#', color: '#1a73e8' },
      { icon: '📚', text: 'חומרי למידה',   url: '#', color: '#34a853' },
      { icon: '🎮', text: 'משחקים חינוכיים', url: '#', color: '#9c27b0' },
      { icon: '📧', text: 'יצירת קשר',     url: '#', color: '#ea4335' },
    ]),

    // ===== הודעה גלובלית =====
    'announcement.active': 'false',
    'announcement.text':   '',
    'announcement.type':   'info',
  };
}

// ============================================================
// פונקציית בדיקה — הפעל ידנית ב-Apps Script לבדיקה
// ============================================================
function testFunctions() {
  Logger.log('=== בדיקת שמירה ===');
  const saveResult = saveSettings({
    colors: { primary: '#1a73e8', secondary: '#fbbc04' },
    school: { name: 'בית ספר דוגמה', year: 'תשפ"ה' },
    links: [{ icon: '📚', text: 'ספרייה', url: '#' }]
  });
  Logger.log(JSON.stringify(saveResult));

  Logger.log('=== בדיקת קריאה ===');
  const getResult = getSettings();
  Logger.log(JSON.stringify(getResult));
}
