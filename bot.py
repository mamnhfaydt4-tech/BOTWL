"""
Discord Bot - نظام التفعيل (Roblox + Discord)
- التفعيل يتطلب يوزر روبلوكس + حساب ديسكورد
- الكتابة في Roblox DataStore عبر Open Cloud مع حماية من التعارض (matchVersion)
- رتبة التفعيل شرط: لو انسحبت الرتبة أو خرج من السيرفر يتلغى التفعيل تلقائياً
"""

import asyncio
import logging
import json
import os
import re
import time
import base64
import hashlib
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("activation")


# ============ الإعدادات ============

def _int(name: str) -> int:
    try:
        return int(os.getenv(name, "0").strip())
    except ValueError:
        return 0


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")
UNIVERSE_ID = os.getenv("UNIVERSE_ID")

OWNER_DISCORD_ID = _int("OWNER_DISCORD_ID")
GUILD_ID = _int("GUILD_ID")                    # آيدي سيرفرك
ADMIN_ROLE_ID = _int("ADMIN_ROLE_ID")          # رتبة الإداريين (بالآيدي وليس الاسم)
ACTIVE_ROLE_ID = _int("ACTIVE_ROLE_ID")        # رتبة "مفعّل" الإلزامية
REMOVE_ROLE_IDS = [
    int(x) for x in os.getenv("REMOVE_ROLE_IDS", "").replace(" ", "").split(",") if x.isdigit()
]                                               # الرتبتين اللي تنسحب عند التفعيل
FORM_CHANNEL_ID = _int("FORM_CHANNEL_ID")      # روم نموذج التفعيل / الإلغاء
LOG_CHANNEL_ID = _int("LOG_CHANNEL_ID")        # روم اللوق الاحتياطي

DATASTORE_NAME = "ActivatedPlayers_V4"
DATASTORE_KEY = "AllData"

_required = {
    "DISCORD_TOKEN": DISCORD_TOKEN, "ROBLOX_API_KEY": ROBLOX_API_KEY, "UNIVERSE_ID": UNIVERSE_ID,
    "OWNER_DISCORD_ID": OWNER_DISCORD_ID, "GUILD_ID": GUILD_ID, "ADMIN_ROLE_ID": ADMIN_ROLE_ID,
    "ACTIVE_ROLE_ID": ACTIVE_ROLE_ID, "FORM_CHANNEL_ID": FORM_CHANNEL_ID, "LOG_CHANNEL_ID": LOG_CHANNEL_ID,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    raise SystemExit(f"❌ متغيرات ناقصة في .env: {', '.join(_missing)}")

ENTRY_URL = (
    f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}"
    "/standard-datastores/datastore/entries/entry"
)
GUILD_OBJ = discord.Object(id=GUILD_ID)
REASON_MAX = 300
ROBLOX_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
NO_MENTIONS = discord.AllowedMentions.none()


# ============ أخطاء ============

class UserError(Exception):
    """خطأ يُعرض للإداري كما هو."""


class DataStoreError(Exception):
    pass


class VersionConflict(DataStoreError):
    pass


# ============ DataStore ============
# شكل البيانات:
# {"players": {"<robloxUserId>": {robloxId, robloxName, discordId, reason, by, ts}}}

_ds_lock = asyncio.Lock()


def _empty() -> dict:
    return {"players": {}}


async def ds_read(session: aiohttp.ClientSession):
    params = {"datastoreName": DATASTORE_NAME, "entryKey": DATASTORE_KEY}
    headers = {"x-api-key": ROBLOX_API_KEY}
    async with session.get(ENTRY_URL, params=params, headers=headers) as resp:
        if resp.status == 200:
            version = resp.headers.get("roblox-entry-version")
            try:
                data = json.loads(await resp.text())
            except ValueError:
                raise DataStoreError("بيانات DataStore تالفة")
            if not isinstance(data, dict):
                raise DataStoreError("بيانات DataStore بصيغة غير متوقعة")
            if not isinstance(data.get("players"), dict):
                data["players"] = {}
            return data, version
        if resp.status == 404:
            return _empty(), None
        raise DataStoreError(f"قراءة فاشلة: {resp.status} - {(await resp.text())[:200]}")


