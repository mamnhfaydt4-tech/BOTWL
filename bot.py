"""
Discord Bot - نظام التفعيل عبر Discord
يتصل مباشرة بـ Roblox DataStore عبر Open Cloud API
"""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()

# ============ الإعدادات ============
DISCORD_TOKEN       = os.getenv("DISCORD_TOKEN")
ROBLOX_API_KEY      = os.getenv("ROBLOX_API_KEY")        # مفتاح Open Cloud
UNIVERSE_ID         = os.getenv("UNIVERSE_ID")           # Universe ID للعبة
DATASTORE_NAME      = "ActivatedPlayers_V3"
DATASTORE_KEY       = "AllData"
OWNER_DISCORD_ID    = int(os.getenv("OWNER_DISCORD_ID", "0"))  # Discord ID حقك
ADMIN_ROLE_NAME     = os.getenv("ADMIN_ROLE_NAME", "Admin")    # اسم الرول في سيرفرك

# رابط Open Cloud API
BASE_URL = f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}/standard-datastores"

# ============ دوال DataStore ============

async def read_datastore():
    """قراءة البيانات من Roblox DataStore"""
    url = f"{BASE_URL}/datastore/entries/entry"
    params = {
        "datastoreName": DATASTORE_NAME,
        "entryKey": DATASTORE_KEY
    }
    headers = {
        "x-api-key": ROBLOX_API_KEY
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                text = await resp.text()
                return json.loads(text)
            elif resp.status == 404:
                # DataStore فاضي
                return {"activated": [], "admins": []}
            else:
                error = await resp.text()
                raise Exception(f"خطأ في القراءة: {resp.status} - {error}")


async def write_datastore(data: dict):
    """كتابة البيانات إلى Roblox DataStore"""
    import hashlib, base64

    url = f"{BASE_URL}/datastore/entries/entry"
    params = {
        "datastoreName": DATASTORE_NAME,
        "entryKey": DATASTORE_KEY
    }
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "content-type": "application/json"
    }

    content = json.dumps(data)

    # Roblox يطلب MD5 hash مشفر بـ base64
    md5 = base64.b64encode(hashlib.md5(content.encode()).digest()).decode()
    headers["content-md5"] = md5

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params, headers=headers, data=content) as resp:
            if resp.status not in (200, 201):
                error = await resp.text()
                raise Exception(f"خطأ في الكتابة: {resp.status} - {error}")
            return True


# ============ إعداد البوت ============

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_DISCORD_ID


def is_admin(interaction: discord.Interaction) -> bool:
    if is_owner(interaction):
        return True
    return any(role.name == ADMIN_ROLE_NAME for role in interaction.user.roles)


# ============ الأوامر (Slash Commands) ============

