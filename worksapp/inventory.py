"""الجرد العام والنقصان. السعر الأصلي ثابت؛ كمية العقد تبقى كما هي.

الحالة: كل زيادة لها حالة مستقلة (pending|approved|rejected). لا خلط بين
المسجل والمعتمد وغير المعتمد. الإجمالي «النهائي المعتمد تعاقديًا» لا يُحسب إلا إذا حدّد
المستخدم الحالات المدرجة (include_statuses) أو لم توجد زيادات غير معتمدة.
"""
from .money import D, q2, q3
from . import alerts as A

STATUSES = ("pending", "approved", "rejected")


def compute_inventory(items, tva_rate=None, include_statuses=None, tva_basis="per_column"):
    """items: [{code, price, contract_qty, decrease, increases:[{qty,status,note}], executed(optional)}].
    tva_basis: per_column (كما يظهر في النموذج: ضريبة على كل عمود) | on_net.  (غير مؤكد: إعداد)"""
    alerts, rows = [], []
    rate = D(tva_rate)
    if rate is None:
        alerts.append(A.make("TVA_INCOMPLETE", "الجرد"))
    elif rate < 0 or rate > 1:
        alerts.append(A.make("TVA_INVALID", "الجرد", f"المعدل المدخل: {rate}"))
        rate = None
    if tva_basis not in ("per_column", "on_net"):
        alerts.append(A.make("TVA_BASIS_INVALID", "الجرد", str(tva_basis)))
        tva_basis = None
    non_approved_exists = False

    for it in items:
        price, cq, dec = D(it.get("price")), D(it.get("contract_qty")), D(it.get("decrease")) or D(0)
        if price is None:
            alerts.append(A.make("PRICE_MISSING", it["code"]))
        elif price < 0:
            alerts.append(A.make("NEGATIVE_PRICE", it["code"], str(price)))
            price = None
        if cq is not None and cq < 0:
            alerts.append(A.make("NEGATIVE_QTY", it["code"], f"الكمية التعاقدية: {cq}"))
            cq = None
        if dec < 0:
            alerts.append(A.make("NEGATIVE_QTY", it["code"], f"كمية النقصان: {dec}"))
        inc = {s: D(0) for s in STATUSES}
        for x in it.get("increases", []):
            if x["status"] not in STATUSES:
                raise ValueError("حالة زيادة غير معروفة")
            q = D(x["qty"])
            if q is not None and q < 0:
                alerts.append(A.make("NEGATIVE_QTY", it["code"], f"كمية الزيادة ({x['status']}): {q}"))
            inc[x["status"]] += q or D(0)
        if D(it.get("executed")) is not None and D(it.get("executed")) < 0:
            alerts.append(A.make("NEGATIVE_QTY", it["code"], f"الكمية المنجزة: {D(it.get('executed'))}"))
        if inc["pending"] > 0:
            alerts.append(A.make("INCREASE_PENDING", it["code"]))
        if inc["pending"] > 0 or inc["rejected"] > 0:
            non_approved_exists = True

        def amt(q):
            return q2(q * price) if price is not None else None

        row = {
            "code": it["code"], "section": it.get("section"), "description": it.get("description"), "unit": it.get("unit"),
            "executed": D(it.get("executed")), "price": price, "contract_qty": cq, "decrease": dec,
            "increase_by_status": inc, "increase_registered": sum(inc.values(), D(0)),
            "contract_amount": amt(cq) if cq is not None else None,
            "decrease_amount": amt(dec),
            "increase_amount_by_status": {s: amt(v) for s, v in inc.items()},
            "final_approved": q3(cq - dec + inc["approved"]) if cq is not None else None,
            "final_with_pending": q3(cq - dec + inc["approved"] + inc["pending"]) if cq is not None else None,
        }
        ex = D(it.get("executed"))
        if ex is not None and cq is not None and ex > cq:
            alerts.append(A.make("EXCEEDS_CONTRACT", it["code"],
                                 f"العقد {q3(cq)}، المسجل {q3(ex)}، الفرق {q3(ex - cq)}"))
            row["exceeds_contract_by"] = q3(ex - cq)   # لا تُعتمد تلقائيًا
        rows.append(row)

    complete = all(r["contract_amount"] is not None and r["price"] is not None for r in rows)
    included = include_statuses
    if included is not None and any(st not in STATUSES for st in included):
        alerts.append(A.make("INCREASE_POLICY_INVALID", "الجرد", str(included)))
        included = None
    if included is None and not non_approved_exists:
        included = ["approved"]
    totals = {"complete": complete}
    if complete:
        s = lambda f: sum((f(r) for r in rows), D(0))
        totals["ht"] = {
            "contract": s(lambda r: r["contract_amount"]),
            "decrease": s(lambda r: r["decrease_amount"]),
            "increase_registered": s(lambda r: sum(r["increase_amount_by_status"].values(), D(0))),
            "increase_approved": s(lambda r: r["increase_amount_by_status"]["approved"]),
            "increase_pending": s(lambda r: r["increase_amount_by_status"]["pending"]),
            "increase_rejected": s(lambda r: r["increase_amount_by_status"]["rejected"]),
        }
        if included is None:
            totals["final_contractual_ht"] = None
            alerts.append(A.make("INCREASE_POLICY_UNSET", "الجرد"))
        else:
            inc_in = sum((totals["ht"][f"increase_{st}"] for st in included), D(0))
            totals["included_statuses"] = list(included)
            totals["final_contractual_ht"] = totals["ht"]["contract"] - totals["ht"]["decrease"] + inc_in
            if rate is not None and tva_basis in ("per_column", "on_net"):
                if tva_basis == "per_column":
                    t = {"contract": q2(totals["ht"]["contract"] * rate),
                         "decrease": q2(totals["ht"]["decrease"] * rate),
                         "increase": q2(inc_in * rate)}
                    t["final"] = t["contract"] - t["decrease"] + t["increase"]
                else:
                    t = {"final": q2(totals["final_contractual_ht"] * rate)}
                totals["tva"] = t
                totals["final_contractual_ttc"] = totals["final_contractual_ht"] + t["final"]
    return {"rows": rows, "totals": totals, "alerts": alerts}
