"""نظام التنبيهات: لكل تنبيه (المشكلة، المتأثر، لماذا، الإجراء) + شدة قابلة للضبط.

الشدّات الافتراضية أدناه مؤقتة (PROVISIONAL): لم يحسم المستخدم أي التحذيرات تمنع الاعتماد.
تُعدَّل عبر إعداد alert_severity دون تغيير الكود.
"""
from dataclasses import dataclass, asdict

INFO, WARNING, BLOCKING = "info", "warning", "blocking"

CATALOG = {
    # code: (default severity, المشكلة, لماذا, الإجراء)
    "QTY_MISSING": (BLOCKING, "كمية منفذة غير موجودة", "لا يمكن حساب مبلغ البند ولا نفترض صفرًا", "أدخل الكمية أو أضف أسطر قياس"),
    "PREV_MISSING": (BLOCKING, "الكمية السابقة غير محددة", "لا يمكن اشتقاق كمية الفترة/المبلغ دون السابق", "أدخل السابق صراحةً (0 إن كان أول وضعية)"),
    "QTY_INCONSISTENT": (BLOCKING, "السابق + الفترة ≠ التراكمي", "الكميات متناقضة", "صحح أحد القيم"),
    "NEGATIVE_PERIOD": (WARNING, "كمية فترة سالبة", "التراكمي الحالي أقل من السابق", "راجع الكميات"),
    "NEGATIVE_LINE": (INFO, "سطر قياس سالب", "قد يكون خصم فتحات (كما في النموذج) أو خطأ", "تأكد من القصد"),
    "LINE_INVALID": (BLOCKING, "سطر قياس غير صالح", "مدخل ناقص أو غير صحيح", "أكمل مدخلات السطر"),
    "MANUAL_OVERRIDE": (INFO, "كمية معدلة يدويًا", "تختلف عن النتيجة المحسوبة", "تأكد من سبب التعديل"),
    "OVERRIDE_NO_REASON": (WARNING, "تعديل يدوي دون سبب", "التتبع لاحقًا يحتاج السبب", "سجل سبب التعديل"),
    "QTY_CONFLICT_UNRESOLVED": (BLOCKING, "اختلاف كمية بين مصدرين", "لا نختار مصدرًا تلقائيًا", "اختر الكمية المعتمدة وسجل السبب"),
    "EXCEEDS_CONTRACT": (WARNING, "الكمية المنفذة تتجاوز كمية العقد", "قرار الاعتماد تعاقدي", "راجع شروط العقد؛ الزيادة لا تُعتمد تلقائيًا"),
    "PRICE_MISSING": (BLOCKING, "بند بلا سعر وحدة", "لا يمكن حساب المبلغ", "أدخل سعر الوحدة"),
    "UNIT_MISSING": (WARNING, "بند بلا وحدة", "الوحدة مطلوبة للعرض/اقتراح المعادلة", "أدخل الوحدة"),
    "TVA_INCOMPLETE": (BLOCKING, "معدل TVA غير مضبوط", "لا نفترض معدلًا ثابتًا", "أدخل معدل TVA للمشروع"),
    "DEDUCTION_INCOMPLETE": (BLOCKING, "إعداد اقتطاع غير مكتمل", "لا نفترض أساسًا أو نسبة", "أكمل نسبة الاقتطاع وأساسه، أو اختر «غير مطبق» صراحةً"),
    "DEDUCTION_EXCEEDS_CAP": (WARNING, "الاقتطاع يتجاوز المتبقي المسموح", "قد يخالف سقف العقد", "راجع السقف أو اختر سياسة القص"),
    "DEDUCTION_NEGATIVE": (WARNING, "اقتطاع سالب", "المبلغ السابق أكبر من المستهدف", "راجع الاقتطاعات السابقة"),
    "NET_INCOMPLETE": (BLOCKING, "صافي المبلغ غير قابل للحساب", "بيانات ناقصة أعلاه", "عالج التنبيهات المانعة"),
    "INCREASE_POLICY_UNSET": (BLOCKING, "طريقة إدراج الزيادات غير المعتمدة غير محددة", "لا نخلط المسجل بالمعتمد", "حدد الحالات المدرجة في الإجمالي النهائي"),
    "INCREASE_PENDING": (WARNING, "زيادة لم تُحسم حالتها", "لا تُعتبر معتمدة بمجرد الإدخال", "اعتمد الزيادة أو ارفضها"),
    "PROJECT_INCOMPLETE": (WARNING, "بيانات مشروع ناقصة", "مطلوبة لملء النموذج", "أكمل بطاقة المشروع"),
    "DOCUMENT_EMPTY": (BLOCKING, "الوثيقة فارغة", "لا تحتوي على أي بند صالح للعرض وقد تكون نتيجة نسيان إدخال البيانات", "أدخل البنود المطلوبة ثم أعد المعاينة قبل الإصدار"),
    "TVA_INVALID": (BLOCKING, "معدل TVA غير صالح", "يجب إدخال معدل نسبي بين 0 و1، لا 19 بدل 0.19", "صحح معدل الضريبة وفق العقد"),
    "DEDUCTION_RATE_INVALID": (BLOCKING, "نسبة اقتطاع غير صالحة", "النسبة خارج المجال من 0 إلى 1", "صحح نسبة الاقتطاع وفق العقد"),
    "INCREASE_POLICY_INVALID": (BLOCKING, "سياسة إدراج زيادات غير صالحة", "تتضمن السياسة حالة غير معروفة", "اختر الحالات المعتمدة من القائمة"),
    "TVA_BASIS_INVALID": (BLOCKING, "أساس ضريبة الجرد غير صالح", "أساس الضريبة غير معروف", "اختر أساس احتساب الضريبة من إعدادات المشروع"),
    "NEGATIVE_PRICE": (BLOCKING, "سعر وحدة سالب", "أسعار بنود العقد لا ينبغي أن تكون سالبة", "راجع سعر الوحدة في بطاقة العقد"),
    "NEGATIVE_QTY": (BLOCKING, "كمية جرد سالبة", "النقصان والزيادة والكمية المنجزة تُدخل ككميات غير سالبة", "صحح الكمية أو سجّل التصحيح بالطريقة المعتمدة تعاقديًا"),
}


@dataclass
class Alert:
    code: str
    severity: str
    problem: str
    affected: str
    why: str
    action: str
    detail: str = ""

    def to_dict(self):
        return asdict(self)


def make(code, affected="", detail=""):
    sev, problem, why, action = CATALOG[code]
    return Alert(code, sev, problem, affected, why, action, detail)


def from_problems(problems, affected):
    return [make(c, affected, m) for c, m in problems if c in CATALOG]


def apply_policy(alerts, overrides=None):
    """overrides: {code: severity} من إعدادات المستخدم."""
    overrides = overrides or {}
    hard_blocking = {"DOCUMENT_EMPTY", "QTY_CONFLICT_UNRESOLVED", "TVA_INVALID", "DEDUCTION_RATE_INVALID",
                     "INCREASE_POLICY_INVALID", "TVA_BASIS_INVALID", "NEGATIVE_PRICE", "NEGATIVE_QTY"}
    for a in alerts:
        # إعدادات الشدة لا تستطيع تجاوز فحوص صحة البيانات أو القرارات المحاسبية الجوهرية.
        if a.code in hard_blocking:
            a.severity = BLOCKING
        elif a.code in overrides:
            a.severity = overrides[a.code]
    return alerts


def blocking(alerts):
    return [a for a in alerts if a.severity == BLOCKING]
