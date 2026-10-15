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
