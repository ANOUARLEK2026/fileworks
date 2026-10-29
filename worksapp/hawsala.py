"""حوصلة الأشغال: سابق / فترة / تراكمي. تُعرض البنود المنفذة فقط، دون افتراض صفر للبيانات الناقصة."""
from .money import D, q3
from .quantities import resolve_period_cumulative
from . import alerts as A


def compute_hawsala(rows):
    """rows: [{code, description, unit, contract_qty, prev, period, cum}]"""
    out, alerts, no_data, zero = [], [], [], []
    for r in rows:
        if r.get("period") in (None, "") and r.get("cum") in (None, ""):
            no_data.append(r["code"])      # لا بيانات: لا نعتبرها صفرًا ولا نعرضها
            continue
        res = resolve_period_cumulative(r.get("prev"), r.get("period"), r.get("cum"))
        alerts += A.from_problems(res["problems"], r["code"])
        if res["cumulative"] is not None and res["cumulative"] == 0 and (res["period"] in (None, 0)):
            zero.append(r["code"])
            continue
        cq = D(r.get("contract_qty"))
        if res["cumulative"] is not None and cq is not None and res["cumulative"] > cq:
            alerts.append(A.make("EXCEEDS_CONTRACT", r["code"],
                                 f"العقد {q3(cq)}، التراكمي {q3(res['cumulative'])}، الفرق {q3(res['cumulative'] - cq)}"))
        out.append({"code": r["code"], "description": r.get("description"), "unit": r.get("unit"),
                    "contract_qty": cq, "prev": res["prev"], "period": res["period"], "cum": res["cumulative"]})
    return {"rows": out, "items_without_data": no_data, "items_zero": zero, "alerts": alerts}
