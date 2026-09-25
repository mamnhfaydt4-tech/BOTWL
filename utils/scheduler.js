const cron = require('node-cron');
const db = require('../database');
const queue = require('./queue');
const { buildPanelEmbed } = require('./embeds');
const { buildPanelButtons } = require('./buttons');

const TIMEZONE = 'Asia/Riyadh';

// خريطة تحتفظ بمهام cron النشطة: scheduleId -> task
const activeJobs = new Map();

async function openPeriodFromSchedule(client, schedule) {
  try {
    const channel = await client.channels.fetch(schedule.channel_id);
    if (!channel) return;

    // لو فيه فترة مفتوحة أصلًا، لا نفتح وحدة جديدة فوقها
    const existing = queue.getOpenPeriod();
    if (existing) {
      console.log(`[جدولة] تخطي فتح جدول #${schedule.id} لأن فيه فترة مفتوحة بالفعل.`);
      return;
    }

    const period = queue.openPeriod({ channelId: schedule.channel_id, maxTickets: schedule.max_tickets });

    // انتظار 5 ثواني قبل إرسال البانل (حسب الفكرة الأصلية)
    await channel.send('⏰ **حان وقت فتح التفعيل!** يفتح الطابور خلال 5 ثواني...');
    await new Promise((res) => setTimeout(res, 5000));

    const embed = buildPanelEmbed(period);
    const row = buildPanelButtons();
    const msg = await channel.send({ embeds: [embed], components: [row] });

    queue.setPanelMessage(period.id, msg.id);
  } catch (err) {
    console.error('خطأ أثناء فتح فترة من الجدولة:', err);
  }
}

/** يبني cron expression من صف جدول */
function toCronExpression(schedule) {
  // node-cron: minute hour dayOfMonth month dayOfWeek
  return `${schedule.minute} ${schedule.hour} * * ${schedule.day_of_week}`;
}

function registerJob(client, schedule) {
  unregisterJob(schedule.id);
  if (!schedule.active) return;

  const task = cron.schedule(
    toCronExpression(schedule),
    () => openPeriodFromSchedule(client, schedule),
    { timezone: TIMEZONE }
  );
  activeJobs.set(schedule.id, task);
}

function unregisterJob(scheduleId) {
  const existing = activeJobs.get(scheduleId);
  if (existing) {
    existing.stop();
    activeJobs.delete(scheduleId);
  }
}

/** يحمّل كل الجداول من قاعدة البيانات ويسجلها كمهام cron (يُستدعى عند تشغيل البوت) */
function loadAllSchedules(client) {
  const schedules = db.prepare(`SELECT * FROM schedules WHERE active = 1`).all();
  for (const s of schedules) registerJob(client, s);
  console.log(`[جدولة] تم تحميل ${schedules.length} جدول (توقيت السعودية).`);
}

module.exports = { registerJob, unregisterJob, loadAllSchedules, TIMEZONE };
