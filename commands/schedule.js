const { SlashCommandBuilder, PermissionFlagsBits, EmbedBuilder, ChannelType } = require('discord.js');
const db = require('../database');
const { registerJob, unregisterJob } = require('../utils/scheduler');

// أيام الأسبوع بترقيم node-cron: 0 = الأحد ... 6 = السبت
const DAYS = [
  { name: 'الأحد', value: 0 },
  { name: 'الاثنين', value: 1 },
  { name: 'الثلاثاء', value: 2 },
  { name: 'الأربعاء', value: 3 },
  { name: 'الخميس', value: 4 },
  { name: 'الجمعة', value: 5 },
  { name: 'السبت', value: 6 },
];
const DAY_NAME = Object.fromEntries(DAYS.map((d) => [d.value, d.name]));

module.exports = {
  data: new SlashCommandBuilder()
    .setName('جدولة')
    .setDescription('إدارة الجدولة الأسبوعية لفتح التفعيل (بتوقيت السعودية)')
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addSubcommand((sub) =>
      sub
        .setName('اضافة')
        .setDescription('إضافة موعد أسبوعي جديد لفتح التفعيل')
        .addStringOption((opt) =>
          opt
            .setName('اليوم')
            .setDescription('يوم الأسبوع')
            .setRequired(true)
            .addChoices(...DAYS.map((d) => ({ name: d.name, value: String(d.value) })))
        )
        .addIntegerOption((opt) =>
          opt.setName('الساعة').setDescription('الساعة (0-23) بتوقيت السعودية').setRequired(true).setMinValue(0).setMaxValue(23)
        )
        .addIntegerOption((opt) =>
          opt.setName('الدقيقة').setDescription('الدقيقة (0-59)').setRequired(true).setMinValue(0).setMaxValue(59)
        )
        .addIntegerOption((opt) =>
          opt.setName('الحد_الأقصى').setDescription('أقصى عدد تذاكر لهذا الموعد').setRequired(true).setMinValue(1)
        )
        .addChannelOption((opt) =>
          opt
            .setName('الروم')
            .setDescription('روم نشر بانل التفعيل')
            .addChannelTypes(ChannelType.GuildText)
            .setRequired(true)
        )
    )
    .addSubcommand((sub) => sub.setName('عرض').setDescription('عرض كل الجداول الحالية'))
    .addSubcommand((sub) =>
      sub
        .setName('تعديل')
        .setDescription('تعديل جدول موجود')
        .addIntegerOption((opt) => opt.setName('id').setDescription('معرف الجدول (من أمر عرض)').setRequired(true))
        .addStringOption((opt) =>
          opt
            .setName('اليوم')
            .setDescription('يوم الأسبوع الجديد')
            .addChoices(...DAYS.map((d) => ({ name: d.name, value: String(d.value) })))
        )
        .addIntegerOption((opt) => opt.setName('الساعة').setDescription('الساعة الجديدة (0-23)').setMinValue(0).setMaxValue(23))
        .addIntegerOption((opt) => opt.setName('الدقيقة').setDescription('الدقيقة الجديدة (0-59)').setMinValue(0).setMaxValue(59))
        .addIntegerOption((opt) => opt.setName('الحد_الأقصى').setDescription('الحد الأقصى الجديد').setMinValue(1))
        .addChannelOption((opt) =>
          opt.setName('الروم').setDescription('الروم الجديد').addChannelTypes(ChannelType.GuildText)
        )
        .addBooleanOption((opt) => opt.setName('مفعل').setDescription('تفعيل أو إيقاف هذا الجدول مؤقتًا'))
    )
    .addSubcommand((sub) =>
      sub
        .setName('حذف')
        .setDescription('حذف جدول')
        .addIntegerOption((opt) => opt.setName('id').setDescription('معرف الجدول (من أمر عرض)').setRequired(true))
    ),

  async execute(interaction) {
    const sub = interaction.options.getSubcommand();

    if (sub === 'اضافة') {
      const day = Number(interaction.options.getString('اليوم'));
      const hour = interaction.options.getInteger('الساعة');
      const minute = interaction.options.getInteger('الدقيقة');
      const maxTickets = interaction.options.getInteger('الحد_الأقصى');
      const channel = interaction.options.getChannel('الروم');

      const info = db
        .prepare(
          `INSERT INTO schedules (day_of_week, hour, minute, max_tickets, channel_id) VALUES (?, ?, ?, ?, ?)`
        )
        .run(day, hour, minute, maxTickets, channel.id);

      const schedule = db.prepare(`SELECT * FROM schedules WHERE id = ?`).get(info.lastInsertRowid);
      registerJob(interaction.client, schedule);

      await interaction.reply({
        content: `✅ تمت إضافة الجدول #${schedule.id}: كل **${DAY_NAME[day]}** الساعة **${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}** بتوقيت السعودية، بروم ${channel}، بحد أقصى **${maxTickets}** تذكرة.`,
        ephemeral: true,
      });
    }

    if (sub === 'عرض') {
      const schedules = db.prepare(`SELECT * FROM schedules ORDER BY day_of_week, hour, minute`).all();
      if (schedules.length === 0) {
        return interaction.reply({ content: 'لا يوجد أي جداول حاليًا.', ephemeral: true });
      }

      const embed = new EmbedBuilder()
        .setTitle('🗓️ الجداول الأسبوعية (توقيت السعودية)')
        .setColor(0x5865f2)
        .setDescription(
          schedules
            .map(
              (s) =>
                `**#${s.id}** — ${DAY_NAME[s.day_of_week]} الساعة ${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')} | حد أقصى: ${s.max_tickets} | الروم: <#${s.channel_id}> | ${s.active ? '🟢 مفعّل' : '🔴 موقوف'}`
            )
            .join('\n')
        );

      await interaction.reply({ embeds: [embed], ephemeral: true });
    }

    if (sub === 'تعديل') {
      const id = interaction.options.getInteger('id');
      const existing = db.prepare(`SELECT * FROM schedules WHERE id = ?`).get(id);
      if (!existing) {
        return interaction.reply({ content: '❌ ما فيه جدول بهذا المعرف.', ephemeral: true });
      }

      const day = interaction.options.getString('اليوم');
      const hour = interaction.options.getInteger('الساعة');
      const minute = interaction.options.getInteger('الدقيقة');
      const maxTickets = interaction.options.getInteger('الحد_الأقصى');
      const channel = interaction.options.getChannel('الروم');
      const active = interaction.options.getBoolean('مفعل');

      const updated = {
        day_of_week: day !== null ? Number(day) : existing.day_of_week,
        hour: hour ?? existing.hour,
        minute: minute ?? existing.minute,
        max_tickets: maxTickets ?? existing.max_tickets,
        channel_id: channel ? channel.id : existing.channel_id,
        active: active === null ? existing.active : active ? 1 : 0,
      };

      db.prepare(
        `UPDATE schedules SET day_of_week = ?, hour = ?, minute = ?, max_tickets = ?, channel_id = ?, active = ? WHERE id = ?`
      ).run(updated.day_of_week, updated.hour, updated.minute, updated.max_tickets, updated.channel_id, updated.active, id);

      const fresh = db.prepare(`SELECT * FROM schedules WHERE id = ?`).get(id);
      if (fresh.active) registerJob(interaction.client, fresh);
      else unregisterJob(id);

      await interaction.reply({ content: `✅ تم تحديث الجدول #${id}.`, ephemeral: true });
    }

    if (sub === 'حذف') {
      const id = interaction.options.getInteger('id');
      const existing = db.prepare(`SELECT * FROM schedules WHERE id = ?`).get(id);
      if (!existing) {
        return interaction.reply({ content: '❌ ما فيه جدول بهذا المعرف.', ephemeral: true });
      }
      db.prepare(`DELETE FROM schedules WHERE id = ?`).run(id);
      unregisterJob(id);
      await interaction.reply({ content: `🗑️ تم حذف الجدول #${id}.`, ephemeral: true });
    }
  },
};
