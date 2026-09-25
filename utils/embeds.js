const { EmbedBuilder } = require('discord.js');
const queue = require('./queue');

/** إمبد بانل فتح التفعيل (يتحدث تلقائيًا كل ما تصدر تذكرة) */
function buildPanelEmbed(period) {
  const summary = queue.getQueueSummary(period.id);
  return new EmbedBuilder()
    .setTitle('🎫 التفعيل مفتوح الآن')
    .setDescription(
      'اضغط زر **أخذ تذكرة** لتحصل على دورك بالطابور.\n' +
        'استخدم **تذكرتي** لمعرفة رقمك وترتيبك، و**حالة الطابور** لمعرفة الوضع العام.'
    )
    .addFields(
      { name: 'التذاكر الحالية', value: `${summary.total} / ${period.max_tickets}`, inline: true },
      { name: 'قيد الانتظار', value: `${summary.waiting}`, inline: true },
      { name: 'قيد المعالجة', value: `${summary.claimed}`, inline: true },
      { name: 'مكتملة', value: `${summary.closed}`, inline: true }
    )
    .setColor(period.status === 'open' ? 0x57f287 : 0xed4245)
    .setFooter({ text: period.status === 'open' ? 'الطابور مفتوح' : 'الطابور مغلق' })
    .setTimestamp();
}

/** إمبد داخل روم التكت الخاص بالعضو */
function buildTicketEmbed(ticket) {
  const ahead = queue.getPositionInfo(ticket);
  const statusMap = {
    waiting: '🟡 بالانتظار',
    claimed: '🔵 قيد المعالجة',
    closed: '🟢 مكتملة',
  };
  return new EmbedBuilder()
    .setTitle(`تذكرة #${ticket.ticket_number}`)
    .addFields(
      { name: 'العضو', value: `<@${ticket.user_id}>`, inline: true },
      { name: 'الحالة', value: statusMap[ticket.status], inline: true },
      { name: 'المتبقي قدامك', value: ticket.status === 'waiting' ? `${ahead}` : '—', inline: true }
    )
    .setColor(0x5865f2)
    .setTimestamp();
}

/** رد مخفي لأمر "تذكرتي" */
function buildMyTicketEmbed(ticket) {
  if (!ticket) {
    return new EmbedBuilder().setDescription('❌ لا يوجد لديك تكت مفتوح.').setColor(0xed4245);
  }
  const ahead = queue.getPositionInfo(ticket);
  const statusMap = {
    waiting: '🟡 بالانتظار',
    claimed: '🔵 قيد المعالجة حاليًا',
    closed: '🟢 مكتملة',
  };
  return new EmbedBuilder()
    .setTitle(`🎫 تذكرتك #${ticket.ticket_number}`)
    .addFields(
      { name: 'الحالة', value: statusMap[ticket.status], inline: true },
      { name: 'أمامك', value: ticket.status === 'waiting' ? `${ahead} شخص` : '—', inline: true },
      { name: 'الروم', value: ticket.channel_id ? `<#${ticket.channel_id}>` : '—', inline: true }
    )
    .setColor(0x5865f2);
}

/** رد مخفي لأمر "حالة الطابور" */
function buildQueueStatusEmbed(period) {
  const summary = queue.getQueueSummary(period.id);
  return new EmbedBuilder()
    .setTitle('📊 حالة الطابور')
    .addFields(
      { name: 'الإجمالي', value: `${summary.total} / ${period.max_tickets}`, inline: true },
      { name: 'بالانتظار', value: `${summary.waiting}`, inline: true },
      { name: 'قيد المعالجة', value: `${summary.claimed}`, inline: true },
      { name: 'مكتملة', value: `${summary.closed}`, inline: true }
    )
    .setColor(0x5865f2);
}

/** إمبد اللوق يُرسل بروم اللوقات عند إغلاق أي تكت */
function buildTicketLogEmbed(ticket) {
  const fmt = (iso) => (iso ? `<t:${Math.floor(new Date(iso + 'Z').getTime() / 1000)}:F>` : '—');
  return new EmbedBuilder()
    .setTitle(`📁 سجل التذكرة #${ticket.ticket_number}`)
    .addFields(
      { name: 'فتحها', value: `<@${ticket.user_id}>`, inline: true },
      { name: 'وقت الفتح', value: fmt(ticket.opened_at), inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
      { name: 'استلمها', value: ticket.claimed_by ? `<@${ticket.claimed_by}>` : '— لم تُستلم —', inline: true },
      { name: 'وقت الاستلام', value: fmt(ticket.claimed_at), inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
      { name: 'أغلقها', value: `<@${ticket.closed_by}>`, inline: true },
      { name: 'وقت الإغلاق', value: fmt(ticket.closed_at), inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
      { name: 'سبب الإغلاق', value: ticket.close_reason || '—', inline: false }
    )
    .setColor(0xed4245)
    .setTimestamp();
}

module.exports = {
  buildPanelEmbed,
  buildTicketEmbed,
  buildMyTicketEmbed,
  buildQueueStatusEmbed,
  buildTicketLogEmbed,
};
