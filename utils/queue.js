const db = require('../database');

// ============ الفترات (Activation Periods) ============

/** يرجع الفترة المفتوحة حاليًا إن وجدت */
function getOpenPeriod() {
  return db.prepare(`SELECT * FROM periods WHERE status = 'open' ORDER BY id DESC LIMIT 1`).get();
}

/** يفتح فترة تفعيل جديدة */
function openPeriod({ channelId, maxTickets }) {
  const existing = getOpenPeriod();
  if (existing) {
    throw new Error('يوجد فترة تفعيل مفتوحة بالفعل. أغلقها أولًا قبل فتح فترة جديدة.');
  }
  const info = db
    .prepare(`INSERT INTO periods (channel_id, max_tickets, status) VALUES (?, ?, 'open')`)
    .run(channelId, maxTickets);
  return db.prepare(`SELECT * FROM periods WHERE id = ?`).get(info.lastInsertRowid);
}

/** يقفل الفترة الحالية عن استقبال تذاكر جديدة (لا يغلق التكتات القائمة) */
function closePeriod(periodId) {
  db.prepare(`UPDATE periods SET status = 'closed', closed_at = datetime('now') WHERE id = ?`).run(periodId);
}

function setPanelMessage(periodId, messageId) {
  db.prepare(`UPDATE periods SET panel_message_id = ? WHERE id = ?`).run(messageId, periodId);
}

function getPeriod(periodId) {
  return db.prepare(`SELECT * FROM periods WHERE id = ?`).get(periodId);
}

// ============ التذاكر (Tickets) ============

/** كم شخص أخذ تذكرة بالفترة الحالية (بغض النظر عن حالتها) */
function countTicketsInPeriod(periodId) {
  return db.prepare(`SELECT COUNT(*) AS c FROM tickets WHERE period_id = ?`).get(periodId).c;
}

/** هل عند هذا العضو تذكرة مفتوحة (غير مغلقة) بنفس الفترة؟ */
function getUserOpenTicket(periodId, userId) {
  return db
    .prepare(`SELECT * FROM tickets WHERE period_id = ? AND user_id = ? AND status != 'closed'`)
    .get(periodId, userId);
}

/**
 * يصدر تذكرة جديدة للعضو ضمن فترة معينة، مع مراعاة الحد الأقصى.
 * كل الفحوصات + الإدراج داخل transaction واحدة متزامنة (better-sqlite3 synchronous) —
 * هذا يمنع فعليًا أي احتمال يفتح فيه نفس العضو تذكرتين بضغطتين سريعتين، أو يتجاوز
 * الحد الأقصى بسبب ضغط متزامن من أكثر من عضو بنفس اللحظة.
 * يرمي خطأ برسالة عربية واضحة لو الحد اكتمل أو عند العضو تذكرة مفتوحة أصلًا.
 */
const issueTicketTx = db.transaction(({ periodId, userId }) => {
  const period = getPeriod(periodId);
  if (!period || period.status !== 'open') {
    throw new Error('التفعيل مقفول حاليًا، انتظر فترة تفعيل جديدة.');
  }

  const already = getUserOpenTicket(periodId, userId);
  if (already) {
    throw new Error(`عندك تذكرة مفتوحة بالفعل برقم #${already.ticket_number}.`);
  }

  const current = countTicketsInPeriod(periodId);
  if (current >= period.max_tickets) {
    throw new Error('❌ اكتمل عدد التذاكر لهذه الفترة. انتظر فترة تفعيل جديدة.');
  }

  const ticketNumber = current + 1;
  // الفهرس الفريد idx_one_open_ticket_per_user يشكّل خط دفاع أخير: لو صار أي
  // تعارض غير متوقع، الإدراج نفسه يفشل بدل ما ينشئ تذكرة مكررة.
  const info = db
    .prepare(
      `INSERT INTO tickets (period_id, ticket_number, user_id, status) VALUES (?, ?, ?, 'waiting')`
    )
    .run(periodId, ticketNumber, userId);

  db.prepare(`UPDATE periods SET ticket_count = ticket_count + 1 WHERE id = ?`).run(periodId);

  return db.prepare(`SELECT * FROM tickets WHERE id = ?`).get(info.lastInsertRowid);
});

function issueTicket({ periodId, userId }) {
  try {
    return issueTicketTx({ periodId, userId });
  } catch (err) {
    if (String(err.message).includes('UNIQUE constraint failed')) {
      throw new Error('عندك تذكرة مفتوحة بالفعل.');
    }
    throw err;
  }
}

function setTicketChannel(ticketId, channelId) {
  db.prepare(`UPDATE tickets SET channel_id = ? WHERE id = ?`).run(channelId, ticketId);
}

function getTicket(ticketId) {
  return db.prepare(`SELECT * FROM tickets WHERE id = ?`).get(ticketId);
}