async def ds_write(session: aiohttp.ClientSession, data: dict, version: Optional[str]):
    params = {"datastoreName": DATASTORE_NAME, "entryKey": DATASTORE_KEY}
    if version:
        params["matchVersion"] = version        # لا تكتب إلا إذا ما تغيّرت البيانات
    else:
        params["exclusiveCreate"] = "true"      # أول إنشاء فقط
    content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    body = content.encode("utf-8")
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "content-type": "application/json",
        "content-md5": base64.b64encode(hashlib.md5(body).digest()).decode(),
    }
    async with session.post(ENTRY_URL, params=params, headers=headers, data=body) as resp:
        if resp.status in (200, 201):
            return
        if resp.status in (409, 412):
            raise VersionConflict()
        raise DataStoreError(f"كتابة فاشلة: {resp.status} - {(await resp.text())[:200]}")


async def mutate(fn):
    """قراءة -> تعديل -> كتابة مع إعادة المحاولة عند التعارض. fn يعدّل data ويرجع نتيجة."""
    async with _ds_lock:
        for attempt in range(6):
            data, version = await ds_read(bot.http_session)
            result = fn(data)
            try:
                await ds_write(bot.http_session, data, version)
                return result
            except VersionConflict:
                await asyncio.sleep(0.3 * (attempt + 1))
        raise DataStoreError("تعذّرت الكتابة بسبب تعارض متكرر، حاول مرة أخرى")


# ============ Roblox API ============

async def resolve_roblox(username: str):
    """يرجّع (userId, الاسم الصحيح) أو None إذا ما وُجد."""
    if not ROBLOX_NAME_RE.match(username):
        raise UserError("يوزر روبلوكس غير صالح (3-20 حرف: أحرف إنجليزية/أرقام/_)")
    payload = {"usernames": [username], "excludeBannedUsers": False}
    try:
        async with bot.http_session.post(
            "https://users.roblox.com/v1/usernames/users", json=payload
        ) as resp:
            if resp.status != 200:
                raise UserError("تعذّر التحقق من يوزر روبلوكس الآن، حاول بعد شوي")
            js = await resp.json()
    except aiohttp.ClientError:
        raise UserError("تعذّر الاتصال بـ Roblox، حاول بعد شوي")
    if not js.get("data"):
        return None
    u = js["data"][0]
    return int(u["id"]), str(u["name"])


# ============ البوت ============

class ActivationBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # لازم يكون مفعّل في Developer Portal
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.http_session: aiohttp.ClientSession = None  # type: ignore
        self.pending: set[int] = set()  # ديسكورد IDs قيد التفعيل (تجاهل الفحص التلقائي)

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        reconcile_loop.start()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()


bot = ActivationBot()
tree = bot.tree


# ============ صلاحيات ============

def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild_id != GUILD_ID:
        return False
    if interaction.user.id == OWNER_DISCORD_ID:
        return True
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)


# ============ مساعدات ============

def clean_reason(text: str) -> str:
    text = " ".join(text.split())
    text = discord.utils.escape_mentions(text)
    if len(text) < 2:
        raise UserError("السبب قصير جداً")
    return text[:REASON_MAX]


async def post_to(channel_id: int, embed: discord.Embed):
    try:
        ch = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        await ch.send(embed=embed, allowed_mentions=NO_MENTIONS)
    except Exception as e:
        log.error("فشل الإرسال إلى الروم %s: %s", channel_id, e)


