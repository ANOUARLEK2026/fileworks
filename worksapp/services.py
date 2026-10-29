"""طبقة الخدمات: تربط قاعدة البيانات بالحسابات. لا تعتمد على أي واجهة، ويمكن اختبارها.

مفاتيح إعدادات المشروع (settings_json): tva_rate, situation_mode, deductions[], increase_statuses[], tva_basis.
حمولة المسودة (payload): {"rows": {code: {...}}, "config": {...}}.
"""
import json
import os
from . import storage as S, alerts as A
from .money import D, fmt, q3
from .hawsala import compute_hawsala
from .inventory import compute_inventory
from .situation import compute_situation, default_deductions
from .quantities import detect_conflict

DOC_LABELS = {"bayan": "بيان الأشغال المنجزة", "hawsala": "حوصلة الأشغال المنجزة",
              "situation": "وضعية الأشغال", "inventory": "الجرد العام والنقصان"}
STATUS_LABELS = {"draft": "مسودة", "issued": "صادرة"}
# الحالات المعروضة للمستخدم (مشتقة من status + revision + الأرشفة). لا توجد حالة «ملغاة» في النظام: الإلغاء يتم بنسخة تصحيحية.
DISPLAY_STATUSES = ("draft", "draft_correction", "issued", "issued_correction", "archived")
DISPLAY_LABELS = {"draft": "مسودة", "draft_correction": "مسودة تصحيحية", "issued": "صادرة",
                  "issued_correction": "تصحيحية صادرة", "archived": "مؤرشفة"}
INCREASE_STATUS_LABELS = {"pending": "غير محسومة", "approved": "معتمدة", "rejected": "مرفوضة"}

# أعمدة المحرر لكل نوع: (المفتاح، العنوان، قابل للتعديل)
EDITOR_COLUMNS = {
    "inventory": [("code", "الرقم", False), ("description", "تعيين الأشغال", False), ("unit", "الوحدة", False),
                  ("price", "سعر الوحدة", False), ("contract_qty", "الكمية المقررة في العقد", False),
                  ("decrease", "كمية النقصان", True), ("increase", "كمية الزيادة", True),
                  ("increase_status", "حالة الزيادة", True), ("executed", "الكمية المنجزة", True)],
    "hawsala": [("code", "الرقم", False), ("description", "تعيين الأشغال", False), ("unit", "الوحدة", False),
                ("contract_qty", "الكمية المقررة في العقد", False), ("prev", "الكمية المنجزة سابقًا", True),
                ("period", "الكمية المنجزة خلال الفترة", True), ("cum", "الكمية الكلية المنجزة", True)],
    "situation": [("code", "الرقم", False), ("description", "تعيين الأشغال", False), ("unit", "الوحدة", False),
                  ("price", "سعر الوحدة", False), ("prev", "الكمية السابقة", True),
                  ("period", "كمية الفترة", True), ("cum", "الكمية الكلية", True)],
}


def project_settings(conn, pid):
    return S.project_settings(conn, pid)


def project_alerts(conn, pid):
    p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    company = S.company_for_project(conn, pid)
    missing = [label for k, label in (("name", "اسم المشروع"), ("contract_no", "رقم العقد"), ("contract_date", "تاريخ العقد"),
                                      ("owner", "صاحب المشروع")) if not p[k]]
    if not company:
        missing.append("الشركة المتعاقدة (أدخل بياناتها من «الشركة المتعاقدة»)")
    out = [A.make("PROJECT_INCOMPLETE", "بطاقة المشروع", "ناقص: " + "، ".join(missing))] if missing else []
    for it in S.list_items(conn, pid):
        if not it["unit"]:
            out.append(A.make("UNIT_MISSING", it["code"]))
    return out


def _latest_issued(conn, pid, doc_type):
    r = conn.execute("SELECT * FROM documents WHERE project_id=? AND doc_type=? AND status='issued' "
                     "ORDER BY id DESC LIMIT 1", (pid, doc_type)).fetchone()
    return dict(r) if r else None


