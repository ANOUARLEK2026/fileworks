"""وضعية الأشغال: كميات -> مبالغ -> TVA -> اقتطاعات قابلة للضبط -> صافي، مع شرح كل خطوة.

لا قواعد ثابتة: النسب والأسس والنطاق (للوضعية/هدف تراكمي) كلها من الإعداد.
القيم الناقصة تعطي None + تنبيهًا، ولا تُعامل صفرًا.

ما يُعتبر مؤقتًا (يحتاج تأكيدك): صيغة الصافي = TTC الفترة − مجموع الاقتطاعات.
(مأخوذة من تسلسل أسطر النموذج، لكن مراجع (1)…(6) فيه لم تُقرأ كلها بوضوح.)
"""
from .money import D, q2
from .quantities import resolve_period_cumulative
from . import alerts as A

BASES = ("ht_period", "ht_cumulative", "tva_period", "ttc_period", "ttc_cumulative")


def default_deductions():
    """الأسطر الافتراضية: ضريبة تُحسب منفصلة؛ الضمان والتسبيق غير مضبوطين حتى يحددهما المستخدم."""
    return [
        {"code": "guarantee", "label": "Retenue de garantie", "method": None},
        {"code": "advance", "label": "Remboursement d'avance", "method": None},
    ]


def _deduction(d, bases, alerts):
    label, code = d.get("label", d["code"]), d["code"]

    def incomplete(msg):
        alerts.append(A.make("DEDUCTION_INCOMPLETE", label, msg))
        return None, f"{label}: غير مكتمل — {msg}"

    if d.get("enabled") is False:      # قرار صريح: الاقتطاع لا يُطبَّق في هذه الوضعية (يظهر 0.00 كما في النموذج)
        return D(0), f"{label}: غير مطبق في هذه الوضعية (قرار صريح)"
    method = d.get("method")
    if method is None:
        return incomplete("لم تُحدد طريقة الحساب")
    if method == "none":
        return D(0), f"{label}: غير مطبق (قرار صريح)"
    if method in ("fixed", "manual"):
        amt = D(d.get("amount"))
        return (q2(amt), f"{label}: مبلغ {method} = {q2(amt)}") if amt is not None else incomplete("المبلغ غير مدخل")
    if method != "percent":
        return incomplete(f"طريقة غير معروفة {method}")

    rate, base_key, scope = D(d.get("rate")), d.get("base"), d.get("scope")
    if rate is not None and (rate < 0 or rate > 1):
        alerts.append(A.make("DEDUCTION_RATE_INVALID", label, str(rate)))
        return None, f"{label}: نسبة غير صالحة ({rate})"
    if rate is None or base_key not in BASES or scope not in ("per_situation", "cumulative_target"):
        return incomplete("النسبة أو الأساس أو النطاق غير محدد")
    base = bases.get(base_key)
    if base is None:
        return incomplete(f"الأساس {base_key} غير قابل للحساب (بيانات ناقصة)")
    raw = rate * base
    if scope == "cumulative_target":
        prev = D(d.get("previous"))
        if prev is None:
            return incomplete("المبلغ المقتطع سابقًا غير مدخل")
        target = q2(raw)
        due = target - q2(prev)
        text = f"{label}: هدف تراكمي {rate*100:g}% × {base_key} ({base}) = {target}؛ المقتطع سابقًا {q2(prev)}؛ المطلوب الآن = {due}"
    else:
        due = q2(raw)
        text = f"{label}: {rate*100:g}% × {base_key} ({base}) = {due}"
    cap = D(d.get("remaining_cap"))
    if cap is not None and due > cap:
        if d.get("cap_policy") == "clamp":
            text += f"؛ قُصّ إلى السقف المتبقي {cap}"
            due = q2(cap)
        else:
            alerts.append(A.make("DEDUCTION_EXCEEDS_CAP", label, f"{due} > المتبقي {cap}"))
    if due < 0:
        alerts.append(A.make("DEDUCTION_NEGATIVE", label, str(due)))
    return due, text


