"""المبلغ بالحروف (تفقيط) بأسلوب الوثائق الجزائرية، كما في النماذج:

    «تسعة ملايين وثلاثمائة وثلاثة وثلاثون ألف وأربعمائة وثلاثة دينار جزائري و 84 سنتيم»

* الأعداد بالرفع (…ون) والمعدود المفرد بعد 11 فما فوق (ثلاثة وثلاثون ألف)، والجمع من 3 إلى 10 (ثلاثة آلاف / ملايين).
* السنتيم يُكتب رقمًا كما في النماذج (يمكن طلبه حروفًا).
* المبلغ يُقرَّب إلى منزلتين بـ ROUND_HALF_UP كسياسة التطبيق (money.q2). السالب مرفوض صراحةً.
"""
from decimal import Decimal

from .money import D, q2

_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
         "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUND = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# (المفرد، المثنى، الجمع لـ 3..10)
_SCALES = [("", "", ""), ("ألف", "ألفان", "آلاف"), ("مليون", "مليونان", "ملايين"), ("مليار", "ملياران", "مليارات")]


def _below_1000(n):
    parts = []
    h, r = divmod(n, 100)
    if h:
        parts.append(_HUND[h])
    if r:
        if r < 20:
            parts.append(_ONES[r])
        else:
            t, u = divmod(r, 10)
            parts.append((_ONES[u] + " و" if u else "") + _TENS[t])
    return " و".join(parts)


def integer_in_words(n):
    """عدد صحيح غير سالب (حتى 999 مليار) بالحروف؛ الصفر = «صفر»."""
    n = int(n)
    if n < 0:
        raise ValueError("المبلغ بالحروف لا يقبل قيمة سالبة")
    if n >= 10 ** 12:
        raise ValueError("الرقم أكبر من الحد المدعوم (999 مليار)")
    if n == 0:
        return "صفر"
    groups = []
    scale = 0
    while n:
        n, g = divmod(n, 1000)
        groups.append((g, scale))
        scale += 1
    out = []
    for g, sc in reversed(groups):
        if g == 0:
            continue
        if sc == 0:
            out.append(_below_1000(g))
            continue
        one, two, few = _SCALES[sc]
        if g == 1:
            out.append(one)
        elif g == 2:
            out.append(two)
        elif 3 <= g <= 10:
            out.append(f"{_ONES[g]} {few}")
        else:
            out.append(f"{_below_1000(g)} {one}")
    return " و".join(out)


def amount_in_words(value, currency="دينار جزائري", centime="سنتيم", centimes_as_digits=True, show_zero_centimes=False):
    """None يعيد None (لا نكتب مبلغًا غير محسوب)."""
    v = D(value)
    if v is None:
        return None
    v = q2(v)
    if v < 0:
        raise ValueError("المبلغ بالحروف لا يقبل قيمة سالبة")
    dinars = int(v)
    cents = int((v - dinars) * 100)
    if dinars == 1:
        cur = f"{currency} واحد"
    elif dinars == 2:
        cur = "ديناران جزائريان" if currency == "دينار جزائري" else f"{currency} (2)"
    else:
        words = integer_in_words(dinars)
        for dual in ("مائتان", "ألفان", "مليونان", "ملياران"):   # مضاف إلى «دينار»: مائتا دينار، ألفا دينار
            if words.endswith(dual):
                words = words[:-1]
                break
        cur = f"{words} {currency}"
    if cents == 0 and not show_zero_centimes:
        return cur
    c = f"{cents:02d}" if centimes_as_digits else integer_in_words(cents)
    return f"{cur} و {c} {centime}"