def previous_cumulative(conn, pid, doc_type, code):
    """الكمية السابقة تلقائيًا = تراكمي آخر وثيقة صادرة من النوع نفسه؛ None إن لم توجد (لا نفترض صفرًا)."""
    d = _latest_issued(conn, pid, doc_type)
    if not d:
        return None
    res = json.loads(d["snapshot_json"])["results"]
    rows = res.get("rows") or res.get("lines") or []
    for r in rows:
        if r.get("code") == code:
            return r.get("cum") if r.get("cum") is not None else r.get("qty_cum")
    return D(0) if rows else None   # وثيقة سابقة صدرت ولم يظهر فيها البند => لم يُنفذ فيها


def new_payload(conn, pid, doc_type):
    rows = {}
    for it in S.list_items(conn, pid):
        row = {}
        if doc_type in ("hawsala", "situation"):
            prev = previous_cumulative(conn, pid, doc_type, it["code"])
            row["prev"] = None if prev is None else str(prev)
        rows[it["code"]] = row
    return {"rows": rows, "config": {}}


def create_draft(conn, pid, doc_type):
    payload = new_payload(conn, pid, doc_type) if doc_type != "bayan" else {}
    return S.create_draft(conn, pid, doc_type, payload)


def _merged_rows(conn, pid, payload):
    out = []
    for it in S.list_items(conn, pid):
        base = {"code": it["code"], "description": it["description"], "unit": it["unit"],
                "price": it["unit_price"], "contract_qty": it["contract_qty"], "section": it.get("section")}
        base.update(payload.get("rows", {}).get(it["code"], {}))
        out.append(base)
    return out


def quantity_conflicts(conn, pid):
    """يعيد تعارضات الكميات مع القيم والمصادر حتى يستطيع المستخدم اتخاذ قرار واعٍ."""
    srcs = {}
    for dt in ("hawsala", "situation"):
        d = conn.execute("SELECT * FROM documents WHERE project_id=? AND doc_type=? ORDER BY id DESC LIMIT 1",
                         (pid, dt)).fetchone()
        if d:
            srcs[dt] = json.loads(d["payload_json"]).get("rows", {})
    found = []
    for it in S.list_items(conn, pid):
        qrow = conn.execute("SELECT * FROM item_quantities WHERE item_id=?", (it["id"],)).fetchone()
        if not qrow or qrow["approved_qty"] not in (None, ""):
            continue
        base = S.get_quantity(conn, it["id"]).final
        values = {"بيان الأشغال": base}
        for dt, label in (("hawsala", "حوصلة الأشغال"), ("situation", "وضعية الأشغال")):
            row = srcs.get(dt, {}).get(it["code"], {})
            val = D(row.get("cum")) if row.get("cum") not in (None, "") else None
            if val is None and row.get("period") not in (None, "") and row.get("prev") not in (None, ""):
                val = D(row["prev"]) + D(row["period"])
            if val is not None:
                values[label] = val
        conflict = detect_conflict(values)
        if conflict["conflict"]:
            found.append({"item_id": it["id"], "code": it["code"], "description": it.get("description") or "",
                          "unit": it.get("unit") or "", "values": conflict["values"]})
    return found


def conflicts(conn, pid):
    """تنبيهات تعارض المصادر: القرار لا يُتخذ آليًا أبدًا."""
    out = []
    for item in quantity_conflicts(conn, pid):
        details = " | ".join(f"{k}: {fmt(v, 3)}" for k, v in item["values"].items())
        out.append(A.make("QTY_CONFLICT_UNRESOLVED", item["code"], details))
    return out


