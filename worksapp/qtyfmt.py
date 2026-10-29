"""عرض الكميات في الوثائق حسب الوحدة ونوع الوثيقة (الحسابات تبقى بدقتها الكاملة؛ هذا للعرض فقط).

النماذج الأصلية تعرض الكميات بأشكال تتبع الوحدة:
  * العدد (و، ج): عدد صحيح بخانتين  «15» «01» «00»
  * م² و«مط»: منزلتان «68.20» «645.00»
  * م³: ثلاث منازل في الجرد/البيان «1.275» «12.000»، وعدد صحيح عند التساوي في الحوصلة/الوضعية «12»

قواعد صارمة لعدم إخفاء الدقة: إن كان التقريب إلى عدد المنازل المطلوب يغيّر القيمة فنزيد المنازل (حتى 3)
بدل أن نعرض رقمًا لا يطابق ما حُسب. ويمكن تجاوز القواعد من إعداد المشروع qty_format:
  {"hawsala": {"m3": "dec3"}}  ، القيم: int2 | dec2 | dec3 | auto3
"""
from decimal import Decimal, ROUND_HALF_UP

from .money import D, fmt

_SUP = str.maketrans("²³٢٣", "2323")
_COUNT = {"و", "وحدة", "وح", "ج", "جزافي", "جزاف", "u", "ens", "fft"}
_ML = {"مط", "ml", "m.l", "مطول"}


def unit_kind(unit):
    """count | m3 | m2 | ml | other — يتحمل المسافات والشرطة والنقطة والأرقام الهندية (م3، م 3، م³، م/ط، م ط)."""
    if not unit:
        return "other"
    u = str(unit).strip().translate(_SUP).lower()
    for ch in " ./\\-\u200f\u200e\u00a0":
        u = u.replace(ch, "")
    if u in ("م3", "m3"):
        return "m3"
    if u in ("م2", "m2"):
        return "m2"
    if u in _ML:
        return "ml"
    if u in _COUNT:
        return "count"
    return "other"


DEFAULT_RULES = {
    "bayan":     {"count": "int2", "m3": "dec3", "m2": "dec2", "ml": "dec2", "other": "dec2"},
    "hawsala":   {"count": "int2", "m3": "auto3", "m2": "dec2", "ml": "dec2", "other": "dec2"},
    "situation": {"count": "int2", "m3": "auto3", "m2": "dec2", "ml": "dec2", "other": "dec2"},
    "inventory": {"count": "int2", "m3": "dec3", "m2": "dec2", "ml": "dec2", "other": "dec2"},
}


def _places(v, n):
    q = Decimal(1).scaleb(-n)
    return v.quantize(q, rounding=ROUND_HALF_UP)


def format_qty(value, unit, doc_type, overrides=None):
    """سلسلة العرض. None → «—» (لا نعرض صفرًا لقيمة غير معروفة)."""
    v = D(value)
    if v is None:
        return "—"
    kind = unit_kind(unit)
    rule = ((overrides or {}).get(doc_type) or {}).get(kind) or DEFAULT_RULES.get(doc_type, DEFAULT_RULES["bayan"])[kind]
    integral = v == v.to_integral_value()
    if rule == "int2" and integral and v >= 0:
        return f"{int(v):02d}"
    if rule == "auto3":
        if integral:
            return str(int(v))
        return fmt(v, 3)
    places = 3 if rule == "dec3" else 2
    if places == 2 and _places(v, 2) != v:       # التقريب كان سيغيّر القيمة → نحافظ على الدقة
        places = 3
    return fmt(v, places)
