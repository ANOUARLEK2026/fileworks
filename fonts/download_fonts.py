"""يحمّل خط Tajawal (ترخيص SIL OFL، حر الاستعمال والتوزيع) إلى هذا المجلد ليستعمله البرنامج تلقائيًا.

التشغيل (يحتاج إنترنت مرة واحدة):   python fonts/download_fonts.py
بعدها أعد تشغيل البرنامج. إن فشل التحميل يستمر البرنامج بخط النظام (Segoe UI) دون أي مشكلة.
"""
import os
import sys
import urllib.request

BASE = "https://github.com/google/fonts/raw/main/ofl/tajawal/"
FILES = ("Tajawal-Regular.ttf", "Tajawal-Medium.ttf", "Tajawal-Bold.ttf", "Tajawal-ExtraBold.ttf")
MAGIC = (b"\x00\x01\x00\x00", b"true", b"OTTO")        # ترويسات ملفات TrueType / OpenType


def is_font(data: bytes) -> bool:
    """يرفض صفحات الخطأ HTML أو الملفات المبتورة التي قد يُرجعها الخادم بدل الخط."""
    return len(data) > 20000 and data[:4] in MAGIC


def download(folder: str) -> int:
    ok = 0
    for name in FILES:
        target = os.path.join(folder, name)
        if os.path.exists(target):
            print(f"موجود: {name}"); ok += 1; continue
        try:
            req = urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
        except Exception as exc:
            print(f"تعذر تحميل {name}: {exc}"); continue
        if not is_font(data):
            print(f"الملف المحمَّل ليس خطًا صالحًا: {name}"); continue
        with open(target, "wb") as fh:
            fh.write(data)
        print(f"تم: {name}"); ok += 1
    return ok


if __name__ == "__main__":
    n = download(os.path.dirname(os.path.abspath(__file__)))
    print(f"\n{n} من {len(FILES)} ملفات جاهزة." + (" أعد تشغيل البرنامج." if n else " تحقق من الاتصال بالإنترنت ثم أعد المحاولة."))
    sys.exit(0 if n else 1)
