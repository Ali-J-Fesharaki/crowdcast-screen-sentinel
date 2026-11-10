# 🛡️ CrowdCast Screen Sentinel
> **نگهبان صفحات و عیب‌یاب یک‌کلیکه ضبط سیاه برای Crowd-Cast در ماشین‌های مجازی Incus (Wayland/GNOME)**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](#)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%7C%20Incus%20VM-orange.svg)](#)

---

## 📖 معرفی به زبان فارسی (Persian Overview)

در محیط‌های توسعه خودکار و ضبط تجربیات کاربر با **`crowd-cast`** بر روی ماشین‌های مجازی Incus (تحت گنوم و ویلند)، یکی از شایع‌ترین و مخرب‌ترین مشکلات، **«ضبط شدن فریم‌های کاملاً سیاه» (Pitch-Black Video)** است. 

این نرم‌افزار به عنوان یک کنسول ناظر (Sentinel) و داشبورد سبک، تمام پنجره‌ها و صفحات باز سیستم را به صورت لحظه‌ای از طریق D-Bus رصد می‌کند، به شما می‌گوید دقیقاً **کدام صفحه در حال حاضر یا در صورت فوکوس سیاه ضبط خواهد شد** و **با یک کلیک در مقابل هر صفحه، علت سیاهی را به طور ریشه‌ای و خودکار حل می‌کند.**

### ✨ ویژگی‌های کلیدی (Key Features)

1. **داشبورد زیبا، سبک و بلادرنگ (Web Dashboard):**
   - بدون نیاز به وابستگی‌های سنگین خارجی (Zero External Pip Dependencies).
   - با طراحی تیره مدرن (Glassmorphism & Cyberpunk Dark Mode) و پشتیبانی کامل راست‌به‌چپ (RTL).
   - دسترسی آسان هم از سیستم میزبان (`http://localhost:8585`) و هم از درون ماشین مجازی (`http://10.5.48.1:8585`).

2. **تشخیص دقیق و زنده صفحات سیاه (Black Screen Detection):**
   - 🔴 **صفحه هم‌اکنون سیاه ضبط می‌شود! (Active Blackout):** اگر پنجره فعال در `target_apps` نباشد، سیستم فوراً با پالس قرمز هشدار می‌دهد.
   - 🟡 **خطر ضبط سیاه (Blackout Risk):** صفحات باز که در لیست مجاز نیستند و با سوییچ روی آنها، ضبط سیاه خواهد شد را علامت‌گذاری می‌کند.
   - 🟢 **در حال نظارت و ایمن (Safe):** صفحاتی که دارای شناسه دقیق `wm_class` هستند و ضبط آنها شفاف و بدون خطاست.

3. **حل مشکل صفحه سیاه با ۱ کلیک (⚡ 1-Click Black Screen Fix):**
   با فشردن یک دکمه جلوی هر صفحه:
   - شناسه رسمی `wm_class` و نام‌های مستعار وابسته (مانند `com.microsoft.VSCode` و `code`) را به `target_apps` اضافه می‌کند.
   - خطای فاجعه‌بار `capture_all = true` (که در ویلند باعث لغو پورتال و سیاهی ۱۰۰٪ می‌شود) را غیرفعال می‌سازد.
   - ویژگی `blank_video_on_untracked_app` را به حالت ایمن درمی‌آورد.
   - تایم‌اوت بیکاری را برای پیشگیری از توقف ضبط به ۶۰۰ ثانیه می‌رساند.
   - سرویس ضبط را ریستارت و پنجره را جهت شروع پایپ‌وایر فوکوس می‌کند.

4. **نظارت بر همه صفحات در یک کلیک (⚡ Whitelist All Open):**
   با یک کلیک تمام نرم‌افزارهای باز دسکتاپ را به لیست نظارت ریکوردر وارد می‌کند.

5. **پروب و نمونه‌برداری زنده روشنایی (Luma Sampler & Live Preview):**
   فریم اخیر ویدیو را مستقیماً استخراج و سطح لومینانس (Min, Max, Mean) را بررسی و پیش‌نمایش تصویر را نشان می‌دهد.

---

## 🛠️ ساختار معماری (Architecture)

```text
Host (Local Machine)
 │
 ├── sentinel.py (CLI & Runner)
 ├── app/
 │    ├── server.py           --> Threaded REST API & Web Dashboard (:8585)
 │    ├── sentinel_core.py    --> منطق تشخیص سیاهی و رفع خودکار ۱-کلیکه
 │    ├── incus_bridge.py     --> پل ارتباطی D-Bus با گنوم و کنترل Incus VM
 │    └── luma_sampler.py     --> استخراج فریم و سنجش روشنایی با FFmpeg
 └── web/
      ├── index.html          --> داشبورد SPA واکنش‌گرا و فارسی
      ├── style.css           --> استایل مدرن دارک و نشانگرهای وضعیت
      └── app.js              --> همگام‌سازی خودکار و تعاملات یک‌کلیکه
           │
           ▼ (sg incus-admin / D-Bus)
Guest VM (crowd-vm / Wayland)
 ├── org.crowdcast.FocusProvider  <-- ListWindows & GetFocused
 ├── ~/.config/agent/config.toml  <-- target_apps whitelist
 └── ~/.local/bin/crowdcast-ctl   <-- daemon controller
```

---

## 🚀 شروع سریع (Quickstart)

### ۱. اجرای داشبورد تحت وب (Web Dashboard)

```bash
# از داخل دایرکتوری ریپو:
./scripts/run_dashboard.sh

# یا مستقیماً با پایتون:
python3 sentinel.py serve --host 0.0.0.0 --port 8585
```

داشبورد را در مرورگر خود باز کنید:
- **روی هاست:** `http://localhost:8585`
- **داخل ماشین مجازی یا شبکه:** `http://10.5.48.1:8585`

---

### ۲. استفاده از خط فرمان (CLI Tool)

این نرم‌افزار علاوه بر داشبورد وب، دارای یک رابط خط فرمان کامل برای اسکریپت‌ها و کاربران ترمینال است:

```bash
# نمایش لیست تمام پنجره‌های باز و وضعیت سیاهی آنها
python3 sentinel.py list

# حل مشکل صفحه سیاه برای یک پنجره با ۱ کلیک در ترمینال
python3 sentinel.py fix org.gnome.Nautilus
python3 sentinel.py fix com.microsoft.VSCode

# افزودن تمام پنجره‌های باز فعلی به لیست نظارت
python3 sentinel.py whitelist-all

# بررسی سلامت روشنایی فریم‌های ویدیویی (Luma Stats)
python3 sentinel.py luma

# مشاهده وضعیت ریکوردر و تنظیمات ایمنی
python3 sentinel.py status
```

---

### ۳. نصب به عنوان سرویس خودکار پس‌زمینه (Systemd Service)

برای اجرای مداوم داشبورد در پس‌زمینه:

```bash
./scripts/install_service.sh
systemctl --user enable --now crowdcast-sentinel.service

# بررسی وضعیت سرویس
systemctl --user status crowdcast-sentinel.service
```

---

## 🧪 اجرای تست‌های خودکار (Unit Tests)

```bash
python3 -m unittest discover -s tests
```

---

## 📄 لایسنس (License)

تحت مجوز [MIT License](LICENSE) منتشر شده است.
توسعه داده شده توسط **علی جعفری فشارکی** با همراهی سیستم توسعه مستقل Hermes Agent.
