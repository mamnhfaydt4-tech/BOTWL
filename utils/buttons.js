const { ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');

function buildPanelButtons() {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('take_ticket').setLabel('أخذ تذكرة').setEmoji('🎫').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId('my_ticket').setLabel('تذكرتي').setEmoji('📋').setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId('queue_status').setLabel('حالة الطابور').setEmoji('📊').setStyle(ButtonStyle.Secondary)
  );
}

function buildTicketButtons(ticketId, { claimed }) {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(`claim_${ticketId}`)
      .setLabel('استلام')
      .setEmoji('✅')
      .setStyle(ButtonStyle.Primary)
      .setDisabled(!!claimed),
    new ButtonBuilder().setCustomId(`close_${ticketId}`).setLabel('إغلاق').setEmoji('🔒').setStyle(ButtonStyle.Danger)
  );
}

module.exports = { buildPanelButtons, buildTicketButtons };