def _snapshot_view(dt, res, state):
    """يبني معاينة الوثيقة الصادرة من لقطة الإصدار، لا من البيانات الحية المتغيرة."""
    if dt == "bayan":
        return ( ["الرقم", "تعيين الأشغال", "الوحدة", "المجموع الكلي", "ملاحظة"],
                 [[r["code"], r.get("description"), r.get("unit"), fmt(r.get("qty"), 3),
                   (f"كمية معتمدة من {r.get('approved_source')}" if r.get("approved") else ("عُدّل يدويًا" if r.get("overridden") else ""))]
                  for r in res.get("rows", [])] )
    if dt == "hawsala":
        return ( ["الرقم", "تعيين الأشغال", "الوحدة", "المقرر في العقد", "سابقًا", "خلال الفترة", "الكلية المنجزة"],
                 [[r["code"], r.get("description"), r.get("unit"), fmt(r.get("contract_qty"), 3),
                   fmt(r.get("prev"), 3), fmt(r.get("period"), 3), fmt(r.get("cum"), 3)]
                  for r in res.get("rows", [])] )
    if dt == "situation":
        desc = {r["code"]: r for r in state.get("items", [])}
        rows = [[l["code"], desc.get(l["code"], {}).get("description"), fmt(l.get("price")),
                 fmt(l.get("qty_period"), 3), fmt(l.get("qty_cum"), 3), fmt(l.get("amount_period"))]
                for l in res.get("lines", [])]
        t = res.get("totals", {})
        rows.append(["", "المجموع خارج الرسم HT", "", "", "", fmt(t.get("ht_period"))])
        rate = D(res.get("tva_rate"))
        rows.append(["", f"TVA {fmt(rate * 100)}%" if rate is not None else "TVA (غير مضبوط)", "", "", "", fmt(t.get("tva_period"))])
        rows.append(["", "المجموع بكل الرسوم TTC", "", "", "", fmt(t.get("ttc_period"))])
        for x in res.get("deductions", []):
            rows.append(["", x.get("label"), "", "", "", fmt(x.get("amount"))])
        rows.append(["", "صافي المبلغ", "", "", "", fmt(res.get("net"))])
        return (["الرقم", "تعيين الأشغال", "سعر الوحدة", "كمية الفترة", "الكمية الكلية", "مبلغ الفترة"], rows)
    if dt == "inventory":
        desc = {r["code"]: r for r in state.get("items", [])}
        return (["الرقم", "تعيين الأشغال", "المقرر في العقد", "نقصان", "زيادة", "مبلغ العقد", "مبلغ النقصان", "مبلغ الزيادة"],
                [[r["code"], desc.get(r["code"], {}).get("description"), fmt(r.get("contract_qty"), 3),
                  fmt(r.get("decrease"), 3), fmt(r.get("increase_registered"), 3), fmt(r.get("contract_amount")),
                  fmt(r.get("decrease_amount")),
                  fmt(sum((D(x) for x in r.get("increase_amount_by_status", {}).values()), D(0))
                      if r.get("price") is not None else None)] for r in res.get("rows", [])])
    raise ValueError(f"نوع وثيقة غير معروف: {dt}")