@tree.command(name="تفعيل", description="تفعيل لاعب في اللعبة")
@app_commands.describe(username="اسم اللاعب في Roblox")
async def activate(interaction: discord.Interaction, username: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        data = await read_datastore()
        activated = data.get("activated", [])
        admins = data.get("admins", [])

        username = username.strip()

        # التحقق من التفعيل المسبق
        if any(n.strip().lower() == username.lower() for n in activated):
            await interaction.followup.send(f"⚠️ **{username}** مفعل مسبقاً!")
            return

        activated.append(username)
        await write_datastore({"activated": activated, "admins": admins})

        embed = discord.Embed(
            title="✅ تم التفعيل",
            description=f"**اللاعب:** {username}\n**بواسطة:** {interaction.user.mention}\n**إجمالي المفعلين:** {len(activated)}",
            color=0x00ff00
        )
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {str(e)}")


@tree.command(name="الغاء_تفعيل", description="إلغاء تفعيل لاعب من اللعبة")
@app_commands.describe(username="اسم اللاعب في Roblox")
async def deactivate(interaction: discord.Interaction, username: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        data = await read_datastore()
        activated = data.get("activated", [])
        admins = data.get("admins", [])

        username = username.strip()

        # البحث عن اللاعب
        found = None
        for name in activated:
            if name.strip().lower() == username.lower():
                found = name
                break

        if not found:
            await interaction.followup.send(f"⚠️ **{username}** غير مفعل!")
            return

        activated.remove(found)
        await write_datastore({"activated": activated, "admins": admins})

        embed = discord.Embed(
            title="❌ تم إلغاء التفعيل",
            description=f"**اللاعب:** {username}\n**بواسطة:** {interaction.user.mention}",
            color=0xff0000
        )
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {str(e)}")


@tree.command(name="اضافة_اداري", description="تعيين لاعب كإداري [المالك فقط]")
@app_commands.describe(username="اسم اللاعب في Roblox")
async def add_admin(interaction: discord.Interaction, username: str):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ فقط المالك يمكنه إضافة إداريين!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        data = await read_datastore()
        activated = data.get("activated", [])
        admins = data.get("admins", [])

        username = username.strip()

        if any(n.strip().lower() == username.lower() for n in admins):
            await interaction.followup.send(f"⚠️ **{username}** إداري مسبقاً!")
            return

        # تفعيل تلقائي إذا لم يكن مفعلاً
        if not any(n.strip().lower() == username.lower() for n in activated):
            activated.append(username)

        admins.append(username)
        await write_datastore({"activated": activated, "admins": admins})

        embed = discord.Embed(
            title="⭐ تم تعيين إداري",
            description=f"**الإداري:** {username}\n**بواسطة:** {interaction.user.mention}",
            color=0xffa500
        )
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {str(e)}")


@tree.command(name="ازالة_اداري", description="إزالة لاعب من الإداريين [المالك فقط]")
@app_commands.describe(username="اسم اللاعب في Roblox")
async def remove_admin(interaction: discord.Interaction, username: str):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ فقط المالك يمكنه إزالة الإداريين!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        data = await read_datastore()
        activated = data.get("activated", [])
        admins = data.get("admins", [])

        username = username.strip()

        found = None
        for name in admins:
            if name.strip().lower() == username.lower():
                found = name
                break

        if not found:
            await interaction.followup.send(f"⚠️ **{username}** ليس إدارياً!")
            return

        admins.remove(found)
        await write_datastore({"activated": activated, "admins": admins})

        embed = discord.Embed(
            title="⚠️ تم إزالة الإداري",
            description=f"**الإداري:** {username}\n**بواسطة:** {interaction.user.mention}",
            color=0xff6600
        )
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {str(e)}")


@tree.command(name="القوائم", description="عرض قوائم المفعلين والإداريين")
async def list_players(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        data = await read_datastore()
        activated = data.get("activated", [])
        admins = data.get("admins", [])

        activated_text = "\n".join(f"`{i+1}.` {n}" for i, n in enumerate(activated)) or "لا يوجد"
        admins_text = "\n".join(f"`{i+1}.` {n}" for i, n in enumerate(admins)) or "لا يوجد"

        embed = discord.Embed(title="📋 قوائم النظام", color=0x5865F2)
        embed.add_field(
            name=f"✅ المفعلين ({len(activated)})",
            value=activated_text[:1024],
            inline=False
        )
        embed.add_field(
            name=f"⭐ الإداريين ({len(admins)})",
            value=admins_text[:1024],
            inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {str(e)}", ephemeral=True)


@tree.command(name="مساعدة", description="عرض قائمة الأوامر")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 أوامر البوت",
        description="أوامر نظام التفعيل عبر Discord",
        color=0x5865F2
    )
    embed.add_field(name="✅ `/تفعيل [اسم]`", value="تفعيل لاعب في اللعبة", inline=False)
    embed.add_field(name="❌ `/الغاء_تفعيل [اسم]`", value="إلغاء تفعيل لاعب", inline=False)
    embed.add_field(name="⭐ `/اضافة_اداري [اسم]`", value="تعيين إداري (المالك فقط)", inline=False)
    embed.add_field(name="⚠️ `/ازالة_اداري [اسم]`", value="إزالة إداري (المالك فقط)", inline=False)
    embed.add_field(name="📋 `/القوائم`", value="عرض جميع المفعلين والإداريين", inline=False)
    embed.set_footer(text="البوت يكتب مباشرة في DataStore — مستقل تماماً عن الماب")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============ تشغيل البوت ============

@bot.event
async def on_ready():
    await tree.sync()  # مزامنة الأوامر مع Discord
    print(f"✅ البوت جاهز: {bot.user}")
    print(f"🌐 Universe ID: {UNIVERSE_ID}")
    print(f"📦 DataStore: {DATASTORE_NAME}")


bot.run(DISCORD_TOKEN)
