import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    bot.tree.clear_commands(guild=None)   # يمسح كل الأوامر العالمية المسجلة
    await bot.tree.sync()                  # يزامن (يعني يصفّر) النسخة العالمية فعليًا
    print("✅ تم مسح كل الأوامر العالمية")
    await bot.close()

bot.run(os.getenv("DISCORD_TOKEN"))