def compute(conn, doc_id):
    d = S.get_document(conn, doc_id)
    if d["status"] == "issued":
        if not d.get("snapshot_json"):
            raise ValueError("الوثيقة صادرة دون لقطة محفوظة؛ أوقف المعاينة وراجع قاعدة البيانات")
        snapshot = json.loads(d["snapshot_json"])
        state, res = snapshot["state"], snapshot["results"]
        alerts = [A.Alert(**a) for a in snapshot.get("alerts", [])]
        return {"doc": d, "results": res, "alerts": alerts, "view": _snapshot_view(d["doc_type"], res, state),
                "snapshot": snapshot}
    pid, dt = d["project_id"], d["doc_type"]
    payload = json.loads(d["payload_json"] or "{}")
    ps = project_settings(conn, pid)
    alerts = project_alerts(conn, pid) + conflicts(conn, pid)
    if dt == "bayan":
        rows = []
        for it in S.list_items(conn, pid):
            if conn.execute("SELECT 1 FROM item_quantities WHERE item_id=?", (it["id"],)).fetchone() is None:
                continue
            q = S.get_quantity(conn, it["id"])
            alerts += A.from_problems(q.problems, it["code"])
            fm = S.load_formulas(conn)
            lines = []
            for ml in conn.execute("SELECT * FROM measure_lines WHERE item_id=? ORDER BY position", (it["id"],)):
                f, vals = fm[ml["formula_code"]], json.loads(ml["inputs_json"])
                from .formulas import evaluate
                lines.append({"formula": f.name, "factors": [str(vals.get(i["name"]) or i.get("default") or "") for i in f.inputs],
                              "label": ml["label"], "location": ml["location"], "result": evaluate(f, vals)})
            rows.append({"code": it["code"], "description": it["description"], "unit": it["unit"],
                         "qty": q.shown, "computed": q.computed, "overridden": q.overridden,
                         "approved": q.approved, "approved_source": q.approved_source,
                         "approved_reason": q.approved_reason, "mode": q.mode, "lines": lines})
        res = {"rows": rows}
        view = (["الرقم", "تعيين الأشغال", "الوحدة", "المجموع الكلي", "ملاحظة"],
                [[r["code"], r["description"], r["unit"], fmt(r["qty"], 3),
                  (f"كمية معتمدة من {r['approved_source']}" if r["approved"] else ("عُدّل يدويًا" if r["overridden"] else ""))] for r in rows])
    elif dt == "hawsala":
        res = compute_hawsala(_merged_rows(conn, pid, payload)); alerts += res["alerts"]
        view = (["الرقم", "تعيين الأشغال", "الوحدة", "المقرر في العقد", "سابقًا", "خلال الفترة", "الكلية المنجزة"],
                [[r["code"], r["description"], r["unit"], fmt(r["contract_qty"], 3), fmt(r["prev"], 3), fmt(r["period"], 3), fmt(r["cum"], 3)]
                 for r in res["rows"]])
    elif dt == "situation":
        cfg = {"mode": payload.get("config", {}).get("mode") or ps.get("situation_mode"),
               "tva_rate": ps.get("tva_rate"), "deductions": ps.get("deductions") or default_deductions()}
        if cfg["mode"] is None:
            raise ValueError("اختر طريقة الوضعية (فترة/تراكمي) في إعدادات المشروع أو المسودة")
        items = [{"code": r["code"], "price": r["price"], "qty_prev": r.get("prev"),
                  "qty_period": r.get("period"), "qty_cum": r.get("cum")} for r in _merged_rows(conn, pid, payload)
                 if r.get("period") not in (None, "") or r.get("cum") not in (None, "")]
        res = compute_situation(items, cfg); alerts += res["alerts"]
        desc = {r["code"]: r for r in _merged_rows(conn, pid, payload)}
        view = (["الرقم", "تعيين الأشغال", "سعر الوحدة", "كمية الفترة", "الكمية الكلية", "مبلغ الفترة"],
                [[l["code"], desc[l["code"]]["description"], fmt(l["price"]), fmt(l["qty_period"], 3), fmt(l["qty_cum"], 3),
                  fmt(l["amount_period"])] for l in res["lines"]])
        t = res["totals"]
        view[1].append(["", "المجموع خارج الرسم HT", "", "", "", fmt(t["ht_period"])])
        view[1].append(["", f"TVA {fmt((res['tva_rate'] or 0) * 100)}%" if res["tva_rate"] is not None else "TVA (غير مضبوط)", "", "", "", fmt(t["tva_period"])])
        view[1].append(["", "المجموع بكل الرسوم TTC", "", "", "", fmt(t["ttc_period"])])
        for x in res["deductions"]:
            view[1].append(["", x["label"], "", "", "", fmt(x["amount"])])
        view[1].append(["", "صافي المبلغ", "", "", "", fmt(res["net"])])
    elif dt == "inventory":
        items = []
        for r in _merged_rows(conn, pid, payload):
            inc = []
            if r.get("increase") not in (None, "", "0"):
                inc = [{"qty": r["increase"], "status": r.get("increase_status") or "pending"}]
            items.append({"code": r["code"], "section": r.get("section"), "description": r["description"], "unit": r["unit"],
                          "price": r["price"], "contract_qty": r["contract_qty"],
                          "decrease": r.get("decrease"), "increases": inc, "executed": r.get("executed")})
        res = compute_inventory(items, ps.get("tva_rate"), ps.get("increase_statuses"), ps.get("tva_basis") or "per_column")
        alerts += res["alerts"]
        desc = {r["code"]: r for r in _merged_rows(conn, pid, payload)}
        view = (["الرقم", "تعيين الأشغال", "المقرر في العقد", "نقصان", "زيادة", "مبلغ العقد", "مبلغ النقصان", "مبلغ الزيادة"],
                [[r["code"], desc[r["code"]]["description"], fmt(r["contract_qty"], 3), fmt(r["decrease"], 3),
                  fmt(r["increase_registered"], 3), fmt(r["contract_amount"]), fmt(r["decrease_amount"]),
                  fmt(sum(r["increase_amount_by_status"].values(), D(0)) if r["price"] is not None else None)]
                 for r in res["rows"]])
    else:
        raise ValueError(dt)
    # لا نصدر بيانًا خاليًا من البنود المنفذة أو حوصلة/وضعية/جردًا بلا أسطر.
    row_key = {"bayan": "rows", "hawsala": "rows", "situation": "lines", "inventory": "rows"}[dt]
    if not res.get(row_key):
        alerts.append(A.make("DOCUMENT_EMPTY", DOC_LABELS[dt], "لا توجد أسطر في ناتج الوثيقة"))
    A.apply_policy(alerts, S.get_setting(conn, "alert_severity", {}))
    return {"doc": d, "results": res, "alerts": alerts, "view": view}