function getTicketByChannel(channelId) {
  return db.prepare(`SELECT * FROM tickets WHERE channel_id = ?`).get(channelId);
}

/** كم شخص قدام هذا العضو (تذاكر أرقامها أقل وما زالت منتظرة) */
function getPositionInfo(ticket) {
  const ahead = db
    .prepare(
      `SELECT COUNT(*) AS c FROM tickets WHERE period_id = ? AND status = 'waiting' AND ticket_number < ?`
    )
    .get(ticket.period_id, ticket.ticket_number).c;
  return ahead;
}

/**
 * يتحقق هل يصح استلام هذه التذكرة الآن (كل التذاكر اللي رقمها أقل يجب أن تكون
 * غير "waiting" — أي تم استلامها أو إغلاقها — قبل ما نسمح باستلام هذي).
 * يستخدم داخليًا فقط لعرض رسالة واضحة؛ القرار الفعلي يصير داخل claimTicket (atomic).
 */
function canClaim(ticket) {
  const blocker = db
    .prepare(
      `SELECT ticket_number FROM tickets
       WHERE period_id = ? AND status = 'waiting' AND ticket_number < ?
       ORDER BY ticket_number ASC LIMIT 1`
    )
    .get(ticket.period_id, ticket.ticket_number);

  if (blocker) {
    return { allowed: false, blockingTicketNumber: blocker.ticket_number };
  }
  return { allowed: true };
}

/**
 * استلام التذكرة — عملية atomic كاملة (فحص + تحديث) داخل transaction واحدة متزامنة.
 * بما إن better-sqlite3 متزامن (synchronous) وNode أحادي الخيط، ما فيه أي طريقة
 * يدخل فيها إداريان بنفس اللحظة يستلمون نفس التذكرة أو يتجاوزون الترتيب — الفحص
 * والتحديث يصيران كوحدة واحدة غير قابلة للمقاطعة.
 * يرمي: NOT_FOUND | ALREADY_CLAIMED | BLOCKED:<رقم التذكرة المطلوب استلامها أولًا>
 */
const claimTicketTx = db.transaction((ticketId, staffId) => {
  const ticket = getTicket(ticketId);
  if (!ticket) throw new Error('NOT_FOUND');
  if (ticket.status !== 'waiting') throw new Error('ALREADY_CLAIMED');

  const blocker = db
    .prepare(
      `SELECT ticket_number FROM tickets
       WHERE period_id = ? AND status = 'waiting' AND ticket_number < ?
       ORDER BY ticket_number ASC LIMIT 1`
    )
    .get(ticket.period_id, ticket.ticket_number);
  if (blocker) throw new Error(`BLOCKED:${blocker.ticket_number}`);

  const result = db
    .prepare(`UPDATE tickets SET status = 'claimed', claimed_by = ?, claimed_at = datetime('now') WHERE id = ? AND status = 'waiting'`)
    .run(staffId, ticketId);
  if (result.changes === 0) throw new Error('ALREADY_CLAIMED');

  return getTicket(ticketId);
});

function claimTicket(ticketId, staffId) {
  return claimTicketTx(ticketId, staffId);
}

/**
 * إغلاق التذكرة مع سبب إلزامي، يُسجَّل معه من أغلقها ومتى (للوق).
 */
const closeTicketTx = db.transaction((ticketId, staffId, reason) => {
  const ticket = getTicket(ticketId);
  if (!ticket) throw new Error('NOT_FOUND');
  if (ticket.status === 'closed') throw new Error('ALREADY_CLOSED');

  db.prepare(
    `UPDATE tickets SET status = 'closed', closed_by = ?, close_reason = ?, closed_at = datetime('now') WHERE id = ?`
  ).run(staffId, reason, ticketId);

  return getTicket(ticketId);
});

function closeTicket(ticketId, staffId, reason) {
  return closeTicketTx(ticketId, staffId, reason);
}

/** ملخص حالة الطابور لفترة معينة */
function getQueueSummary(periodId) {
  const rows = db
    .prepare(
      `SELECT status, COUNT(*) AS c FROM tickets WHERE period_id = ? GROUP BY status`
    )
    .all(periodId);

  const summary = { waiting: 0, claimed: 0, closed: 0 };
  for (const r of rows) summary[r.status] = r.c;

  const period = getPeriod(periodId);
  summary.total = period.ticket_count;
  summary.max = period.max_tickets;
  return summary;
}

module.exports = {
  getOpenPeriod,
  openPeriod,
  closePeriod,
  setPanelMessage,
  getPeriod,
  countTicketsInPeriod,
  getUserOpenTicket,
  issueTicket,
  setTicketChannel,
  getTicket,
  getTicketByChannel,
  getPositionInfo,
  canClaim,
  claimTicket,
  closeTicket,
  getQueueSummary,
};
