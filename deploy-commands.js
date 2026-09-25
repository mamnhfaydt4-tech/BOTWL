require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { REST, Routes } = require('discord.js');

const commands = [];
const commandsPath = path.join(__dirname, 'commands');
for (const file of fs.readdirSync(commandsPath).filter((f) => f.endsWith('.js'))) {
  const command = require(path.join(commandsPath, file));
  commands.push(command.data.toJSON());
}

const rest = new REST().setToken(process.env.DISCORD_TOKEN);

(async () => {
  try {
    const target = process.env.GUILD_ID
      ? Routes.applicationGuildCommands(process.env.CLIENT_ID, process.env.GUILD_ID)
      : Routes.applicationCommands(process.env.CLIENT_ID);

    await rest.put(target, { body: commands });
    console.log(`✅ تم نشر ${commands.length} أمر سلاش${process.env.GUILD_ID ? ' (على السيرفر المحدد فقط)' : ' (عالميًا، قد يأخذ للنشر حتى ساعة)'}.`);
  } catch (err) {
    console.error(err);
  }
})();