def preview(conn, doc_id):
    return compute(conn, doc_id)


def issue(conn, doc_id, explicit_approval=False):
    c = compute(conn, doc_id)
    return S.issue_document(conn, doc_id, c["alerts"], c["results"], explicit_approval)


def documents_overview(conn, pid):
    out = {}
    for dt in S.DOC_TYPES:
        docs = [dict(r) for r in conn.execute("SELECT id,number,revision,status,created_at,issued_at FROM documents "
                                              "WHERE project_id=? AND doc_type=? ORDER BY id DESC", (pid, dt))]
        out[dt] = {"label": DOC_LABELS[dt], "docs": docs,
                   "state": ("لا وثائق" if not docs else
                             f"آخر وثيقة: {STATUS_LABELS[docs[0]['status']]}" + (f" رقم {docs[0]['number']}" if docs[0]['number'] else ""))}
    return out


# ---------- إدخال البنود ----------
def next_item_code(conn, pid):
    nums = []
    for it in S.list_items(conn, pid):
        try:
            nums.append(int(it["code"]))
        except ValueError:
            pass
    n = (max(nums) + 1) if nums else len(S.list_items(conn, pid)) + 1
    existing = {it["code"] for it in S.list_items(conn, pid)}
    while f"{n:02d}" in existing:
        n += 1
    return f"{n:02d}"