def activation_result_embed(by_mention, rec, member_mention, kind_label):
    e = discord.Embed(title="✅ تم تفعيل الشخص", color=0x2ECC71, timestamp=discord.utils.utcnow())
    e.add_field(name="يوزر روبلوكس", value=f"`{rec['robloxName']}` (ID: {rec['robloxId']})", inline=False)
    e.add_field(name="حساب الديسكورد", value=member_mention, inline=False)
    e.add_field(name="بواسطة", value=by_mention, inline=False)
    e.add_field(name="نوع التفعيل", value=kind_label, inline=False)
    e.add_field(name="السبب", value=rec["reason"], inline=False)
    return e


def activation_form_embed(by_mention, rec, member_mention):
    e = discord.Embed(title="نموذج التفعيل", color=0x2ECC71, timestamp=discord.utils.utcnow())
    e.add_field(name="اسم الشخص الذي فعّله", value=by_mention, inline=False)
    e.add_field(name="يوزر الشخص روبلوكس", value=rec["robloxName"], inline=False)
    e.add_field(name="يوزر الشخص ديسكورد", value=member_mention, inline=False)
    e.add_field(name="سبب التفعيل", value=rec["reason"], inline=False)
    return e


def deactivation_result_embed(by_mention, rec, member_mention, reason):
    e = discord.Embed(title="❌ تم إلغاء تفعيل الشخص", color=0xE74C3C, timestamp=discord.utils.utcnow())
    e.add_field(name="يوزر روبلوكس", value=f"`{rec['robloxName']}` (ID: {rec['robloxId']})", inline=False)
    e.add_field(name="حساب الديسكورد", value=member_mention, inline=False)
    e.add_field(name="بواسطة", value=by_mention, inline=False)
    e.add_field(name="سبب الإلغاء", value=reason, inline=False)
    return e


def deactivation_form_embed(by_mention, rec, member_mention, reason):
    e = discord.Embed(title="نموذج إلغاء تفعيل", color=0xE74C3C, timestamp=discord.utils.utcnow())
    e.add_field(name="اسم الإداري", value=by_mention, inline=False)
    e.add_field(name="يوزر الشخص روبلوكس", value=rec["robloxName"], inline=False)
    e.add_field(name="يوزر الشخص ديسكورد", value=member_mention, inline=False)
    e.add_field(name="سبب إلغاء التفعيل", value=reason, inline=False)
    return e


async def get_member(guild: discord.Guild, user_id: int):
    """يرجّع Member أو None إذا خرج. أي خطأ آخر يُرفع."""
    m = guild.get_member(user_id)
    if m:
        return m
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


# ============ رسائل الخاص ============

DM_ACTIVATED = (
    "🎉 **تم تفعيل حسابك بنجاح!**\n\n"
    "**مرحبًا بك {mention}،**\n"
    "تم اعتماد وتفعيل صلاحية دخولك إلى **WL Emergency** بنجاح. ✅\n\n"
    "يمكنك الآن الدخول إلى الماب والاستفادة من الصلاحيات المخصصة لك.\n\n"
    "نتمنى لك تجربة ممتعة، ونراك داخل المدينة! 🚨💜\n\n"
    "**WL Emergency | الإدارة**"
)

DM_DEACTIVATED = (
    "⚠️ **تم إلغاء تفعيل حسابك!**\n\n"
    "**مرحبًا بك {mention}،**\n"
    "تم إلغاء صلاحية دخولك إلى **WL Emergency** بنجاح. ❌\n\n"
    "📋 **سبب إلغاء التفعيل:**\n"
    "{reason}\n\n"
    "لم يعد بإمكانك الدخول إلى الماب أو الاستفادة من الصلاحيات المخصصة لك.\n\n"
    "في حال كان لديك أي استفسار، يمكنك التواصل مع إدارة الماب. 📩\n\n"
    "**WL Emergency | الإدارة**"
)


