"""الكمية المدخلة / المحسوبة / المعتمدة، وكشف تعارض المصادر."""
from dataclasses import dataclass, field
from .money import D, q3
from .formulas import evaluate, MissingInput


@dataclass
class QuantityResult:
    mode: str                 # direct | measured
    computed: object          # بدقة كاملة، أو None إن كانت مفقودة
    final: object             # بعد التعديل اليدوي إن وُجد (بدقة كاملة)
    shown: object             # q3(final) للعرض/الاعتماد
    overridden: bool = False
    override_reason: str = ""
    line_results: list = field(default_factory=list)
    problems: list = field(default_factory=list)   # [(code, message)]
    approved: bool = False
    approved_source: str = ""
    approved_reason: str = ""


def line_result(formula, inputs):
    return evaluate(formula, inputs)


def item_quantity(mode, direct=None, lines=(), formulas=None, override=None, override_reason=""):
    """lines: [(formula_code, inputs_dict, label)]. لا أسطر وهمية في الوضع المباشر."""
    problems, results = [], []
    if mode == "direct":
        computed = D(direct)
        if computed is None:
            problems.append(("QTY_MISSING", "لم تُدخل كمية مباشرة"))
    elif mode == "measured":
        if not lines:
            computed = None
            problems.append(("QTY_MISSING", "لا توجد أسطر قياس"))
        else:
            total, ok = D(0), True
            for code, inputs, label in lines:
                try:
                    r = line_result(formulas[code], inputs)
                except (MissingInput, KeyError) as e:
                    ok = False
                    problems.append(("LINE_INVALID", f"سطر «{label or code}»: {e}"))
                    continue
                results.append(r)
                if r < 0:
                    problems.append(("NEGATIVE_LINE", f"سطر «{label or code}» نتيجته سالبة"))
                total += r          # جمع بدقة كاملة، لا تقريب مبكر
            computed = total if ok else None
    else:
        raise ValueError("mode يجب أن تكون direct أو measured")

    ov = D(override)
    if ov is not None:
        if not override_reason:
            problems.append(("OVERRIDE_NO_REASON", "تعديل يدوي دون سبب مسجل"))
        problems.append(("MANUAL_OVERRIDE", "الكمية عُدلت يدويًا عن النتيجة المحسوبة"))
        final = ov
    else:
        final = computed
    return QuantityResult(mode, computed, final, q3(final), ov is not None,
                          override_reason, results, problems)


def resolve_period_cumulative(prev, period=None, cumulative=None, tol=D("0.0005")):
    """العلاقة: التراكمي = السابق + الفترة. السابق المفقود لا يُعتبر صفرًا."""
    prev, period, cumulative = D(prev), D(period), D(cumulative)
    problems = []
    if prev is None:
        problems.append(("PREV_MISSING", "الكمية السابقة غير محددة"))
        return {"prev": None, "period": period, "cumulative": cumulative, "problems": problems}
    if period is not None and cumulative is not None:
        if abs(prev + period - cumulative) > tol:
            problems.append(("QTY_INCONSISTENT", "السابق + الفترة لا يساوي التراكمي"))
    elif period is not None:
        cumulative = prev + period
    elif cumulative is not None:
        period = cumulative - prev
        if period < 0:
            problems.append(("NEGATIVE_PERIOD", "كمية الفترة سالبة (التراكمي أقل من السابق)"))
    else:
        problems.append(("QTY_MISSING", "لا كمية فترة ولا تراكمية"))
    return {"prev": prev, "period": period, "cumulative": cumulative, "problems": problems}


def detect_conflict(sources: dict):
    """sources: {'بيان الأشغال': qty, 'وضعية الأشغال': qty,...}. لا نختار تلقائيًا."""
    vals = {k: q3(v) for k, v in sources.items() if v is not None}
    distinct = set(vals.values())
    return {"conflict": len(distinct) > 1, "values": vals,
            "missing_in": [k for k, v in sources.items() if v is None]}
