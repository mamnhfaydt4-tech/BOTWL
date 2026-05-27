# دليل الإعداد الكامل

## الخطوة 1 — إنشاء بوت Discord

1. افتح: https://discord.com/developers/applications
2. اضغط **New Application** → أعطه اسم
3. اذهب لتبويب **Bot** → اضغط **Add Bot**
4. انسخ الـ **Token** (هذا هو DISCORD_TOKEN)
5. في نفس الصفحة فعّل:
   - **Server Members Intent**
   - **Message Content Intent**
6. اذهب لـ **OAuth2 → URL Generator**:
   - اختر: `bot` و `applications.commands`
   - Permissions: `Send Messages`, `Use Slash Commands`
   - انسخ الرابط وأضف البوت لسيرفرك


## الخطوة 2 — إنشاء Roblox API Key

1. افتح: https://create.roblox.com/credentials
2. اضغط **Create API Key**
3. أعطها اسم
4. في **API System** اختر: `Universe Datastores`
5. في **Experience** أضف لعبتك
6. الصلاحيات: فعّل `Read` و `Write`
7. في **Accepted IP Addresses**: اكتب `0.0.0.0/0` (أو IP السيرفر)
8. اضغط **Save** وانسخ المفتاح


## الخطوة 3 — الحصول على Universe ID

من رابط اللعبة في Roblox Create:
```
https://create.roblox.com/dashboard/creations/experiences/XXXXXXX/overview
```
الرقم الكبير = Universe ID


## الخطوة 4 — تشغيل البوت

```bash
# تثبيت المكتبات
pip install -r requirements.txt

# إنشاء ملف .env
cp .env.example .env
# عبئ القيم في .env

# تشغيل البوت
python bot.py
```


## الخطوة 5 — تشغيل مستمر (اختياري)

لتشغيل البوت 24/7 يمكنك استخدام:
- **Railway** (مجاني): https://railway.app
- **Replit** مع Keep Alive
- أي VPS (Ubuntu + `screen` أو `pm2`)


## الأوامر المتاحة

| الأمر | الوصف | الصلاحية |
|-------|-------|---------|
| `/تفعيل [اسم]` | تفعيل لاعب | إداري + مالك |
| `/الغاء_تفعيل [اسم]` | إلغاء تفعيل | إداري + مالك |
| `/اضافة_اداري [اسم]` | تعيين إداري | مالك فقط |
| `/ازالة_اداري [اسم]` | إزالة إداري | مالك فقط |
| `/القوائم` | عرض الكل | إداري + مالك |
| `/مساعدة` | الأوامر | الجميع |


## ملاحظة مهمة

البوت والماب **مستقلان تماماً**:
- البوت يكتب في DataStore مباشرة عبر Open Cloud API
- الماب يقرأ نفس DataStore بشكل مستقل
- لو البوت وقف، الماب يشتغل 100% عادي
- لو الماب توقف، البوت يشتغل 100% عادي
