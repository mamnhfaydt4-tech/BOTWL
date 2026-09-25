const {
  PermissionFlagsBits,
  ChannelType,
  ModalBuilder,
  TextInputBuilder,
  TextInputStyle,
  ActionRowBuilder,
} = require('discord.js');
const queue = require('../utils/queue');
const {
  buildPanelEmbed,
  buildTicketEmbed,
  buildMyTicketEmbed,
  buildQueueStatusEmbed,
  buildTicketLogEmbed,
} = require('../utils/embeds');
const { buildTicketButtons } = require('../utils/buttons');

const STAFF_ROLE_ID = process.env.STAFF_ROLE_ID;
const TICKET_CATEGORY_ID = process.env.TICKET_CATEGORY_ID;
const TICKET_LOG_CHANNEL_ID = process.env.TICKET_LOG_CHANNEL_ID;

function isStaff(member) {
  return STAFF_ROLE_ID ? member.roles.cache.has(STAFF_ROLE_ID) : member.permissions.has(PermissionFlagsBits.ManageGuild);
}

/** يحدّث رسالة البانل بالعداد الحالي */
async function refreshPanel(client, period) {
  try {
    if (!period.panel_message_id) return;
    const channel = await client.channels.fetch(period.channel_id);
    const msg = await channel.messages.fetch(period.panel_message_id);
    const fresh = queue.getPeriod(period.id);
    await msg.edit({ embeds: [buildPanelEmbed(fresh)] });
  } catch (err) {
    console.error('تعذر تحديث البانل:', err.message);
  }
}

