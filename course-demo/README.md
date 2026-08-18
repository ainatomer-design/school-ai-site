# אתר בית ספר עם עוזר AI

פרויקט הגשה לקורס פיתוח AI (~120 שעות).

אפליקציית ווב: אתר בית ספר ציבורי + לוח ניהול. המנהל מדבר בעברית עם Gemini, מאשר שינויים, והתוכן נשמר ב-Supabase. האפליקציה רצה ב-Railway.

## מה מציגים

1. **אתר ציבורי** (`/`) — באנר, הודעה, קישורים, כיתות.
2. **לוח ניהול** (`/admin`) — הזנת מפתח Gemini, עריכת תוכן, צ'אט AI, יומן שיחות.
3. **מסד נתונים** — טבלאות `school_state` ו-`ai_logs` ב-Supabase.
4. **העלאה** — Railway עם משתני סביבה.

דוגמה להדגמה: בלשונת עוזר AI כותבים «שנה את שם בית הספר לאור תורה ושנה את הצבע לכחול כהה» → מאשרים → האתר הציבורי מתעדכן.

## מפתחות שחייבים להכניס

| מפתח | מאיפה | לאן |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | מסך הניהול, או משתנה ב-Railway |
| `SUPABASE_URL` | Supabase → Project Settings → API | Railway Variables / `.env` |
| `SUPABASE_SERVICE_ROLE_KEY` | אותו מסך, **service_role** (לא anon) | Railway Variables / `.env` |

את מפתח ה-service_role לא שמים בקוד ולא ב-Git.

## 1. Supabase

1. צרו פרויקט ב-[supabase.com](https://supabase.com).
2. SQL Editor → הדביקו והריצו את `supabase/schema.sql`.
3. Settings → API: העתיקו Project URL ו-`service_role`.

## 2. הרצה מקומית

```bash
cd course-demo
copy .env.example .env
```

השלימו את שלושת המפתחות ב-`.env`, ואז:

```bash
pip install -r requirements.txt
python app.py
```

- אתר: http://localhost:5000
- ניהול: http://localhost:5000/admin

## 3. העלאה ל-Railway

1. העלו את התיקייה ל-GitHub (בלי `.env`).
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub.
3. Root Directory: `course-demo` (אם כל הריפו עולה).
4. Variables:

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
GEMINI_API_KEY=AIza...
```

5. Generate Domain. כתובת האתר הציבורי היא הדומיין של Railway, ולוח הניהול הוא `/admin`.

## מבנה

```
course-demo/
  app.py                 שרת Flask: Gemini + Supabase
  Procfile / railway.toml
  supabase/schema.sql
  static/index.html      אתר בית הספר
  static/admin.html      ניהול + AI
```

## מה הקורס רואה בטכנולוגיה

- **AI:** Gemini דרך שרת (המפתח לא נזרק לקוד הציבורי של האתר).
- **DB:** JSON של האתר + יומן שיחות ב-Postgres (Supabase).
- **Deploy:** Gunicorn על Railway, פורט מ-`$PORT`.