async def send_dm(user_id: int, template: str, **kwargs) -> bool:
    """يرسل رسالة خاصة. يرجّع False إذا الخاص مقفول أو تعذّر الإرسال."""
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        text = template.format(mention=f"<@{user_id}>", **kwargs)
        await user.send(text[:2000], allowed_mentions=NO_MENTIONS)
        return True
    except discord.Forbidden:
        log.info("الخاص مقفول عند %s", user_id)
    except Exception as e:
        log.warning("فشل إرسال الخاص إلى %s: %s", user_id, e)
    return False


DM_FAIL_NOTE = "⚠️ تعذّر إرسال رسالة الخاص (الخاص مقفول عند الشخص)"


# ============ منطق التفعيل ============

REASON_LABELS = {"normal": "التفعيل الطبيعي", "instant": "تفعيل فوري", "other": "سبب آخر"}


async def run_activation(interaction: discord.Interaction, roblox_username: str,
                         member: discord.Member, kind: str, reason_text: str):
    """يفترض أن interaction تم عمل defer له."""
    guild = interaction.guild
    try:
        if guild is None or guild.id != GUILD_ID:
            raise UserError("هذا الأمر يعمل فقط في السيرفر الرسمي")
        if member.bot:
            raise UserError("ما تقدر تفعّل بوت")
        reason = clean_reason(reason_text)

        resolved = await resolve_roblox(roblox_username.strip())
        if not resolved:
            raise UserError("ما لقيت هذا اليوزر في روبلوكس، تأكد من الكتابة")
        rid, rname = resolved

        active_role = guild.get_role(ACTIVE_ROLE_ID)
        if active_role is None:
            raise UserError("رتبة التفعيل غير موجودة، تأكد من ACTIVE_ROLE_ID")
        remove_roles = [r for r in (guild.get_role(i) for i in REMOVE_ROLE_IDS)
                        if r is not None and r in member.roles]

        me = guild.me
        if not me.guild_permissions.manage_roles:
            raise UserError("البوت ما عنده صلاحية Manage Roles")
        for r in [active_role] + remove_roles:
            if r.managed or r >= me.top_role:
                raise UserError(f"رتبة البوت لازم تكون أعلى من الرتبة **{r.name}**")

        # فحص مسبق (بدون كتابة) عشان ما نعطي رتب لشخص مرفوض
        data, _ = await ds_read(bot.http_session)
        for rec in data["players"].values():
            if int(rec.get("robloxId", 0)) == rid:
                raise UserError(f"**{rname}** مفعّل مسبقاً")
            if str(rec.get("discordId")) == str(member.id):
                raise UserError("حساب الديسكورد هذا مفعّل مسبقاً على حساب روبلوكس آخر")

        record = {
            "robloxId": rid, "robloxName": rname, "discordId": str(member.id),
            "reason": reason, "by": str(interaction.user.id), "ts": int(time.time()),
        }

        def add_fn(d):
            for rec in d["players"].values():
                if int(rec.get("robloxId", 0)) == rid:
                    raise UserError(f"**{rname}** مفعّل مسبقاً")
                if str(rec.get("discordId")) == str(member.id):
                    raise UserError("حساب الديسكورد هذا مفعّل مسبقاً على حساب روبلوكس آخر")
            d["players"][str(rid)] = record

        audit = f"تفعيل بواسطة {interaction.user} ({interaction.user.id})"
        bot.pending.add(member.id)
        roles_changed = False
        try:
            try:
                await member.add_roles(active_role, reason=audit)
                roles_changed = True
                if remove_roles:
                    await member.remove_roles(*remove_roles, reason=audit)
                await mutate(add_fn)
            except Exception:
                # تراجع كامل عن الرتب
                if roles_changed:
                    try:
                        await member.remove_roles(active_role, reason="تراجع: فشل التفعيل")
                        if remove_roles:
                            await member.add_roles(*remove_roles, reason="تراجع: فشل التفعيل")
                    except Exception as rb:
                        log.error("فشل التراجع عن الرتب: %s", rb)
                raise
        finally:
            bot.pending.discard(member.id)

    except UserError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return
    except discord.Forbidden:
        await interaction.followup.send("❌ البوت ما يقدر يعدّل رتب هذا الشخص (تحقق من ترتيب الرتب)")
        return
    except DataStoreError as e:
        log.error("DataStore: %s", e)
        await interaction.followup.send("❌ فشل الحفظ في DataStore، ما تم التفعيل. حاول مرة أخرى")
        return
    except Exception:
        log.exception("خطأ غير متوقع في التفعيل")
        await interaction.followup.send("❌ صار خطأ غير متوقع، ما تم التفعيل")
        return

    by, mm = interaction.user.mention, member.mention
    result = activation_result_embed(by, record, mm, REASON_LABELS[kind])
    if not await send_dm(member.id, DM_ACTIVATED):
        result.set_footer(text=DM_FAIL_NOTE)
    await interaction.followup.send(embed=result, allowed_mentions=NO_MENTIONS)
    await post_to(LOG_CHANNEL_ID, result)
    await post_to(FORM_CHANNEL_ID, activation_form_embed(by, record, mm))