module.exports = {
  name: 'interactionCreate',
  async execute(interaction) {
    // ===== أوامر السلاش =====
    if (interaction.isChatInputCommand()) {
      const command = interaction.client.commands.get(interaction.commandName);
      if (!command) return;
      try {
        await command.execute(interaction);
      } catch (err) {
        console.error(err);
        const payload = { content: '❌ صار خطأ أثناء تنفيذ الأمر.', ephemeral: true };
        if (interaction.replied || interaction.deferred) await interaction.followUp(payload);
        else await interaction.reply(payload);
      }
      return;
    }

    // ===== إرسال مودال سبب الإغلاق =====
    if (interaction.isModalSubmit() && interaction.customId.startsWith('close_reason_')) {
      const ticketId = Number(interaction.customId.split('_')[2]);
      const reason = interaction.fields.getTextInputValue('reason').trim();

      let ticket;
      try {
        ticket = queue.closeTicket(ticketId, interaction.user.id, reason);
      } catch (err) {
        if (err.message === 'ALREADY_CLOSED') {
          return interaction.reply({ content: 'ℹ️ هذه التذكرة مغلقة بالفعل.', ephemeral: true });
        }
        console.error(err);
        return interaction.reply({ content: '❌ صار خطأ أثناء الإغلاق.', ephemeral: true });
      }

      await interaction.reply({ embeds: [buildTicketEmbed(ticket)] });

      const period = queue.getPeriod(ticket.period_id);
      await refreshPanel(interaction.client, period);

      // إرسال اللوق
      if (TICKET_LOG_CHANNEL_ID) {
        try {
          const logChannel = await interaction.client.channels.fetch(TICKET_LOG_CHANNEL_ID);
          await logChannel.send({ embeds: [buildTicketLogEmbed(ticket)] });
        } catch (err) {
          console.error('تعذر إرسال اللوق:', err.message);
        }
      }

      setTimeout(async () => {
        try {
          const channel = await interaction.guild.channels.fetch(ticket.channel_id);
          await channel.delete('تم إغلاق التذكرة');
        } catch (_) {
          /* الروم محذوف مسبقًا أو لا صلاحية */
        }
      }, 5000);
      return;
    }

    if (!interaction.isButton()) return;

    // ===== زر: أخذ تذكرة =====
    if (interaction.customId === 'take_ticket') {
      const period = queue.getOpenPeriod();
      if (!period) {
        return interaction.reply({ content: '❌ التفعيل مقفول حاليًا.', ephemeral: true });
      }

      let ticket;
      try {
        ticket = queue.issueTicket({ periodId: period.id, userId: interaction.user.id });
      } catch (err) {
        return interaction.reply({ content: `❌ ${err.message}`, ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      try {
        const guild = interaction.guild;
        const overwrites = [
          { id: guild.roles.everyone, deny: [PermissionFlagsBits.ViewChannel] },
          {
            id: interaction.user.id,
            allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory],
          },
        ];
        if (STAFF_ROLE_ID) {
          overwrites.push({
            id: STAFF_ROLE_ID,
            allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory],
          });
        }

        const ticketChannel = await guild.channels.create({
          name: `تفعيل-${ticket.ticket_number}`,
          type: ChannelType.GuildText,
          parent: TICKET_CATEGORY_ID || undefined,
          permissionOverwrites: overwrites,
        });

        queue.setTicketChannel(ticket.id, ticketChannel.id);
        const fresh = queue.getTicket(ticket.id);

        await ticketChannel.send({
          content: `مرحبًا <@${interaction.user.id}>${STAFF_ROLE_ID ? ` — <@&${STAFF_ROLE_ID}>` : ''}`,
          embeds: [buildTicketEmbed(fresh)],
          components: [buildTicketButtons(ticket.id, { claimed: false })],
        });

        await interaction.editReply({ content: `✅ تم إنشاء تذكرتك #${ticket.ticket_number} في ${ticketChannel}.` });

        await refreshPanel(interaction.client, period);
      } catch (err) {
        console.error(err);
        await interaction.editReply({ content: '❌ صار خطأ أثناء إنشاء روم التذكرة. تواصل مع الإدارة.' });
      }
      return;
    }

    // ===== زر: تذكرتي =====
    if (interaction.customId === 'my_ticket') {
      const period = queue.getOpenPeriod();
      if (!period) {
        return interaction.reply({ content: '❌ لا يوجد تفعيل مفتوح حاليًا.', ephemeral: true });
      }
      const ticket = queue.getUserOpenTicket(period.id, interaction.user.id);
      return interaction.reply({ embeds: [buildMyTicketEmbed(ticket)], ephemeral: true });
    }

    // ===== زر: حالة الطابور =====
    if (interaction.customId === 'queue_status') {
      const period = queue.getOpenPeriod();
      if (!period) {
        return interaction.reply({ content: '❌ لا يوجد تفعيل مفتوح حاليًا.', ephemeral: true });
      }
      return interaction.reply({ embeds: [buildQueueStatusEmbed(period)], ephemeral: true });
    }

    // ===== زر: استلام (مخصص للإدارة فقط، عملية ذرية بدون أي احتمال تعارض) =====
    if (interaction.customId.startsWith('claim_')) {
      if (!isStaff(interaction.member)) {
        return interaction.reply({ content: '❌ هذا الزر مخصص للإدارة فقط.', ephemeral: true });
      }

      const ticketId = Number(interaction.customId.split('_')[1]);

      let ticket;
      try {
        // فحص الترتيب + التحديث يصيران معًا كوحدة واحدة غير قابلة للمقاطعة (transaction).
        // مستحيل يستلم إداريان نفس التذكرة أو يتجاوزون الترتيب حتى لو ضغطوا بنفس اللحظة.
        ticket = queue.claimTicket(ticketId, interaction.user.id);
      } catch (err) {
        if (err.message === 'NOT_FOUND') {
          return interaction.reply({ content: '❌ لم يتم العثور على هذه التذكرة.', ephemeral: true });
        }
        if (err.message === 'ALREADY_CLAIMED') {
          return interaction.reply({ content: 'ℹ️ هذه التذكرة تم استلامها بالفعل من إداري آخر.', ephemeral: true });
        }
        if (err.message.startsWith('BLOCKED:')) {
          const num = err.message.split(':')[1];
          return interaction.reply({
            content: `⏳ لسا ما وصل دور هذه التذكرة. لازم تُستلم التذكرة **#${num}** أولًا.`,
            ephemeral: true,
          });
        }
        console.error(err);
        return interaction.reply({ content: '❌ صار خطأ غير متوقع.', ephemeral: true });
      }

      await interaction.update({
        embeds: [buildTicketEmbed(ticket)],
        components: [buildTicketButtons(ticketId, { claimed: true })],
      });

      await interaction.followUp({
        content: `✅ تم استلام التذكرة بواسطة <@${interaction.user.id}>.`,
      });

      const period = queue.getPeriod(ticket.period_id);
      await refreshPanel(interaction.client, period);
      return;
    }

    // ===== زر: إغلاق — مخصص للإدارة فقط، ويفتح مودال لكتابة سبب إلزامي =====
    if (interaction.customId.startsWith('close_')) {
      if (!isStaff(interaction.member)) {
        return interaction.reply({ content: '❌ إغلاق التذكرة مخصص للإدارة فقط.', ephemeral: true });
      }

      const ticketId = Number(interaction.customId.split('_')[1]);
      const ticket = queue.getTicket(ticketId);
      if (!ticket) return interaction.reply({ content: '❌ لم يتم العثور على هذه التذكرة.', ephemeral: true });
      if (ticket.status === 'closed') {
        return interaction.reply({ content: 'ℹ️ هذه التذكرة مغلقة بالفعل.', ephemeral: true });
      }

      const modal = new ModalBuilder()
        .setCustomId(`close_reason_${ticketId}`)
        .setTitle(`إغلاق التذكرة #${ticket.ticket_number}`);

      const reasonInput = new TextInputBuilder()
        .setCustomId('reason')
        .setLabel('سبب الإغلاق')
        .setStyle(TextInputStyle.Paragraph)
        .setRequired(true)
        .setMinLength(3)
        .setMaxLength(500)
        .setPlaceholder('اكتب سبب إغلاق هذه التذكرة...');

      modal.addComponents(new ActionRowBuilder().addComponents(reasonInput));

      await interaction.showModal(modal);
      return;
    }
  },
};
