"""تحويل المبالغ إلى كلمات عربية للاستخدام في الوثائق الإدارية الجزائرية."""
from decimal import Decimal, ROUND_HALF_UP

_ONES = {
    0: "صفر", 1: "واحد", 2: "اثنان", 3: "ثلاثة", 4: "أربعة", 5: "خمسة",
    6: "ستة", 7: "سبعة", 8: "ثمانية", 9: "تسعة", 10: "عشرة",
    11: "أحد عشر", 12: "اثنا عشر", 13: "ثلاثة عشر", 14: "أربعة عشر",
    15: "خمسة عشر", 16: "ستة عشر", 17: "سبعة عشر", 18: "ثمانية عشر", 19: "تسعة عشر",
}
_TENS = {20: "عشرون", 30: "ثلاثون", 40: "أربعون", 50: "خمسون", 60: "ستون",
         70: "سبعون", 80: "ثمانون", 90: "تسعون"}
_HUNDREDS = {100: "مائة", 200: "مائتان", 300: "ثلاثمائة", 400: "أربعمائة",
             500: "خمسمائة", 600: "ستمائة", 700: "سبعمائة", 800: "ثمانمائة", 900: "تسعمائة"}
_SCALES = {
    1: ("ألف", "ألفان", "آلاف", "ألفًا"),
    2: ("مليون", "مليونان", "ملايين", "مليونًا"),
    3: ("مليار", "ملياران", "مليارات", "مليارًا"),
}


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, units = divmod(n, 10)
        return _TENS[tens * 10] if not units else f"{_ONES[units]} و{_TENS[tens * 10]}"
    hundreds = (n // 100) * 100
    remainder = n % 100
    return _HUNDREDS[hundreds] if not remainder else f"{_HUNDREDS[hundreds]} و{_under_thousand(remainder)}"


def number_words(value: int, construct: bool = False) -> str:
    """يعيد العدد الصحيح كلمات عربية، حتى خانة التريليونات تقريبًا.

    construct=True تستعمل صيغة الإضافة عند إتباع العدد باسم العملة، مثل
    «خمسة وعشرون ألف دينار» بدل «خمسة وعشرون ألفًا دينار».
    """
    n = int(value)
    if n < 0:
        return "سالب " + number_words(-n, construct=construct)
    if n == 0:
        return _ONES[0]
    parts = []
    scale = 0
    while n:
        group = n % 1000
        n //= 1000
        if group:
            words = _under_thousand(group)
            if scale:
                singular, dual, plural, accusative = _SCALES.get(scale, ("ترليون", "ترليونان", "ترليونات", "ترليونًا"))
                if group == 1:
                    words = singular
                elif group == 2:
                    words = dual[:-2] + "ا" if construct else dual
                elif 3 <= group <= 10:
                    words = f"{words} {plural}"
                elif construct or group % 100 == 0:
                    # عند إتباع العدد باسم العملة: «مائة ألف دينار» لا «مائة ألفًا دينار».
                    words = f"{words} {singular}"
                else:
                    words = f"{words} {accusative}"
            parts.append(words)
        scale += 1
    return " و".join(reversed(parts))


def _currency_unit(n: int, singular: str, dual: str, plural: str, accusative: str) -> str:
    last = n % 100
    if n == 1:
        return singular + " واحد"
    if n == 2:
        return dual
    if 3 <= last <= 10:
        return plural
    if 11 <= last <= 99:
        return accusative
    return singular


def amount_in_words(amount) -> str:
    """صياغة مبلغ بالدينار الجزائري والسنتيم مع الحفاظ على خانتين نقديتين."""
    if amount is None or amount == "":
        return ""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negative = value < 0
    value = abs(value)
    total_cents = int(value * 100)
    dinars, cents = divmod(total_cents, 100)
    if dinars == 1:
        dinar_phrase = "دينار جزائري واحد"
    elif dinars == 2:
        dinar_phrase = "ديناران جزائريان"
    else:
        unit = _currency_unit(dinars, "دينار جزائري", "ديناران جزائريان", "دنانير جزائرية", "دينارًا جزائريًا")
        dinar_phrase = f"{number_words(dinars, construct=True)} {unit}"
    phrase = dinar_phrase
    if cents:
        if cents == 1:
            cents_phrase = "سنتيم واحد"
        elif cents == 2:
            cents_phrase = "سنتيمان"
        elif 3 <= cents <= 10:
            cents_phrase = f"{number_words(cents)} سنتيمات"
        elif 11 <= cents <= 99:
            cents_phrase = f"{number_words(cents)} سنتيمًا"
        else:
            cents_phrase = f"{number_words(cents)} سنتيم"
        phrase += f" و{cents_phrase}"
    phrase = f"فقط {phrase} لا غير"
    return f"سالب {phrase}" if negative else phrase