def compute_situation(items, config):
    """items: [{code, price, qty_prev, qty_period, qty_cum}]; config: mode, tva_rate, deductions."""
    alerts, lines = [], []
    mode = config.get("mode")
    if mode not in ("period", "cumulative"):
        raise ValueError("mode يجب أن تكون period أو cumulative (تُحدد حسب العقد)")
    rate = D(config.get("tva_rate"))
    if rate is None:
        alerts.append(A.make("TVA_INCOMPLETE", "المشروع"))
    elif rate < 0 or rate > 1:
        alerts.append(A.make("TVA_INVALID", "المشروع", f"المعدل المدخل: {rate}"))
        rate = None

    complete = True
    for it in items:
        price = D(it.get("price"))
        r = resolve_period_cumulative(it.get("qty_prev"), it.get("qty_period"), it.get("qty_cum"))
        probs = [p for p in r["problems"] if not (mode == "period" and p[0] == "PREV_MISSING")]
        alerts += A.from_problems(probs, it["code"])
        need_prev = mode == "cumulative"
        usable = (price is not None
                  and ((mode == "period" and r["period"] is not None)
                       or (mode == "cumulative" and r["cumulative"] is not None and r["prev"] is not None)))
        if price is None:
            alerts.append(A.make("PRICE_MISSING", it["code"]))
        if not usable:
            complete = False
        lines.append({
            "code": it["code"], "price": price,
            "qty_prev": r["prev"], "qty_period": r["period"], "qty_cum": r["cumulative"],
            "amount_period": q2(r["period"] * price) if usable and r["period"] is not None else None,
            "amount_cum": q2(r["cumulative"] * price) if price is not None and r["cumulative"] is not None else None,
            "amount_prev": q2(r["prev"] * price) if price is not None and r["prev"] is not None else None,
        })

    totals = {"ht_period": None, "ht_cumulative": None, "ht_previous": None,
              "tva_period": None, "ttc_period": None, "tva_cumulative": None, "ttc_cumulative": None}
    if complete and lines:
        if mode == "period":
            totals["ht_period"] = sum((l["amount_period"] for l in lines), D(0))
        else:   # التراكمي: فترة = تراكمي − سابق (لا خصم مزدوج)
            totals["ht_cumulative"] = sum((l["amount_cum"] for l in lines), D(0))
            totals["ht_previous"] = sum((l["amount_prev"] for l in lines), D(0))
            totals["ht_period"] = totals["ht_cumulative"] - totals["ht_previous"]
        if mode == "period" and all(l["amount_cum"] is not None for l in lines):
            totals["ht_cumulative"] = sum((l["amount_cum"] for l in lines), D(0))
        if rate is not None:
            totals["tva_period"] = q2(totals["ht_period"] * rate)
            totals["ttc_period"] = totals["ht_period"] + totals["tva_period"]
            if totals["ht_cumulative"] is not None:
                totals["tva_cumulative"] = q2(totals["ht_cumulative"] * rate)
                totals["ttc_cumulative"] = totals["ht_cumulative"] + totals["tva_cumulative"]

    bases = {k: totals[k] for k in BASES}
    deductions, all_ok = [], True
    for d in config.get("deductions", []):
        val, text = _deduction(d, bases, alerts)
        all_ok &= val is not None
        deductions.append({"code": d["code"], "label": d.get("label", d["code"]), "amount": val, "explain": text})

    net = None
    if totals["ttc_period"] is not None and all_ok:
        net = totals["ttc_period"] - sum((x["amount"] for x in deductions), D(0))
    else:
        alerts.append(A.make("NET_INCOMPLETE", "الوضعية"))

    return {"mode": mode, "tva_rate": rate, "lines": lines, "totals": totals,
            "deductions": deductions, "net": net,
            "net_formula": "ttc_period − Σ deductions  (مؤقتة: بانتظار تأكيد ترتيب العناصر)",
            "alerts": alerts}
