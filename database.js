const Database = require('better-sqlite3');
const path = require('path');

const db = new Database(path.join(__dirname, 'bot.db'));
db.pragma('journal_mode = WAL');

// ============ إنشاء الجداول ============

db.exec(`
CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_of_week INTEGER NOT NULL,      -- 0 = الأحد ... 6 = السبت (يطابق ترقيم node-cron)
  hour INTEGER NOT NULL,             -- الساعة بتوقيت السعودية (0-23)
  minute INTEGER NOT NULL,           -- الدقيقة (0-59)
  max_tickets INTEGER NOT NULL,      -- الحد الأقصى للتكتات لهذا الموعد
  channel_id TEXT NOT NULL,          -- روم فتح البانل
  active INTEGER NOT NULL DEFAULT 1, -- 1 = مفعّل، 0 = موقوف مؤقتًا
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS periods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,          -- الروم اللي فيه البانل
  panel_message_id TEXT,             -- رسالة البانل (يتم تحديثها بالعداد)
  max_tickets INTEGER NOT NULL,
  ticket_count INTEGER NOT NULL DEFAULT 0,  -- عدد التذاكر اللي صدرت لين الحين
  status TEXT NOT NULL DEFAULT 'open',      -- open | closed
  opened_at TEXT NOT NULL DEFAULT (datetime('now')),
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period_id INTEGER NOT NULL,
  ticket_number INTEGER NOT NULL,    -- رقم التذكرة داخل نفس الفترة (1, 2, 3 ...)
  user_id TEXT NOT NULL,
  channel_id TEXT,                   -- روم التكت الخاص بهذا العضو
  status TEXT NOT NULL DEFAULT 'waiting',  -- waiting | claimed | closed
  claimed_by TEXT,
  closed_by TEXT,
  close_reason TEXT,
  opened_at TEXT NOT NULL DEFAULT (datetime('now')),
  claimed_at TEXT,
  closed_at TEXT,
  FOREIGN KEY (period_id) REFERENCES periods(id)
);

CREATE INDEX IF NOT EXISTS idx_tickets_period ON tickets(period_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(period_id, status);

-- يمنع أي عضو من امتلاك أكثر من تذكرة غير مغلقة بنفس الفترة (حماية على مستوى قاعدة البيانات
-- ضد الضغط المزدوج أو أي محاولة فتح تذكرتين بنفس الوقت)
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_ticket_per_user
  ON tickets(period_id, user_id)
  WHERE status != 'closed';
`);

module.exports = db;
