"""أدوات الأعداد العشرية. كل الحسابات بـ Decimal (لا float) والتخزين نصًا.

سياسة التقريب (قابلة للمراجعة، موثقة هنا ومستعملة في كل مكان):
  * الدقة الداخلية: 40 خانة، لا تقريب أثناء الجمع/الضرب.
  * الكميات المعروضة/المعتمدة: 3 منازل، ROUND_HALF_UP.
  * المبالغ: منزلتان، ROUND_HALF_UP، على مستوى كل سطر؛ والمجاميع = جمع الأسطر المقربة
    (وهو ما تطابق مع أرقام النماذج الأصلية).
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext, InvalidOperation, DecimalException

getcontext().prec = 40
PI = Decimal("3.14159265358979323846264338327950288")
Q3 = Decimal("0.001")
Q2 = Decimal("0.01")
# حدود حماية عامة تمنع القيم غير المنتهية/الضخمة من إفساد الحسابات أو التصدير.
MAX_ABS_NUMBER = Decimal("1e18")
MIN_ADJUSTED_EXPONENT = -30


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# علامات الاتجاه غير المرئية (LRM/RLM/LRE/RLE/PDF/LRO/RLO/LRI/RLI/FSI/PDI/ALM) تُحذف عند قراءة الأرقام،
# لأن العرض في الواجهة قد يضيفها حول المبالغ ثم يعيد المستخدم نسخ الرقم أو تعديله.
_BIDI_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c"))


def normalize_number(text):
    """يقبل الأرقام العربية-الهندية، والمسافات/NBSP كفاصل آلاف، والفاصلة العشرية العربية (٫) أو الفرنسية (,).
    فاصلة وحدها = فاصلة عشرية. إن وُجدت فاصلة ونقطة معًا فالأخيرة هي العشرية. أكثر من فاصلة = آلاف."""
    s = str(text).translate(_BIDI_MARKS).strip().translate(_DIGITS)
    s = s.replace("٫", ".").replace("٬", "").replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return s


def D(v):
    """تحويل آمن إلى Decimal؛ يرفض NaN/Infinity والقيم خارج النطاق الحسابي.

    None والسلسلة الفارغة تبقيان None (لا نفترض صفرًا أبدًا). لا نسمح بقيم
    ضخمة أو صغيرة للغاية قد تسبب أخطاء quantize أو نتائج غير قابلة للعرض.
    """
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        result = v if isinstance(v, Decimal) else Decimal(normalize_number(v))
    except (InvalidOperation, DecimalException, TypeError, ValueError):
        raise ValueError(f"قيمة عددية غير صالحة: {v!r}")
    if not result.is_finite():
        raise ValueError(f"يجب أن تكون القيمة رقمًا محدودًا: {v!r}")
    if abs(result) > MAX_ABS_NUMBER:
        raise ValueError(f"القيمة خارج النطاق المسموح (±{MAX_ABS_NUMBER}): {v!r}")
    if result and result.adjusted() < MIN_ADJUSTED_EXPONENT:
        raise ValueError(f"القيمة صغيرة جدًا للدقة الحسابية المدعومة: {v!r}")
    return result


def q3(v):
    return None if v is None else D(v).quantize(Q3, rounding=ROUND_HALF_UP)


def q2(v):
    return None if v is None else D(v).quantize(Q2, rounding=ROUND_HALF_UP)


def fmt(v, places=2):
    """تنسيق عرض كما في النماذج: فاصل آلاف بمسافة وفاصلة عشرية نقطة."""
    if v is None:
        return "—"
    qz = Q2 if places == 2 else Q3
    return f"{D(v).quantize(qz, rounding=ROUND_HALF_UP):,.{places}f}".replace(",", " ")


LRM = "\u200e"


def bidi_safe(text):
    """يحمي نصًا رقميًا (مبلغ/كمية/تاريخ) من انعكاس مقاطعه داخل سياق RTL.

    المسافة بين مجموعات الآلاف محايدة في خوارزمية Unicode، وبين رقمين في فقرة RTL تأخذ اتجاه الفقرة
    فيُعرض «9 333 403.84» بترتيب «403.84 333 9». نحيط كل مسافة وطرفي النص بعلامة LRM القوية.
    """
    if text is None or text == "":
        return text
    t = str(text)
    return LRM + t.replace(" ", LRM + " " + LRM).replace("\u00a0", LRM + "\u00a0" + LRM) + LRM


def ltr_marks(text):
    """يثبّت ترتيب التواريخ وأرقام العقود ذات الفواصل (- / : .) داخل نص RTL بعلامة LRM حول الفاصل كي لا تنعكس مقاطعها."""
    if text in (None, ""):
        return text
    import re
    return re.sub(r"([-/:.])", "\u200e\\1\u200e", str(text))


def fmt_ui(v, places=2):
    """تنسيق مبلغ/كمية للعرض في الواجهة: فاصل آلاف + نقطة عشرية + حماية الاتجاه. None → «—»."""
    return bidi_safe(fmt(v, places))
