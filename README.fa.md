# Archive Bot

[🇬🇧 English](README.md) | [🇮🇷 فارسی](README.fa.md)

یه بات تلگرامی async که فایل‌ها و ویدیوها رو داخل صف جمع می‌کنه و بعد ازشون آرشیو می‌سازه.

## قابلیت‌ها

- صف کردن فایل، ویدیو، صدا، گیف، ویس و ویدیو نوت
- حذف فایل از صف با reply کردن روی فایل و فرستادن `/delete`
- پاک کردن کل صف با تایید
- تشخیص فایل‌های تکراری قبل از آرشیو با امکان نگه داشتن یا حذف کردن فایل‌های تکراری
- پیشنهاد هوشمند فرمت بر اساس متادیتای فایل‌ها
- پشتیبانی از ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, TAR.ZSTD, TAR.ZST, GZ, XZ, ZST
- انتخاب سطح فشرده‌سازی همراه با توضیح فشاری که به CPU میاد
- امکان گذاشتن پسورد برای فرمت‌هایی که پشتیبانی می‌کنن
- تعیین حداکثر حجم خروجی با پیش‌فرض ۲۰۰۰ مگابایت
- تقسیم کردن آرشیوهای بزرگ به چند پارت مختلف
- ساخت چند آرشیو مستقل برای صف‌های بزرگ
- نمایش سرعت دانلود، زمان گذشته، ETA و مقدار منتقل شده
- ‏heartbeat موقع آپلود به تلگرام، چون این مسیر آپلود progress دقیق بایتی نمیده
- انتخاب اسم پیش‌فرض یا اسم دلخواه برای آرشیو با محدودیت امن
- پاک‌سازی فایل‌های موقت موقع startup، شروع job، پایان job و shutdown

## فرمت‌های دارای پسورد

| فرمت | پشتیبانی از پسورد | نیازمندی |
|---|---|---|
| 7Z | بله | `7z` |
| ZIP | بله | `7z` |
| RAR | بله | `rar` |
| TAR / TAR.GZ / TAR.BZ2 / TAR.XZ / TAR.ZST | نه | ندارد |

برای 7Z، هدرها هم رمزنگاری میشن.

## نیازمندی‌ها