def parse_items_text(conn, pid, text):
    """يحلل نصًا منسوخًا من Excel/جدول: أعمدة مفصولة بـ Tab أو ; بالترتيب:
    رقم البند | وصف | وحدة | سعر الوحدة | الكمية | فصل (اختياري). يعيد (rows, errors) ولا يكتب شيئًا."""
    from .money import D
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    split = lambda l: [c.strip() for c in (l.split("\t") if "\t" in l else l.split(";"))]
    rows, errors = [], []
    existing = {it["code"] for it in S.list_items(conn, pid)}
    seen = set()
    start = 0
    if len(lines) > 1:                      # سطر عناوين؟ (خانة السعر ليست رقمًا)
        first = split(lines[0])
        if len(first) > 3 and first[3]:
            try:
                D(first[3])
            except ValueError:
                start = 1
    for n, line in enumerate(lines[start:], start=start + 1):
        c = split(line) + [""] * 6
        code, desc, unit, price, qty, section = c[:6]
        ok = True
        if not code:
            errors.append(f"السطر {n}: رقم البند مطلوب"); continue
        if code in existing or code in seen:
            errors.append(f"السطر {n}: رقم البند «{code}» مكرر"); ok = False
        vals = {}
        for key, label, raw in (("price", "سعر الوحدة", price), ("qty", "الكمية التعاقدية", qty)):
            try:
                v = D(raw) if raw else None
                if v is not None and v < 0:
                    raise ValueError("سالب")
                vals[key] = v
            except ValueError:
                errors.append(f"السطر {n}: {label} «{raw}» ليس رقمًا صحيحًا"); ok = False
        seen.add(code)
        if ok:
            rows.append({"code": code, "description": desc or None, "unit": unit or None, "section": section or None, **vals})
    return rows, errors


# ---------- مجلدات حفظ الملفات (حسب المشروع ونوع الوثيقة) ----------
def export_dir(conn, pid, doc_type):
    """مجلد حفظ ملفات وثيقة من نوع معين. الأولوية: مجلد مخصص لنوع الوثيقة، ثم مجلد المشروع
    (مع مجلد فرعي باسم نوع الوثيقة ما لم يُلغَ ذلك)، وإلا None (يسأل البرنامج عند التصدير)."""
    ps = S.project_settings(conn, pid)
    per_type = ((ps.get("export_dirs") or {}).get(doc_type) or "").strip()
    if per_type:
        return per_type
    base = (ps.get("export_dir") or "").strip()
    if not base:
        return None
    return os.path.join(base, DOC_LABELS[doc_type]) if ps.get("export_subfolders", True) else base


def export_filename(doc, ext):
    """اسم الملف المقترح: «وضعية الأشغال 03.docx»؛ النسخة التصحيحية تضيف رقم المراجعة."""
    name = DOC_LABELS[doc["doc_type"]]
    if doc["number"] is not None:
        name += f" {doc['number']:02d}"
    if doc.get("revision"):
        name += f" - تصحيح {doc['revision']}"
    return f"{name}.{ext}"


def suggested_export_path(conn, doc_id, ext):
    """المسار المقترح الكامل (ينشئ المجلد إن لم يوجد). يعيد اسم الملف فقط إن لم يُضبط مجلد."""
    d = S.get_document(conn, doc_id)
    name = export_filename(d, ext)
    folder = export_dir(conn, d["project_id"], d["doc_type"])
    if not folder:
        return name
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return name                       # مجلد غير صالح/غير متاح: نرجع لحوار الحفظ العادي
    return os.path.join(folder, name)


def validate_export_dirs(base, per_type):
    """يتحقق من المسارات المدخلة (مطلقة فقط). يعيد القيم منظفة أو يرمي ValueError."""
    def clean(v, what):
        v = (v or "").strip().strip('"')
        if v and not os.path.isabs(v):
            raise ValueError(f"{what}: أدخل مسارًا كاملًا (مثل D:\\وثائق\\المشروع) أو اختره بزر «استعراض»")
        return v or None
    return clean(base, "مجلد المشروع"), {dt: clean(per_type.get(dt), f"مجلد «{DOC_LABELS[dt]}»") for dt in S.DOC_TYPES}


# ---------- مركز الوثائق: بحث شامل ولوحة ملخص ----------
def display_status(status, revision, archived=False):
    if archived:
        return "archived"
    return {"draft": "draft_correction" if revision else "draft", "issued": "issued_correction" if revision else "issued"}[status]