# ============ منطق إلغاء التفعيل ============

async def remove_record(rid: Optional[int], lname: Optional[str], did: Optional[int]):
    """يحذف سجل مطابق لكل المعلومات المعطاة. يرجّع السجل."""
    def fn(d):
        for key, rec in d["players"].items():
            ok = True
            if rid is not None or lname:
                name_ok = (rid is not None and int(rec.get("robloxId", 0)) == rid) or \
                          (lname and str(rec.get("robloxName", "")).lower() == lname)
                ok = ok and bool(name_ok)
            if did is not None:
                ok = ok and str(rec.get("discordId")) == str(did)
            if ok:
                return d["players"].pop(key)
        raise UserError("ما لقيت شخص مفعّل بهذه المعلومات")
    return await mutate(fn)


async def finish_deactivation(by_mention: str, rec: dict, reason: str, guild: discord.Guild,
                              strip_role: bool):
    did = int(rec["discordId"])
    member = None
    try:
        member = await get_member(guild, did)
    except Exception as e:
        log.warning("تعذّر جلب العضو %s: %s", did, e)
    if strip_role and member:
        role = guild.get_role(ACTIVE_ROLE_ID)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"إلغاء تفعيل: {reason[:100]}")
            except Exception as e:
                log.error("فشل سحب رتبة التفعيل: %s", e)
    mm = member.mention if member else f"<@{did}>"
    result = deactivation_result_embed(by_mention, rec, mm, reason)
    if not await send_dm(did, DM_DEACTIVATED, reason=reason):
        result.set_footer(text=DM_FAIL_NOTE)
    await post_to(LOG_CHANNEL_ID, result)
    await post_to(FORM_CHANNEL_ID, deactivation_form_embed(by_mention, rec, mm, reason))
    return result


async def auto_deactivate(discord_id: int, why: str):
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    try:
        rec = await remove_record(None, None, discord_id)
    except UserError:
        return  # ما كان مفعّل (أو انحذف قبل)
    except DataStoreError as e:
        log.error("فشل الإلغاء التلقائي: %s", e)
        return
    log.info("إلغاء تفعيل تلقائي: %s (%s)", rec.get("robloxName"), why)
    await finish_deactivation(bot.user.mention, rec, f"إلغاء تفعيل تلقائي — {why}", guild, strip_role=True)


# ============ الأوامر ============