- ‏Python 3.11 یا 3.12 پیشنهاد می‌شه
- توکن بات از [@BotFather](https://t.me/BotFather)
- ‏API_ID و API_HASH از <https://my.telegram.org> (می‌تونید از [این](https://t.me/ApiHashGeneratorBot) بات هم استفاده کنید.)
- سرور لینوکسی پیشنهاد میشه
- ابزارهای اختیاری:
  - ‏`p7zip-full` برای 7Z و ZIP پسورددار
  - ‏`zstd` برای TAR.ZST / TAR.ZSTD
  - ‏`rar` برای آرشیو RAR

## نصب

### ۱. نصب پکیج‌های سیستم

روی Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip p7zip-full zstd
```

برای نصب RAR:

```bash
sudo apt install -y rar
```

اگر نصب نشد، بخش troubleshooting رو بخون.

### ۲. کلون کردن ریپو

```bash
git clone https://github.com/BlueMammad/TelegramArchiveBot.git
cd TelegramArchiveBot
```

### ۳. ساخت virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### ۴. تنظیم `.env`

```bash
cp .env.example .env
nano .env
```

نمونه:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:your_bot_token
ARCHIVE_BOT_DATA=./archive_bot_data
MAX_PARALLEL_DOWNLOADS=3
MAX_PARALLEL_JOBS=1
MAX_PARALLEL_UPLOADS=1
DEFAULT_MAX_MB=2000
EDIT_INTERVAL=4.0
SEND_INTERVAL=1.1
DRAFT_INTERVAL=4.0
BURST_SUMMARY_DELAY=3.0
```

### ۵. اجرای بات

```bash
python3 bot.py
```

خروجی مورد انتظار:

```text
Archive bot is running. Press Ctrl+C to stop.
```

## محدود کردن دسترسی با BotFather

بات رو با [@BotFather](https://t.me/BotFather) بساز، توکن رو بردار و داخل `.env` بذار.

اگه می‌خوای فقط خودت بتونی از بات استفاده کنی، داخل تنظیمات BotFather رو طوری تنظیم کن که فقط اکانت تلگرام خودت اجازه استفاده داشته باشه.

## استفاده

1. فایل یا ویدیو بفرست.
2. صبر کن پیام صف بعد از تموم شدن ارسال‌ها ظاهر بشه.
3. برای حذف فایل، روی همون فایل reply کن و `/delete` بفرست.
4. روی **Compress all** کلیک کن.
5. فرمت رو انتخاب کن.
6. سطح فشرده‌سازی رو انتخاب کن.
7. حداکثر حجم خروجی رو انتخاب کن.
8. اگر فرمت پشتیبانی می‌کرد، پسورد بده یا skip کن.
9. اسم پیش‌فرض آرشیو رو قبول کن یا اسم دلخواه بفرست.
10. اگر فایل تکراری پیدا شد، انتخاب کن نگه داشته بشن یا حذف بشن.
11. ‏job رو شروع کن.
12. آرشیو یا پارت‌ها رو دانلود کن.

## آرشیوهای تقسیم شده

اگر خروجی از محدودیت بیشتر بشه، بات فایل‌هایی شبیه این می‌سازه:

```text
archive.tar.zst.part001
archive.tar.zst.part002
archive.tar.zst.part003
```

همه پارت‌ها رو دانلود کن و بعدش یکی کن.

روی لینوکس:

```bash
cat archive.tar.zst.part* > archive.tar.zst
```

بعد فایل اصلی رو extract کن.

## اجرا با systemd

```bash
sudo nano /etc/systemd/system/archivebot.service
```

نمونه:

```ini
[Unit]
Description=Archive Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/TelegramArchiveBot
ExecStart=/root/TelegramArchiveBot/venv/bin/python /root/TelegramArchiveBot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

فعال‌سازی و اجرا:

```bash
sudo systemctl daemon-reload
sudo systemctl enable archivebot
sudo systemctl start archivebot
sudo systemctl status archivebot
```

لاگ‌ها:

```bash
journalctl -u archivebot -f
```

## Troubleshooting

### موقع نصب پکیج‌ها Permission denied گرفتی

داخل virtual environment از `sudo pip` استفاده نکن.

```bash
cd ~/TelegramArchiveBot
deactivate 2>/dev/null || true
sudo chown -R "$USER:$USER" ~/TelegramArchiveBot
rm -rf venv
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

اگر ریپو رو با root کلون کردی، به جای `~/TelegramArchiveBot` از `/root/TelegramArchiveBot` استفاده کن.

### خطای `externally-managed-environment`

داری داخل Python سیستم نصب می‌کنی. virtual environment بساز.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

### پیدا نشدن `API_ID` یا `API_HASH` یا `BOT_TOKEN`

مطمئن شو `.env` کنار `bot.py` هست.

```bash
ls -la .env
```

### مشکل event loop روی Python 3.13

اگه PyroTGFork روی Python 3.13 مشکل داشت، از Python 3.11 یا 3.12 استفاده کن.

### پکیج `rar` قابل نصب نیست

بعضی از توزیع‌ها پکیج `rar` رو توی مخزن‌های پیش‌فرضشون ندارن.

می‌تونی دستی از ریلیز رسمی RARLAB نصبش کنی:

```bash
wget https://www.rarlab.com/rar/rarlinux-x64-701.tar.gz

tar -xf rarlinux-x64-701.tar.gz

cd rar

sudo install -Dm755 rar /usr/local/bin/rar
````

برای مطمئن شدن از نصب:

```bash
rar
```

اگه نصب `rar` ممکن نبود، از یه فرمت آرشیو دیگه استفاده کن.

بات فقط وقتی خطا می‌ده که فرمت RAR انتخاب شده باشه ولی باینری `rar` روی سیستم نصب نباشه؛ پس نصب RAR اجباری نیست.

### نصب نبودن `zstd`

```bash
sudo apt install -y zstd
```

### نصب نبودن `7z`

```bash
sudo apt install -y p7zip-full
```

### باقی ماندن فایل‌های قدیمی روی سرور

بات این موارد رو پاک می‌کنه:

- پوشه‌های runtime موقع startup
- پوشه‌های work/output هر کاربر موقع شروع job جدید
- فایل‌های دانلود شده بعد از job
- پوشه‌های runtime موقع shutdown

اگر فایل‌ها باقی موندن، permission پوشه رو درست کن.

```bash
sudo chown -R "$USER:$USER" ./archive_bot_data
```

## متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
|---|---:|---|
| `API_ID` | required | API ID تلگرام |
| `API_HASH` | required | API Hash تلگرام |
| `BOT_TOKEN` | required | توکن بات |
| `ARCHIVE_BOT_DATA` | `./archive_bot_data` | پوشه runtime |
| `MAX_PARALLEL_DOWNLOADS` | `3` | تعداد دانلود همزمان |
| `MAX_PARALLEL_JOBS` | `1` | تعداد job همزمان |
| `MAX_PARALLEL_UPLOADS` | `1` | تعداد آپلود همزمان |
| `DEFAULT_MAX_MB` | `2000` | حجم پیش‌فرض هر part |
| `EDIT_INTERVAL` | `4.0` | حداقل فاصله edit |
| `SEND_INTERVAL` | `1.1` | حداقل فاصله ارسال پیام در هر چت |
| `DRAFT_INTERVAL` | `4.0` | مقدار legacy |
| `BURST_SUMMARY_DELAY` | `3.0` | زمان انتظار قبل از ساخت دوباره پیام صف |