def doc_amount(doc_type, results):
    """المبلغ الرئيسي للوثيقة الصادرة من لقطتها: الصافي للدفع (وضعية) أو TTC النهائي (جرد). البيان والحوصلة بلا مبلغ."""
    try:
        if doc_type == "situation":
            return D(results.get("net"))
        if doc_type == "inventory":
            return D((results.get("totals") or {}).get("final_contractual_ttc"))
    except Exception:
        return None
    return None


def _row_to_doc(r):
    snap = json.loads(r["snapshot_json"]) if r["snapshot_json"] else None
    archived = r["archived_at"] is not None
    live_name = r["project_name"]
    name = ((snap or {}).get("state", {}).get("project", {}) or {}).get("name") or live_name      # اسم المشروع وقت الإصدار
    contract = ((snap or {}).get("state", {}).get("project", {}) or {}).get("contract_no") or r["contract_no"]
    amount = doc_amount(r["doc_type"], snap["results"]) if snap else None
    return {"id": r["id"], "project_id": r["project_id"], "project_name": name, "live_project_name": live_name,
            "contract_no": contract, "doc_type": r["doc_type"], "label": DOC_LABELS[r["doc_type"]], "number": r["number"],
            "revision": r["revision"], "status": r["status"], "archived": archived,
            "display": display_status(r["status"], r["revision"], archived),
            "created_at": r["created_at"], "issued_at": r["issued_at"], "correction_reason": r["correction_reason"],
            "amount": amount}


def search_documents(conn, text="", doc_type=None, status=None, project_id=None, date_from=None, date_to=None,
                     include_archived=False, only_archived=False, amount_min=None, amount_max=None, limit=1000):
    """بحث شامل عبر كل المشاريع. text: يطابق رقم الوثيقة أو رقم العقد أو اسم المشروع (وقت الإصدار أو الحالي) أو النوع أو سبب التصحيح
    أو المبلغ نصًا. status: أحد DISPLAY_STATUSES. التواريخ بصيغة YYYY-MM-DD وتُطبَّق على تاريخ الإصدار (أو الإنشاء للمسودة)."""
    sql = ("SELECT d.id, d.project_id, d.doc_type, d.number, d.revision, d.status, d.created_at, d.issued_at, d.correction_reason, "
           "d.snapshot_json, p.name AS project_name, p.contract_no AS contract_no, a.archived_at AS archived_at "
           "FROM documents d JOIN projects p ON p.id=d.project_id LEFT JOIN doc_archive a ON a.doc_id=d.id WHERE 1=1")
    args = []
    if doc_type:
        sql += " AND d.doc_type=?"; args.append(doc_type)
    if project_id:
        sql += " AND d.project_id=?"; args.append(project_id)
    if only_archived:
        sql += " AND a.doc_id IS NOT NULL"
    elif not include_archived:
        sql += " AND a.doc_id IS NULL"
    if date_from:
        sql += " AND substr(COALESCE(d.issued_at, d.created_at),1,10) >= ?"; args.append(date_from)
    if date_to:
        sql += " AND substr(COALESCE(d.issued_at, d.created_at),1,10) <= ?"; args.append(date_to)
    sql += " ORDER BY COALESCE(d.issued_at, d.created_at) DESC, d.id DESC"
    q = (text or "").strip().lower()
    amin = D(amount_min) if amount_min not in (None, "") else None
    amax = D(amount_max) if amount_max not in (None, "") else None
    out = []
    for r in conn.execute(sql, args):
        d = _row_to_doc(r)
        if status and d["display"] != status:
            continue
        if amin is not None and (d["amount"] is None or d["amount"] < amin):
            continue
        if amax is not None and (d["amount"] is None or d["amount"] > amax):
            continue
        if q:
            hay = " ".join(str(x) for x in (
                d["number"] if d["number"] is not None else "", f"{d['number']:02d}" if d["number"] is not None else "",
                d["contract_no"] or "", d["project_name"] or "", d["live_project_name"] or "", d["label"],
                d["correction_reason"] or "", fmt(d["amount"]) if d["amount"] is not None else "",
                str(d["amount"]) if d["amount"] is not None else "")).lower()
            if q not in hay:
                continue
        d.pop("snapshot_json", None)
        out.append(d)
        if len(out) >= limit:
            break
    return out