class OtherReasonModal(discord.ui.Modal, title="سبب التفعيل"):
    reason = discord.ui.TextInput(
        label="اكتب سبب التفعيل", style=discord.TextStyle.paragraph,
        min_length=2, max_length=REASON_MAX, required=True,
    )

    def __init__(self, roblox_username: str, member: discord.Member):
        super().__init__()
        self.roblox_username = roblox_username
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        await interaction.response.defer()
        await run_activation(interaction, self.roblox_username, self.member, "other", str(self.reason.value))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("خطأ في المودال", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ صار خطأ", ephemeral=True)


REASON_CHOICES = [
    app_commands.Choice(name="التفعيل الطبيعي", value="normal"),
    app_commands.Choice(name="تفعيل فوري", value="instant"),
    app_commands.Choice(name="سبب آخر", value="other"),
]


@tree.command(name="تفعيل", description="تفعيل لاعب (يوزر روبلوكس + حساب ديسكورد)")
@app_commands.guilds(GUILD_OBJ)
@app_commands.guild_only()
@app_commands.rename(roblox_username="يوزر_روبلوكس", member="الديسكورد", reason="السبب")
@app_commands.describe(roblox_username="يوزر اللاعب في روبلوكس", member="حساب الديسكورد للاعب",
                       reason="سبب التفعيل")
@app_commands.choices(reason=REASON_CHOICES)
async def activate(interaction: discord.Interaction, roblox_username: str,
                   member: discord.Member, reason: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return
    if reason.value == "other":
        await interaction.response.send_modal(OtherReasonModal(roblox_username, member))
        return
    await interaction.response.defer()
    await run_activation(interaction, roblox_username, member, reason.value, REASON_LABELS[reason.value])


@tree.command(name="الغاء_تفعيل", description="إلغاء تفعيل لاعب (اكتب يوزر روبلوكس أو اختر الديسكورد)")
@app_commands.guilds(GUILD_OBJ)
@app_commands.guild_only()
@app_commands.rename(reason="السبب", roblox_username="يوزر_روبلوكس", user="الديسكورد")
@app_commands.describe(reason="سبب إلغاء التفعيل", roblox_username="يوزر اللاعب في روبلوكس",
                       user="حساب الديسكورد للاعب")
async def deactivate(interaction: discord.Interaction, reason: str,
                     roblox_username: Optional[str] = None, user: Optional[discord.User] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return
    if not roblox_username and user is None:
        await interaction.response.send_message("⚠️ اكتب يوزر روبلوكس أو اختر حساب الديسكورد", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        reason = clean_reason(reason)
        rid = lname = None
        if roblox_username:
            roblox_username = roblox_username.strip()
            lname = roblox_username.lower()
            if ROBLOX_NAME_RE.match(roblox_username):
                try:
                    resolved = await resolve_roblox(roblox_username)
                    if resolved:
                        rid = resolved[0]
                except UserError:
                    pass  # نكمل بالمطابقة على الاسم المخزّن
            else:
                raise UserError("يوزر روبلوكس غير صالح")
        rec = await remove_record(rid, lname, user.id if user else None)
    except UserError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return
    except DataStoreError as e:
        log.error("DataStore: %s", e)
        await interaction.followup.send("❌ فشل الحفظ في DataStore، ما تم الإلغاء. حاول مرة أخرى")
        return

    result = await finish_deactivation(interaction.user.mention, rec, reason, interaction.guild, strip_role=True)
    await interaction.followup.send(embed=result, allowed_mentions=NO_MENTIONS)


@tree.command(name="القوائم", description="عرض المفعّلين")
@app_commands.guilds(GUILD_OBJ)
@app_commands.guild_only()
async def list_players(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        data, _ = await ds_read(bot.http_session)
    except DataStoreError as e:
        log.error("DataStore: %s", e)
        await interaction.followup.send("❌ فشلت القراءة من DataStore", ephemeral=True)
        return
    recs = list(data["players"].values())
    lines, size = [], 0
    for i, r in enumerate(recs, 1):
        line = f"`{i}.` {r.get('robloxName')} — <@{r.get('discordId')}>"
        if size + len(line) > 3500:
            lines.append(f"... و {len(recs) - i + 1} آخرين")
            break
        lines.append(line)
        size += len(line) + 1
    embed = discord.Embed(title=f"📋 المفعّلين ({len(recs)})",
                          description="\n".join(lines) or "لا يوجد", color=0x5865F2)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=NO_MENTIONS)


@tree.command(name="مساعدة", description="عرض قائمة الأوامر")
@app_commands.guilds(GUILD_OBJ)
@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 أوامر البوت", color=0x5865F2)
    embed.add_field(name="`/تفعيل`", value="يوزر روبلوكس + حساب الديسكورد + السبب (الاثنين إلزامي)", inline=False)
    embed.add_field(name="`/الغاء_تفعيل`", value="السبب + (يوزر روبلوكس أو الديسكورد)", inline=False)
    embed.add_field(name="`/القوائم`", value="عرض المفعّلين", inline=False)
    embed.set_footer(text="الرتبة شرط: سحبها أو الخروج من السيرفر يلغي التفعيل تلقائياً")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error("خطأ في الأمر: %s", error)
    msg = "❌ صار خطأ غير متوقع"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# ============ الإلغاء التلقائي ============

@bot.event
async def on_member_remove(member: discord.Member):
    if member.guild.id != GUILD_ID or member.id in bot.pending:
        return
    await auto_deactivate(member.id, "غادر السيرفر")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id != GUILD_ID or after.id in bot.pending:
        return
    had = any(r.id == ACTIVE_ROLE_ID for r in before.roles)
    has = any(r.id == ACTIVE_ROLE_ID for r in after.roles)
    if had and not has:
        await auto_deactivate(after.id, "سُحبت منه رتبة التفعيل")


@tasks.loop(seconds=60)
async def reconcile_loop():
    """شبكة أمان: تلتقط أي تغيير فاتنا (البوت كان مطفي، إلخ)."""
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    try:
        data, _ = await ds_read(bot.http_session)
    except DataStoreError as e:
        log.warning("reconcile: %s", e)
        return
    for rec in list(data["players"].values()):
        try:
            did = int(rec.get("discordId"))
        except (TypeError, ValueError):
            continue
        if did in bot.pending:
            continue
        try:
            member = await get_member(guild, did)
        except Exception as e:
            log.warning("reconcile: تعذّر جلب %s: %s", did, e)
            continue  # لا نلغي التفعيل عند خطأ مؤقت
        if member is None:
            await auto_deactivate(did, "غادر السيرفر")
        elif not any(r.id == ACTIVE_ROLE_ID for r in member.roles):
            await auto_deactivate(did, "لا يملك رتبة التفعيل")


@reconcile_loop.before_loop
async def _before_reconcile():
    await bot.wait_until_ready()


async def register_commands():
    """تسجيل الأوامر في السيرفر + حذف الأوامر العامة القديمة (من النسخة السابقة)."""
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        log.error("❌ البوت مو موجود في السيرفر GUILD_ID=%s — تأكد من الآيدي وإن البوت داخل السيرفر", GUILD_ID)
        return
    try:
        synced = await tree.sync(guild=GUILD_OBJ)
        log.info("✅ تم تسجيل %d أوامر في السيرفر: %s", len(synced), guild.name)
    except discord.Forbidden:
        log.error("❌ ما قدر يسجل الأوامر (403). ادخل البوت من رابط فيه صلاحية applications.commands "
                  "(OAuth2 > URL Generator > تحدد bot + applications.commands) وأعد دعوته")
        return
    except Exception:
        log.exception("❌ فشل تسجيل الأوامر")
        return
    try:
        tree.clear_commands(guild=None)  # يحذف الأوامر العامة القديمة عشان ما تتكرر
        await tree.sync()
    except Exception as e:
        log.warning("تعذّر تنظيف الأوامر العامة القديمة: %s", e)


_ready_once = False


@bot.event
async def on_ready():
    global _ready_once
    log.info("✅ البوت جاهز: %s | Universe: %s | DataStore: %s", bot.user, UNIVERSE_ID, DATASTORE_NAME)
    if not _ready_once:
        _ready_once = True
        await register_commands()


bot.run(DISCORD_TOKEN)