def dashboard_stats(conn, stale_days=7):
    """أرقام اللوحة الرئيسية. الإجمالي = مجموع صافي الوضعيات الصادرة، بآخر مراجعة لكل رقم (التصحيحية تحل محل الأصل)."""
    from datetime import datetime, timedelta
    n = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    docs = search_documents(conn, include_archived=True, limit=100000)
    latest = {}
    for d in docs:
        if d["status"] == "issued" and d["doc_type"] == "situation" and d["amount"] is not None:
            k = (d["project_id"], d["number"])
            if k not in latest or d["revision"] > latest[k]["revision"]:
                latest[k] = d
    total = sum((d["amount"] for d in latest.values()), D(0))
    cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat(timespec="seconds")
    attention = []
    for d in docs:
        if d["status"] == "draft" and d["revision"]:
            attention.append({"kind": "correction_draft", "doc_id": d["id"], "project_id": d["project_id"],
                              "text": f"{d['label']} — نسخة تصحيحية غير مُصدرة ({d['project_name']})"})
        elif d["status"] == "draft" and d["created_at"] < cutoff:
            attention.append({"kind": "stale_draft", "doc_id": d["id"], "project_id": d["project_id"],
                              "text": f"{d['label']} — مسودة منذ أكثر من {stale_days} أيام ({d['project_name']})"})
    for p in conn.execute("SELECT id, name FROM projects WHERE archived=0"):
        try:
            k = len(quantity_conflicts(conn, p["id"]))
        except Exception:
            k = 0
        if k:
            attention.append({"kind": "conflicts", "doc_id": None, "project_id": p["id"],
                              "text": f"{p['name']} — {k} كمية متعارضة تحتاج حسمًا"})
    return {"projects": n("SELECT COUNT(*) FROM projects WHERE archived=0"),
            "projects_archived": n("SELECT COUNT(*) FROM projects WHERE archived=1"),
            "drafts": sum(1 for d in docs if d["status"] == "draft"),
            "issued": sum(1 for d in docs if d["status"] == "issued" and not d["archived"]),
            "corrections": sum(1 for d in docs if d["revision"]),
            "archived_docs": sum(1 for d in docs if d["archived"]),
            "total_net": total, "attention": attention,
            "by_display": {k: sum(1 for d in docs if d["display"] == k) for k in DISPLAY_STATUSES}}


def open_correction_draft(conn, doc_id):
    """رقم مسودة تصحيحية مفتوحة لنفس رقم الوثيقة إن وُجدت (لمنع إنشاء نسخ تصحيحية متوازية عن غير قصد)، وإلا None."""
    d = S.get_document(conn, doc_id)
    if d["number"] is None:
        return None
    r = conn.execute("SELECT id FROM documents WHERE project_id=? AND doc_type=? AND number=? AND status='draft' AND revision>0 "
                     "ORDER BY id DESC LIMIT 1", (d["project_id"], d["doc_type"], d["number"])).fetchone()
    return r[0] if r else None


def preview_pdf(conn, doc_id, path):
    """معاينة مطابقة للتصدير: تمر الوثيقة بنفس مسار Word→PDF (LibreOffice) الذي يُنتج ملف PDF النهائي، فلا تختلف عنه.
    ترمي RuntimeError إن تعذر LibreOffice؛ تتعامل الواجهة مع ذلك بمعاينة تقريبية وتنبّه المستخدم صراحةً."""
    from . import export as EX
    return EX.export_pdf(conn, doc_id, path)
