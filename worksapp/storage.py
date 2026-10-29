"""قاعدة SQLite المحلية: مشاريع، بنود، قياسات، وثائق، ترقيم، إصدار ثابت، نسخ احتياطي.

ثبات الوثائق مفروض في قاعدة البيانات نفسها بمشغّلات (triggers): لا تعديل ولا حذف
لأي وثيقة صادرة، حتى لو أخطأ الكود.
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime

from .formulas import BUILTIN_FORMULAS, Formula, validate_expr
from .money import D, q3
from .quantities import item_quantity
from . import alerts as A

SCHEMA_VERSION = "3"
SUPPORTED_VERSIONS = ("1", "2", "3")      # النسخ الاحتياطية القديمة تُقبل وتُرحَّل عند الفتح
DOC_TYPES = ("bayan", "hawsala", "situation", "inventory")

SCHEMA = """
CREATE TABLE schema_info(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE companies(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
  data_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE projects(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, contract_no TEXT, contract_date TEXT,
  owner TEXT, contractor TEXT, extra_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0, company_id INTEGER REFERENCES companies(id));
CREATE TABLE items(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
  ordinal INTEGER NOT NULL, code TEXT NOT NULL, description TEXT, unit TEXT,
  unit_price TEXT, contract_qty TEXT, section TEXT, UNIQUE(project_id, code));
CREATE TABLE formulas(code TEXT PRIMARY KEY, name TEXT NOT NULL, expr TEXT NOT NULL,
  inputs_json TEXT NOT NULL, unit_hint TEXT, builtin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE item_quantities(
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN ('direct','measured')),
  direct_qty TEXT, override_qty TEXT, override_reason TEXT,
  approved_qty TEXT, approved_source TEXT, approved_reason TEXT);
CREATE TABLE measure_lines(
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, formula_code TEXT NOT NULL REFERENCES formulas(code),
  inputs_json TEXT NOT NULL, label TEXT DEFAULT '', location TEXT DEFAULT '');
CREATE TABLE audit_log(id INTEGER PRIMARY KEY, at TEXT NOT NULL, entity TEXT NOT NULL,
  entity_id INTEGER, field TEXT, old_value TEXT, new_value TEXT, reason TEXT);
CREATE TABLE doc_counters(project_id INTEGER NOT NULL, doc_type TEXT NOT NULL,
  last_number INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(project_id, doc_type));
CREATE TABLE documents(
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
  doc_type TEXT NOT NULL CHECK(doc_type IN ('bayan','hawsala','situation','inventory')),
  number INTEGER, revision INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','issued')),
  parent_id INTEGER REFERENCES documents(id), correction_reason TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}', snapshot_json TEXT,
  created_at TEXT NOT NULL, issued_at TEXT);
CREATE TABLE doc_archive(
  doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE RESTRICT,
  archived_at TEXT NOT NULL, reason TEXT);
CREATE UNIQUE INDEX uq_doc_number ON documents(project_id, doc_type, number, revision)
  WHERE number IS NOT NULL;
CREATE TRIGGER documents_immutable_update BEFORE UPDATE ON documents
  WHEN OLD.status = 'issued'
  BEGIN SELECT RAISE(ABORT, 'الوثيقة الصادرة ثابتة ولا تُعدَّل'); END;
CREATE TRIGGER documents_immutable_delete BEFORE DELETE ON documents
  WHEN OLD.status = 'issued'
  BEGIN SELECT RAISE(ABORT, 'الوثيقة الصادرة لا تُحذف'); END;
"""


class IssueBlocked(Exception):
    def __init__(self, blocking):
        self.blocking = blocking
        super().__init__("; ".join(f"{b['problem']} ({b['affected']})" for b in blocking))


def _now():
    return datetime.now().isoformat(timespec="seconds")


def migrate(conn, path=None):
    """يرحّل قاعدة أقدم إلى المخطط الحالي دون فقد بيانات: يضيف الجداول والأعمدة والفهارس والمشغّلات الناقصة فقط.
    يأخذ نسخة احتياطية (path + .before_migrate) قبل أي تغيير. يعيد قائمة بما أُضيف (فارغة = لا شيء)."""
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    changes = []
    plan = []
    for name, typ, sql in ref.execute("SELECT name, type, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"):
        if typ == "table" and name not in have:
            plan.append(("create", name, sql))
        elif typ == "table":
            cur = {r[1] for r in conn.execute(f"PRAGMA table_info({name})")}
            for _cid, col, ctype, notnull, dflt, pk in ref.execute(f"PRAGMA table_info({name})"):
                if col not in cur:
                    plan.append(("column", f"{name}.{col}", (name, col, ctype, notnull, dflt)))
        elif name not in have:                       # فهرس أو مشغّل ناقص
            plan.append(("create", name, sql))
    ref.close()
    if not plan:
        _migrate_company_data(conn)
        _stamp_version(conn)
        return changes
    if path and os.path.exists(path) and not os.path.exists(path + ".before_migrate"):
        conn.commit()
        shutil.copy2(path, path + ".before_migrate")
    for kind, name, payload in plan:
        if kind == "create":
            conn.execute(payload)
        else:
            t, col, ctype, notnull, dflt = payload
            default = dflt if dflt is not None else (("0" if "INT" in (ctype or "").upper() else "''") if notnull else None)
            conn.execute(f"ALTER TABLE {t} ADD COLUMN {col} {ctype or ''}" + (f" DEFAULT {default}" if default is not None else ""))
        changes.append(name)
    conn.commit()
    _migrate_company_data(conn)
    _stamp_version(conn)
    return changes


def connect(path):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not new:
        migrate(conn, path)
    if new:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO schema_info VALUES('version', ?)", (SCHEMA_VERSION,))
        for f in BUILTIN_FORMULAS:
            conn.execute("INSERT INTO formulas VALUES(?,?,?,?,?,1)",
                         (f.code, f.name, f.expr, json.dumps(f.inputs, ensure_ascii=False), f.unit_hint))
        conn.commit()
    return conn


def log(conn, entity, entity_id, field, old, new, reason=""):
    conn.execute("INSERT INTO audit_log(at,entity,entity_id,field,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",
                 (_now(), entity, entity_id, field, None if old is None else str(old),
                  None if new is None else str(new), reason))


def _clear_quantity_approval(conn, item_id, why):
    """إبطال قرار حسم سابق تلقائيًا إذا تغير أحد مصادر الكمية، مع تسجيل السبب."""
    row = conn.execute("SELECT approved_qty,approved_source,approved_reason FROM item_quantities WHERE item_id=?", (item_id,)).fetchone()
    if row and row["approved_qty"] not in (None, ""):
        old = f"{row['approved_qty']} ({row['approved_source'] or ''})؛ {row['approved_reason'] or ''}"
        conn.execute("UPDATE item_quantities SET approved_qty=NULL,approved_source=NULL,approved_reason=NULL WHERE item_id=?", (item_id,))
        log(conn, "item_quantity", item_id, "approved_qty", old, None, f"أُلغي القرار السابق لأن المصدر تغير: {why}")



# ---------- الشركة المتعاقدة (بيانات ثابتة تُدخل مرة واحدة) ----------
# هذه الحقول تخص المؤسسة نفسها وتتكرر في كل مشروع؛ لذلك تُحفظ مرة واحدة في جدول companies
# وتُربط بها المشاريع. أما بيانات العقد (الاسم، الرقم، التاريخ، المصلحة المتعاقدة، المبلغ) فتبقى في المشروع.
COMPANY_FIELDS = (
    ("manager", "المسير"), ("address", "العنوان / المقر الاجتماعي"), ("wilaya", "الولاية"),
    ("place", "مكان التحرير (المدينة)"), ("rc_no", "رقم السجل التجاري"), ("rc_date", "تاريخ السجل التجاري"),
    ("nif", "الرقم الجبائي"), ("article_no", "رقم المادة"), ("nis", "رقم التعريف الإحصائي"),
    ("bank", "البنك والوكالة"), ("rib", "رقم الحساب البنكي (RIB)"),
)
COMPANY_KEYS = tuple(k for k, _ in COMPANY_FIELDS)


def _company_row(r):
    d = json.loads(r["data_json"] or "{}")
    return {"id": r["id"], "name": r["name"], "is_default": bool(r["is_default"]),
            **{k: d.get(k, "") for k in COMPANY_KEYS}}


def list_companies(conn):
    return [_company_row(r) for r in conn.execute("SELECT * FROM companies ORDER BY is_default DESC, id")]


def get_company(conn, company_id):
    r = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone() if company_id else None
    return _company_row(r) if r else None


def default_company(conn):
    r = conn.execute("SELECT * FROM companies ORDER BY is_default DESC, id LIMIT 1").fetchone()
    return _company_row(r) if r else None


def save_company(conn, company_id, name, make_default=None, **data):
    """ينشئ شركة (company_id=None) أو يعدّل بياناتها. تعديل الشركة لا يمس الوثائق الصادرة (لها لقطة)."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("اسم الشركة مطلوب")
    unknown = set(data) - set(COMPANY_KEYS)
    if unknown:
        raise ValueError(f"حقل غير معروف: {sorted(unknown)[0]}")
    clean = {k: str(v).strip() for k, v in data.items() if v is not None and str(v).strip()}
    if company_id is None:
        if conn.execute("SELECT 1 FROM companies WHERE name=?", (name,)).fetchone():
            raise ValueError("توجد شركة بهذا الاسم")
        first = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
        cur = conn.execute("INSERT INTO companies(name,is_default,data_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                           (name, 1 if (first or make_default) else 0, json.dumps(clean, ensure_ascii=False), _now(), _now()))
        company_id = cur.lastrowid
        if make_default and not first:
            conn.execute("UPDATE companies SET is_default=0 WHERE id<>?", (company_id,))
        log(conn, "company", company_id, "created", None, name, "إنشاء شركة")
    else:
        old = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if old is None:
            raise ValueError("الشركة غير موجودة")
        if conn.execute("SELECT 1 FROM companies WHERE name=? AND id<>?", (name, company_id)).fetchone():
            raise ValueError("توجد شركة بهذا الاسم")
        old_data = json.loads(old["data_json"] or "{}")
        if old["name"] != name:
            log(conn, "company", company_id, "name", old["name"], name, "تعديل بيانات الشركة")
        for k in COMPANY_KEYS:
            if (old_data.get(k) or "") != clean.get(k, ""):
                log(conn, "company", company_id, k, old_data.get(k), clean.get(k), "تعديل بيانات الشركة")
        conn.execute("UPDATE companies SET name=?, data_json=?, updated_at=? WHERE id=?",
                     (name, json.dumps(clean, ensure_ascii=False), _now(), company_id))
        if make_default:
            conn.execute("UPDATE companies SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END", (company_id,))
    conn.execute("UPDATE projects SET contractor=? WHERE company_id=?", (name, company_id))   # نسخة الاسم للعرض والبحث
    conn.commit()
    return company_id


def ensure_company(conn, name, seed=None):
    """يعيد رقم الشركة باسمها، وينشئها عند الغياب. يملأ الحقول الفارغة فقط من seed (دون استبدال بيانات مُدخلة)."""
    name = str(name).strip()
    r = conn.execute("SELECT * FROM companies WHERE name=?", (name,)).fetchone()
    seed = {k: v for k, v in (seed or {}).items() if k in COMPANY_KEYS and v}
    if r is None:
        return save_company(conn, None, name, **seed)
    data = json.loads(r["data_json"] or "{}")
    fill = {k: v for k, v in seed.items() if not data.get(k)}
    if fill:
        data.update(fill)
        conn.execute("UPDATE companies SET data_json=?, updated_at=? WHERE id=?",
                     (json.dumps(data, ensure_ascii=False), _now(), r["id"]))
        conn.commit()
    return r["id"]


def set_project_company(conn, project_id, company_id):
    c = get_company(conn, company_id)
    if c is None:
        raise ValueError("الشركة غير موجودة")
    old = conn.execute("SELECT company_id FROM projects WHERE id=?", (project_id,)).fetchone()
    if old is None:
        raise ValueError("المشروع غير موجود")
    if old[0] != company_id:
        conn.execute("UPDATE projects SET company_id=?, contractor=?, updated_at=? WHERE id=?",
                     (company_id, c["name"], _now(), project_id))
        log(conn, "project", project_id, "company_id", old[0], company_id, "ربط المشروع بشركة")
    conn.commit()


def company_for_project(conn, project_id):
    """شركة المشروع الحية. تعيد None إن لم تُدخل أي شركة بعد."""
    r = conn.execute("SELECT company_id FROM projects WHERE id=?", (project_id,)).fetchone()
    return get_company(conn, r[0]) if r and r[0] else None


def _migrate_company_data(conn):
    """ترحيل آمن وقابل للتكرار: المشاريع القديمة التي لها اسم مقاول وحقول مؤسسة في extra_json
    تُنشأ لها شركة وتُربط بها. لا يُحذف شيء من الحقول القديمة (تبقى قراءة قديمة للوثائق الصادرة)."""
    rows = conn.execute("SELECT id, contractor, extra_json FROM projects WHERE company_id IS NULL").fetchall()
    if not rows:
        return
    for r in rows:
        name = (r["contractor"] or "").strip()
        if not name:
            continue
        extra = json.loads(r["extra_json"] or "{}")
        cid = ensure_company(conn, name, seed={k: extra.get(k) for k in COMPANY_KEYS})
        conn.execute("UPDATE projects SET company_id=? WHERE id=?", (cid, r["id"]))
    dflt = default_company(conn)
    if dflt:
        conn.execute("UPDATE projects SET company_id=?, contractor=? WHERE company_id IS NULL", (dflt["id"], dflt["name"]))
    conn.commit()


def _stamp_version(conn):
    conn.execute("INSERT INTO schema_info(key,value) VALUES('version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (SCHEMA_VERSION,))
    conn.commit()


# ---------- الإعدادات ----------
def set_setting(conn, key, value):
    conn.execute("INSERT INTO app_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))
    conn.commit()


def get_setting(conn, key, default=None):
    r = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


# ---------- المشروع والبنود ----------
def create_project(conn, name, **fields):
    extra = fields.pop("extra", {})
    settings = fields.pop("settings", {})
    company_id = fields.get("company_id")
    if company_id is None and fields.get("contractor"):
        company_id = ensure_company(conn, fields["contractor"])          # توافق مع الاستدعاء القديم بالاسم
    if company_id is None:
        d = default_company(conn)
        company_id = d["id"] if d else None                                # الشركة الثابتة تُربط تلقائيًا
    c = get_company(conn, company_id)
    cur = conn.execute(
        "INSERT INTO projects(name,contract_no,contract_date,owner,contractor,company_id,extra_json,settings_json,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (name, fields.get("contract_no"), fields.get("contract_date"), fields.get("owner"),
         c["name"] if c else None, company_id, json.dumps(extra, ensure_ascii=False),
         json.dumps(settings, ensure_ascii=False), _now(), _now()))
    conn.commit()
    return cur.lastrowid


def update_project(conn, project_id, **fields):
    allowed = {"name", "contract_no", "contract_date", "owner", "contractor", "company_id"}
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(k)
        if k == "company_id":
            set_project_company(conn, project_id, v)
            continue
        if k == "contractor":                       # توافق قديم: الاسم يُحوَّل إلى ربط بشركة
            if v:
                set_project_company(conn, project_id, ensure_company(conn, v))
            continue
        row = conn.execute(f"SELECT {k} FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("المشروع غير موجود")
        old = row[0]
        if old != v:
            conn.execute(f"UPDATE projects SET {k}=?, updated_at=? WHERE id=?", (v, _now(), project_id))
            log(conn, "project", project_id, k, old, v, "تعديل بيانات المشروع")
    conn.commit()


def issued_count(conn, project_id):
    return conn.execute("SELECT COUNT(*) FROM documents WHERE project_id=? AND status='issued'", (project_id,)).fetchone()[0]


def archive_project(conn, project_id, on=True):
    """الأرشفة تُخفي المشروع من القائمة دون المساس بوثائقه الصادرة (الحل لمشروع له وثائق صادرة)."""
    conn.execute("UPDATE projects SET archived=?, updated_at=? WHERE id=?", (1 if on else 0, _now(), project_id))
    log(conn, "project", project_id, "archived", None, int(bool(on)), "أرشفة" if on else "إلغاء أرشفة")
    conn.commit()


def delete_project(conn, project_id):
    """حذف نهائي لمشروع **ليس له وثائق صادرة** (تُحذف معه بنوده ومسوداته). الوثائق الصادرة ثابتة بقرار التصميم:
    إن وُجدت ترفض الدالة وتُستعمل الأرشفة بدلًا من الحذف. يعيد (عدد البنود، عدد المسودات)."""
    n = issued_count(conn, project_id)
    if n:
        raise ValueError(f"لا يمكن حذف مشروع له {n} وثيقة صادرة (الوثائق الصادرة ثابتة). يمكنك أرشفته بدلًا من ذلك.")
    name = conn.execute("SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
    if name is None:
        raise ValueError("المشروع غير موجود")
    n_items = conn.execute("SELECT COUNT(*) FROM items WHERE project_id=?", (project_id,)).fetchone()[0]
    n_drafts = conn.execute("SELECT COUNT(*) FROM documents WHERE project_id=?", (project_id,)).fetchone()[0]
    try:
        conn.execute("DELETE FROM documents WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM doc_counters WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM items WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        log(conn, "project", project_id, "deleted", name[0], None, f"حذف نهائي ({n_items} بند، {n_drafts} مسودة)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n_items, n_drafts


def delete_draft(conn, doc_id):
    d = get_document(conn, doc_id)
    if d["status"] != "draft":
        raise ValueError("الوثيقة الصادرة ثابتة ولا تُحذف. للتصحيح أنشئ نسخة تصحيحية.")
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    log(conn, "document", doc_id, "deleted", d["doc_type"], None, "حذف مسودة")
    conn.commit()


def project_settings(conn, project_id):
    return json.loads(conn.execute("SELECT settings_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])


def set_project_settings(conn, project_id, settings):
    old = conn.execute("SELECT settings_json FROM projects WHERE id=?", (project_id,)).fetchone()
    new_json = json.dumps(settings, ensure_ascii=False, sort_keys=True, default=str)
    same = bool(old) and json.loads(old[0] or "{}") == settings
    if old and not same:
        conn.execute("UPDATE projects SET settings_json=?, updated_at=? WHERE id=?",
                     (new_json, _now(), project_id))
        log(conn, "project", project_id, "settings_json", old[0], new_json, "تعديل إعدادات المشروع")
    conn.commit()


def add_item(conn, project_id, code, description, unit, unit_price, contract_qty, ordinal=None, section=None):
    if not str(code or "").strip():
        raise ValueError("رقم البند مطلوب")
    price, qty = D(unit_price), D(contract_qty)
    if price is not None and price < 0:
        raise ValueError("سعر الوحدة لا يقبل قيمة سالبة")
    if qty is not None and qty < 0:
        raise ValueError("الكمية التعاقدية لا تقبل قيمة سالبة")
    if ordinal is None:
        ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM items WHERE project_id=?", (project_id,)).fetchone()[0]
    cur = conn.execute("INSERT INTO items(project_id,ordinal,code,description,unit_price,contract_qty,unit,section) VALUES(?,?,?,?,?,?,?,?)",
                       (project_id, ordinal, str(code).strip(), description, str(price) if price is not None else None,
                        str(qty) if qty is not None else None, unit, section))
    conn.commit()
    return cur.lastrowid


ITEM_FIELDS = {"code": "رقم البند", "description": "وصف البند", "unit": "الوحدة", "unit_price": "سعر الوحدة",
               "contract_qty": "الكمية التعاقدية", "section": "الفصل"}


def update_item_field(conn, item_id, field, value):
    """تعديل حقل واحد من بند. يرمي ValueError برسالة تذكر اسم الحقل. الوثائق الصادرة لا تتأثر (لقطات)."""
    if field not in ITEM_FIELDS:
        raise ValueError(field)
    label = ITEM_FIELDS[field]
    value = None if value is None or str(value).strip() == "" else str(value).strip()
    if field == "code" and value is None:
        raise ValueError("رقم البند مطلوب")
    if field in ("unit_price", "contract_qty") and value is not None:
        try:
            n = D(value)
        except ValueError:
            raise ValueError(f"{label}: «{value}» ليس رقمًا صحيحًا")
        if n < 0:
            raise ValueError(f"{label}: لا يقبل قيمة سالبة")
        value = str(n)
    old = conn.execute(f"SELECT {field} FROM items WHERE id=?", (item_id,)).fetchone()[0]
    try:
        conn.execute(f"UPDATE items SET {field}=? WHERE id=?", (value, item_id))
    except sqlite3.IntegrityError:
        raise ValueError("رقم البند مستعمل في بند آخر داخل المشروع")
    if old != value and field == "code":
        _clear_quantity_approval(conn, item_id, "تغيير رقم البند")
    if old != value:
        log(conn, "item", item_id, field, old, value, "تعديل مباشر")
    conn.commit()


def delete_item(conn, item_id):
    """يحذف البند وكمياته وأسطر قياسه بعد تسجيل لقطة من بياناته في سجل التدقيق."""
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise ValueError("البند غير موجود")
    log(conn, "item", item_id, "deleted", json.dumps(dict(row), ensure_ascii=False, default=str), None, "حذف بند")
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()


def add_items_bulk(conn, project_id, rows):
    """إدراج ذري: إما كل البنود أو لا شيء."""
    try:
        ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),0) FROM items WHERE project_id=?", (project_id,)).fetchone()[0]
        for r in rows:
            ordinal += 1
            conn.execute("INSERT INTO items(project_id,ordinal,code,description,unit,unit_price,contract_qty,section) VALUES(?,?,?,?,?,?,?,?)",
                         (project_id, ordinal, r["code"], r.get("description"), r.get("unit"),
                          None if r.get("price") is None else str(r["price"]),
                          None if r.get("qty") is None else str(r["qty"]), r.get("section")))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# حقول العقد الخاصة بالمشروع (تتغير من مشروع لآخر). حقول المؤسسة الثابتة انتقلت إلى COMPANY_FIELDS.
PROJECT_EXTRA_FIELDS = (
    ("owner_rep", "ممثل المصلحة المتعاقدة"), ("contract_amount", "مبلغ العقد (كما يُطبع، دج)"),
)


def set_doc_config(conn, doc_id, **kv):
    """يضبط حقولًا في config مسودة (تاريخ الوثيقة date، مكان place، final…). الصادرة ثابتة (مشغّل قاعدة البيانات)."""
    d = get_document(conn, doc_id)
    if d["status"] != "draft":
        raise ValueError("الوثيقة الصادرة ثابتة؛ أنشئ نسخة تصحيحية")
    pl = json.loads(d["payload_json"] or "{}")
    cfg = pl.setdefault("config", {})
    for k, v in kv.items():
        if v in (None, ""):
            cfg.pop(k, None)
        else:
            cfg[k] = v
    update_draft_payload(conn, doc_id, pl)


def update_project_extra(conn, project_id, **kv):
    row = conn.execute("SELECT extra_json FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise ValueError("المشروع غير موجود")
    extra = json.loads(row[0] or "{}")
    changed = []
    for k, v in kv.items():
        old = extra.get(k)
        if v:
            extra[k] = v
            new = v
        else:
            extra.pop(k, None)
            new = None
        if old != new:
            changed.append((k, old, new))
    if changed:
        conn.execute("UPDATE projects SET extra_json=?, updated_at=? WHERE id=?",
                     (json.dumps(extra, ensure_ascii=False), _now(), project_id))
        for k, old, new in changed:
            log(conn, "project", project_id, f"extra.{k}", old, new, "تعديل بيانات إضافية")
    conn.commit()


def update_item_price(conn, item_id, price, reason=""):
    value = D(price)
    if value is None or value < 0:
        raise ValueError("سعر الوحدة مطلوب ويجب ألا يكون سالبًا")
    row = conn.execute("SELECT unit_price FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise ValueError("البند غير موجود")
    old = row[0]
    conn.execute("UPDATE items SET unit_price=? WHERE id=?", (str(value), item_id))
    if old != str(value):
        log(conn, "item", item_id, "unit_price", old, value, reason)
    conn.commit()


def list_items(conn, project_id):
    return [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id=? ORDER BY ordinal", (project_id,))]


# ---------- ترتيب البنود ----------
def _ordered_ids(conn, project_id):
    return [r[0] for r in conn.execute("SELECT id FROM items WHERE project_id=? ORDER BY ordinal, id", (project_id,))]


def _write_order(conn, project_id, ids, reason):
    """يكتب الترتيب الجديد (1..n) ويسجل في سجل التدقيق كل بند تغير موضعه. لا يمس الوثائق الصادرة (لقطات)."""
    old = {r["id"]: r["ordinal"] for r in conn.execute("SELECT id, ordinal FROM items WHERE project_id=?", (project_id,))}
    if sorted(ids) != sorted(old):
        raise ValueError("قائمة الترتيب لا تطابق بنود المشروع")
    for pos, iid in enumerate(ids, start=1):
        if old[iid] != pos:
            conn.execute("UPDATE items SET ordinal=? WHERE id=?", (pos, iid))
            log(conn, "item", iid, "ordinal", old[iid], pos, reason)
    conn.commit()


def move_item(conn, item_id, where):
    """where: up | down | top | bottom | رقم الموضع الجديد (يبدأ من 1). يعيد الموضع الجديد."""
    row = conn.execute("SELECT project_id FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise ValueError("البند غير موجود")
    pid = row[0]
    ids = _ordered_ids(conn, pid)
    i = ids.index(item_id)
    if where == "up":
        j = max(0, i - 1)
    elif where == "down":
        j = min(len(ids) - 1, i + 1)
    elif where == "top":
        j = 0
    elif where == "bottom":
        j = len(ids) - 1
    else:
        try:
            j = int(where) - 1
        except (TypeError, ValueError):
            raise ValueError("الموضع يجب أن يكون رقمًا صحيحًا")
        if not 0 <= j < len(ids):
            raise ValueError(f"الموضع يجب أن يكون بين 1 و{len(ids)}")
    ids.insert(j, ids.pop(i))
    _write_order(conn, pid, ids, "إعادة ترتيب البنود")
    return j + 1


def reorder_items(conn, project_id, ordered_ids):
    _write_order(conn, project_id, list(ordered_ids), "إعادة ترتيب البنود")


def _natural_key(code):
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(code))]


def sort_items_by_code(conn, project_id):
    rows = list_items(conn, project_id)
    ids = [r["id"] for r in sorted(rows, key=lambda r: _natural_key(r["code"]))]
    _write_order(conn, project_id, ids, "ترتيب البنود حسب الرقم")


def insert_item_after(conn, project_id, after_item_id, code, description=None, unit=None, unit_price=None,
                      contract_qty=None, section=None):
    """يضيف بندًا مباشرة بعد بند محدد (أو في النهاية إن كان after_item_id=None)."""
    new_id = add_item(conn, project_id, code, description, unit, unit_price, contract_qty, section=section)
    if after_item_id is not None:
        ids = [i for i in _ordered_ids(conn, project_id) if i != new_id]
        if after_item_id in ids:
            ids.insert(ids.index(after_item_id) + 1, new_id)
            _write_order(conn, project_id, ids, "إدراج بند")
    return new_id


def duplicate_item(conn, item_id, new_code):
    """نسخ بند (الوصف والوحدة والسعر والكمية التعاقدية والفصل) بعد الأصل مباشرة. الكميات المنجزة لا تُنسخ."""
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if it is None:
        raise ValueError("البند غير موجود")
    return insert_item_after(conn, it["project_id"], item_id, new_code, it["description"], it["unit"],
                             it["unit_price"], it["contract_qty"], it["section"])


# ---------- المعادلات ----------
def load_formulas(conn):
    return {r["code"]: Formula(r["code"], r["name"], r["expr"], json.loads(r["inputs_json"]),
                               r["unit_hint"] or "", bool(r["builtin"]))
            for r in conn.execute("SELECT * FROM formulas")}


def add_formula(conn, code, name, expr, inputs, unit_hint=""):
    validate_expr(expr, [i["name"] for i in inputs])
    conn.execute("INSERT INTO formulas VALUES(?,?,?,?,?,0)",
                 (code, name, expr, json.dumps(inputs, ensure_ascii=False), unit_hint))
    conn.commit()


# ---------- الكميات والقياسات (بيان الأشغال) ----------
def set_direct_quantity(conn, item_id, qty):
    """إدخال مباشر: يبطل أي اعتماد قديم لأن قيمة المصدر تغيرت ويسجل القيمة السابقة."""
    value = D(qty)
    if value is None:
        raise ValueError("الكمية المباشرة مطلوبة؛ لا تستخدم قيمة فارغة بدل الصفر")
    if value < 0:
        raise ValueError("الكمية المباشرة لا تقبل قيمة سالبة؛ استخدم أسطر القياس للخصومات الميدانية")
    old_row = conn.execute("SELECT direct_qty,mode FROM item_quantities WHERE item_id=?", (item_id,)).fetchone()
    old = old_row["direct_qty"] if old_row else None
    _clear_quantity_approval(conn, item_id, "تغيير الكمية المباشرة")
    conn.execute("INSERT INTO item_quantities(item_id,mode,direct_qty) VALUES(?, 'direct', ?) "
                 "ON CONFLICT(item_id) DO UPDATE SET mode='direct', direct_qty=excluded.direct_qty",
                 (item_id, str(value)))
    if old != str(value) or (old_row and old_row["mode"] != "direct"):
        log(conn, "item_quantity", item_id, "direct_qty", old, value, "تعديل الكمية المباشرة")
    conn.commit()


def add_measure_line(conn, item_id, formula_code, inputs, label="", location=""):
    formulas = load_formulas(conn)
    if formula_code not in formulas:
        raise ValueError("المعادلة المحددة غير موجودة")
    from .formulas import evaluate
    evaluate(formulas[formula_code], inputs)  # تحقّق قبل إبطال قرار أو كتابة أي بيانات
    _clear_quantity_approval(conn, item_id, "إضافة/تغيير سطر قياس")
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM measure_lines WHERE item_id=?", (item_id,)).fetchone()[0]
    conn.execute("INSERT INTO item_quantities(item_id,mode) VALUES(?, 'measured') "
                 "ON CONFLICT(item_id) DO UPDATE SET mode='measured'", (item_id,))
    serialized = json.dumps({k: str(v) for k, v in inputs.items()}, ensure_ascii=False, sort_keys=True)
    cur = conn.execute("INSERT INTO measure_lines(item_id,position,formula_code,inputs_json,label,location) VALUES(?,?,?,?,?,?)",
                       (item_id, pos, formula_code, serialized, label, location))
    log(conn, "measure_line", cur.lastrowid, "created", None,
        json.dumps({"item_id": item_id, "formula_code": formula_code, "inputs": json.loads(serialized), "label": label, "location": location}, ensure_ascii=False),
        "إضافة سطر قياس")
    conn.commit()


def update_measure_line(conn, line_id, formula_code, inputs, label="", location=""):
    """تعديل سطر قياس موجود، مع إبطال أي اعتماد كمية سابق وتسجيل كامل التغيير."""
    row = conn.execute("SELECT * FROM measure_lines WHERE id=?", (line_id,)).fetchone()
    if row is None:
        raise ValueError("سطر القياس غير موجود")
    formulas = load_formulas(conn)
    if formula_code not in formulas:
        raise ValueError("المعادلة المحددة غير موجودة")
    from .formulas import evaluate
    evaluate(formulas[formula_code], inputs)
    old = {k: row[k] for k in ("item_id", "position", "formula_code", "inputs_json", "label", "location")}
    serialized = json.dumps({k: str(v) for k, v in inputs.items()}, ensure_ascii=False, sort_keys=True)
    new = {"item_id": row["item_id"], "position": row["position"], "formula_code": formula_code,
           "inputs_json": serialized, "label": label, "location": location}
    _clear_quantity_approval(conn, row["item_id"], "تعديل سطر قياس")
    conn.execute("UPDATE measure_lines SET formula_code=?,inputs_json=?,label=?,location=? WHERE id=?",
                 (formula_code, serialized, label, location, line_id))
    log(conn, "measure_line", line_id, "updated", json.dumps(old, ensure_ascii=False),
        json.dumps(new, ensure_ascii=False), "تعديل سطر قياس")
    conn.commit()


def delete_measure_line(conn, line_id):
    """حذف سطر قياس وإعادة ترقيم بقية أسطر البند بشكل متسلسل."""
    row = conn.execute("SELECT * FROM measure_lines WHERE id=?", (line_id,)).fetchone()
    if row is None:
        raise ValueError("سطر القياس غير موجود")
    old = {k: row[k] for k in ("item_id", "position", "formula_code", "inputs_json", "label", "location")}
    _clear_quantity_approval(conn, row["item_id"], "حذف سطر قياس")
    conn.execute("DELETE FROM measure_lines WHERE id=?", (line_id,))
    conn.execute("UPDATE measure_lines SET position=position-1 WHERE item_id=? AND position>?",
                 (row["item_id"], row["position"]))
    log(conn, "measure_line", line_id, "deleted", json.dumps(old, ensure_ascii=False), None, "حذف سطر قياس")
    conn.commit()


def set_override(conn, item_id, qty, reason):
    row = conn.execute("SELECT override_qty FROM item_quantities WHERE item_id=?", (item_id,)).fetchone()
    value = D(qty)
    if row is None:
        if value is None:
            return  # لا يوجد تعديل سابق لمسحه
        raise ValueError("أدخل كمية مباشرة أو سطر قياس صالحًا قبل تطبيق تعديل يدوي")
    if value is not None:
        if value < 0:
            raise ValueError("الكمية النهائية المعدلة لا تقبل قيمة سالبة")
        if get_quantity(conn, item_id).computed is None:
            raise ValueError("لا يمكن اعتماد تعديل يدوي قبل اكتمال الكمية الأصلية المحسوبة")
    _clear_quantity_approval(conn, item_id, "تغيير التعديل اليدوي")
    old = row["override_qty"]
    conn.execute("UPDATE item_quantities SET override_qty=?, override_reason=? WHERE item_id=?",
                 (None if value is None else str(value), reason, item_id))
    if old != (None if value is None else str(value)):
        log(conn, "item_quantity", item_id, "override_qty", old, value, reason)
    conn.commit()


def get_quantity(conn, item_id):
    q = conn.execute("SELECT * FROM item_quantities WHERE item_id=?", (item_id,)).fetchone()
    if q is None:
        return item_quantity("direct", None)   # => QTY_MISSING، لا صفر مفترض
    lines = [(r["formula_code"], json.loads(r["inputs_json"]), r["label"])
             for r in conn.execute("SELECT * FROM measure_lines WHERE item_id=? ORDER BY position", (item_id,))]
    result = item_quantity(q["mode"], q["direct_qty"], lines, load_formulas(conn),
                           q["override_qty"], q["override_reason"] or "")
    # قرار حسم تعارض المصادر له أولوية صريحة ويظل منفصلًا عن التعديل اليدوي.
    if q["approved_qty"] not in (None, ""):
        result.final = D(q["approved_qty"])
        result.shown = q3(result.final)
        result.approved = True
        result.approved_source = q["approved_source"] or ""
        result.approved_reason = q["approved_reason"] or ""
    return result


def count_measure_lines(conn, item_id):
    return conn.execute("SELECT COUNT(*) FROM measure_lines WHERE item_id=?", (item_id,)).fetchone()[0]


def approve_quantity(conn, item_id, qty, source, reason):
    """قرار المستخدم عند تعارض المصادر: تُحفظ الكمية والمصدر والسبب، وتبقى القيم الأصلية في مصادرها."""
    if not str(reason or "").strip():
        raise ValueError("سبب الاعتماد مطلوب")
    if not str(source or "").strip():
        raise ValueError("مصدر الكمية المعتمدة مطلوب")
    normalized = D(qty)
    if normalized is None:
        raise ValueError("الكمية المعتمدة مطلوبة")
    if normalized < 0:
        raise ValueError("الكمية المعتمدة لا تقبل قيمة سالبة")
    conn.execute("INSERT INTO item_quantities(item_id,mode) VALUES(?, 'direct') ON CONFLICT(item_id) DO NOTHING", (item_id,))
    old = conn.execute("SELECT approved_qty,approved_source,approved_reason FROM item_quantities WHERE item_id=?", (item_id,)).fetchone()
    old_value = None if old is None or old["approved_qty"] is None else f"{old['approved_qty']} ({old['approved_source'] or ''})؛ {old['approved_reason'] or ''}"
    conn.execute("UPDATE item_quantities SET approved_qty=?, approved_source=?, approved_reason=? WHERE item_id=?",
                 (str(normalized), str(source).strip(), str(reason).strip(), item_id))
    log(conn, "item_quantity", item_id, "approved_qty", old_value, f"{normalized} ({source})", reason)
    conn.commit()


# ---------- الوثائق والترقيم والإصدار ----------
def _next_number(conn, project_id, doc_type):
    conn.execute("INSERT OR IGNORE INTO doc_counters VALUES(?,?,0)", (project_id, doc_type))
    conn.execute("UPDATE doc_counters SET last_number=last_number+1 WHERE project_id=? AND doc_type=?", (project_id, doc_type))
    return conn.execute("SELECT last_number FROM doc_counters WHERE project_id=? AND doc_type=?", (project_id, doc_type)).fetchone()[0]


def create_draft(conn, project_id, doc_type, payload=None):
    """حجز الرقم عند المسودة أو عند الإصدار حسب إعداد numbering_mode."""
    if doc_type not in DOC_TYPES:
        raise ValueError(doc_type)
    number = _next_number(conn, project_id, doc_type) if get_setting(conn, "numbering_mode", "issue") == "draft" else None
    cur = conn.execute("INSERT INTO documents(project_id,doc_type,number,payload_json,created_at) VALUES(?,?,?,?,?)",
                       (project_id, doc_type, number, json.dumps(payload or {}, ensure_ascii=False, default=str), _now()))
    # أحدث مسودة حوصلة/وضعية تصبح مصدر المقارنة الحالي؛ قرارات الحسم السابقة
    # لا تملك بصمة للمصدر القديم، لذلك نبطلها صراحةً كي لا تُستخدم مع مصدر جديد.
    if doc_type in ("hawsala", "situation"):
        for it in list_items(conn, project_id):
            _clear_quantity_approval(conn, it["id"], f"إنشاء مسودة جديدة من نوع {doc_type}")
    conn.commit()
    return cur.lastrowid


def get_document(conn, doc_id):
    return dict(conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def update_draft_payload(conn, doc_id, payload):
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError("الوثيقة غير موجودة")
    if doc["status"] != "draft":
        raise ValueError("لا يمكن تعديل وثيقة صادرة")
    if not isinstance(payload, dict):
        raise ValueError("بيانات المسودة يجب أن تكون كائنًا")
    old_json = doc["payload_json"] or "{}"
    new_json = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    old_payload = json.loads(old_json)
    # إذا كانت هذه أحدث وثيقة من مصدر يعتمد عليه حسم الكميات، فإن تعديل القيم
    # السابقة/الفترة/التراكمي يبطل قرار الحسم للبنود المتأثرة فقط.
    if doc["doc_type"] in ("hawsala", "situation"):
        latest = conn.execute("SELECT id FROM documents WHERE project_id=? AND doc_type=? ORDER BY id DESC LIMIT 1",
                              (doc["project_id"], doc["doc_type"])).fetchone()
        if latest and latest[0] == doc_id:
            old_rows = old_payload.get("rows", {})
            new_rows = payload.get("rows", {})
            changed_codes = set()
            for code in set(old_rows) | set(new_rows):
                a, b = old_rows.get(code, {}), new_rows.get(code, {})
                if any(a.get(k) != b.get(k) for k in ("prev", "period", "cum")):
                    changed_codes.add(code)
            if changed_codes:
                for code in changed_codes:
                    it = conn.execute("SELECT id FROM items WHERE project_id=? AND code=?",
                                      (doc["project_id"], code)).fetchone()
                    if it:
                        _clear_quantity_approval(conn, it[0], f"تغيير مصدر الكمية في مسودة {doc['doc_type']}")
    if old_json != new_json:
        conn.execute("UPDATE documents SET payload_json=? WHERE id=?", (new_json, doc_id))
        log(conn, "document", doc_id, "payload_json", old_json, new_json, "تعديل بيانات المسودة")
    conn.commit()


def capture_project_state(conn, project_id):
    p = dict(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
    items = []
    for it in list_items(conn, project_id):
        qr = get_quantity(conn, it["id"])
        qrow = conn.execute("SELECT * FROM item_quantities WHERE item_id=?", (it["id"],)).fetchone()
        lines = [dict(r) for r in conn.execute("SELECT * FROM measure_lines WHERE item_id=? ORDER BY position", (it["id"],))]
        items.append({**it, "quantity_row": dict(qrow) if qrow else None, "measure_lines": lines,
                      "quantity_final": None if qr.final is None else str(qr.final),
                      "quantity_computed": None if qr.computed is None else str(qr.computed)})
    formulas = {c: {"name": f.name, "expr": f.expr, "inputs": f.inputs} for c, f in load_formulas(conn).items()}
    return {"project": p, "company": company_for_project(conn, project_id), "items": items, "formulas": formulas, "app_settings": {
        r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM app_settings")}}


def issue_document(conn, doc_id, alert_list, results, explicit_approval=False):
    """«اعتماد وإصدار»: يتطلب موافقة صريحة، ويفشل عند وجود تنبيه مانع بعد تطبيق سياسة الشدّة.
    يُحفظ لقطة ثابتة كاملة (بيانات المشروع + النتائج + التنبيهات) لا تتغير بعدها."""
    if not explicit_approval:
        raise PermissionError("الاعتماد يتطلب إجراءً صريحًا من المستخدم")
    doc = get_document(conn, doc_id)
    if doc["status"] != "draft":
        raise ValueError("الوثيقة ليست مسودة")
    overrides = get_setting(conn, "alert_severity", {})
    A.apply_policy(alert_list, overrides)
    blocking = [a.to_dict() for a in A.blocking(alert_list)]
    if blocking:
        raise IssueBlocked(blocking)
    number = doc["number"] if doc["number"] is not None else _next_number(conn, doc["project_id"], doc["doc_type"])
    snapshot = {"state": capture_project_state(conn, doc["project_id"]),
                "payload": json.loads(doc["payload_json"]), "results": results,
                "alerts": [a.to_dict() for a in alert_list]}
    conn.execute("UPDATE documents SET status='issued', number=?, snapshot_json=?, issued_at=? WHERE id=?",
                 (number, json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str), _now(), doc_id))
    log(conn, "document", doc_id, "issued", "draft", "issued", f"إصدار الوثيقة برقم {number}")
    conn.commit()
    return number


def create_correction(conn, doc_id, reason):
    """نسخة تصحيحية جديدة مرتبطة بالأصل (يبقى الأصل كما هو). الرقم نفسه + رقم مراجعة أعلى (افتراض يحتاج تأكيدًا)."""
    if not reason:
        raise ValueError("سبب التصحيح مطلوب")
    d = get_document(conn, doc_id)
    if d["status"] != "issued":
        raise ValueError("التصحيح يخص وثيقة صادرة فقط")
    rev = conn.execute("SELECT MAX(revision) FROM documents WHERE project_id=? AND doc_type=? AND number=?",
                       (d["project_id"], d["doc_type"], d["number"])).fetchone()[0] + 1
    cur = conn.execute("INSERT INTO documents(project_id,doc_type,number,revision,parent_id,correction_reason,payload_json,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (d["project_id"], d["doc_type"], d["number"], rev, doc_id, reason, d["payload_json"], _now()))
    log(conn, "document", cur.lastrowid, "created", None, f"correction_of:{doc_id}", f"نسخة تصحيحية رقم {rev}: {reason}")
    conn.commit()
    return cur.lastrowid


# ---------- أرشفة الوثائق ونسخها وسجلها ----------
def is_archived(conn, doc_id):
    return conn.execute("SELECT 1 FROM doc_archive WHERE doc_id=?", (doc_id,)).fetchone() is not None


def archive_document(conn, doc_id, reason=""):
    """أرشفة وثيقة **صادرة** (تُخفى من القائمة الافتراضية دون أي تغيير في محتواها). المسودات تُحذف لا تُؤرشف.
    تُسجَّل في جدول جانبي، فلا يُمسّ مشغّل ثبات الوثائق الصادرة."""
    d = get_document(conn, doc_id)
    if d["status"] != "issued":
        raise ValueError("الأرشفة للوثائق الصادرة فقط. المسودة التي لا حاجة لها تُحذف.")
    if is_archived(conn, doc_id):
        raise ValueError("الوثيقة مؤرشفة بالفعل.")
    try:
        conn.execute("INSERT INTO doc_archive(doc_id, archived_at, reason) VALUES(?,?,?)", (doc_id, _now(), reason or ""))
        log(conn, "document", doc_id, "archived", 0, 1, reason or "أرشفة")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def restore_document(conn, doc_id):
    if not is_archived(conn, doc_id):
        raise ValueError("الوثيقة ليست في الأرشيف.")
    try:
        conn.execute("DELETE FROM doc_archive WHERE doc_id=?", (doc_id,))
        log(conn, "document", doc_id, "archived", 1, 0, "استرجاع من الأرشيف")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def duplicate_document(conn, doc_id):
    """مسودة جديدة من وثيقة سابقة (أي حالة) بنسخ بيانات الإدخال فقط؛ الأصل لا يتغير. تأخذ رقمًا جديدًا حسب سياسة الترقيم."""
    d = get_document(conn, doc_id)
    payload = json.loads(d["payload_json"] or "{}")
    payload.get("config", {}).pop("date", None)           # تاريخ الوثيقة الجديدة يُدخل من جديد، لا يُورَّث بصمت
    try:
        new_id = create_draft(conn, d["project_id"], d["doc_type"], payload)
        log(conn, "document", new_id, "created", None, f"copy_of:{doc_id}", "نسخة جديدة من وثيقة سابقة")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return new_id


def document_history(conn, doc_id):
    """سجل زمني مرتب: الإنشاء، التعديل، الإصدار، التصحيح (الصادر منه واللاحق به)، الأرشفة والاسترجاع."""
    d = get_document(conn, doc_id)
    ev = [(d["created_at"], "إنشاء", f"أُنشئت الوثيقة" + (f" (نسخة تصحيحية {d['revision']}: {d['correction_reason']})" if d["revision"] else ""))]
    if d["issued_at"]:
        ev.append((d["issued_at"], "إصدار", f"صدرت برقم {d['number']}"))
    for r in conn.execute("SELECT at, field, old_value, new_value, reason FROM audit_log WHERE entity='document' AND entity_id=? ORDER BY id", (doc_id,)):
        if r["field"] == "payload_json":
            ev.append((r["at"], "تعديل", r["reason"]))
        elif r["field"] == "archived":
            ev.append((r["at"], "أرشفة" if r["new_value"] == "1" else "استرجاع", r["reason"]))
    for c in conn.execute("SELECT id, revision, created_at, correction_reason FROM documents WHERE parent_id=? ORDER BY id", (doc_id,)):
        ev.append((c["created_at"], "تصحيح", f"أُنشئت منها نسخة تصحيحية رقم {c['revision']} (السبب: {c['correction_reason']})"))
    return sorted(ev, key=lambda e: e[0])


# ---------- النسخ الاحتياطي ----------
_REQUIRED_TABLES = {"schema_info", "projects", "items", "item_quantities", "measure_lines",
                    "formulas", "documents", "doc_counters", "app_settings", "audit_log"}


def inspect_backup(path):
    """يفحص ملف نسخة احتياطية دون تعديله: سلامة SQLite، المفاتيح الأجنبية، الجداول، الإصدار. يعيد ملخصًا أو يرمي ValueError."""
    try:
        chk = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        raise ValueError("ملف النسخة الاحتياطية ليس قاعدة بيانات صالحة؛ لم يُستبدل شيء") from exc
    try:
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        fk_errors = chk.execute("PRAGMA foreign_key_check").fetchall()
        tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ver = chk.execute("SELECT value FROM schema_info WHERE key='version'").fetchone() if "schema_info" in tables else None
        if not ok or fk_errors or ver is None or ver[0] not in SUPPORTED_VERSIONS or not _REQUIRED_TABLES.issubset(tables):
            raise ValueError(f"ملف النسخة الاحتياطية تالف أو غير متوافق (الإصدارات المدعومة: {', '.join(SUPPORTED_VERSIONS)})؛ لم يُستبدل شيء")
        n = lambda sql: chk.execute(sql).fetchone()[0]
        return {"version": ver[0], "projects": n("SELECT COUNT(*) FROM projects"), "documents": n("SELECT COUNT(*) FROM documents"),
                "issued": n("SELECT COUNT(*) FROM documents WHERE status='issued'"), "items": n("SELECT COUNT(*) FROM items")}
    except sqlite3.DatabaseError as exc:
        raise ValueError("ملف النسخة الاحتياطية ليس قاعدة بيانات صالحة؛ لم يُستبدل شيء") from exc
    finally:
        chk.close()


def backup(conn, dest_path):
    """نسخة احتياطية متسقة: تُكتب في ملف مؤقت ثم تُفحص (سلامة + أعداد السجلات مطابقة للأصل) ثم تُنقل ذريًا إلى الوجهة.
    لا يبقى ملف نصف مكتوب عند الفشل، ولا تُستبدل نسخة قديمة سليمة بنسخة غير سليمة. يعيد dest_path."""
    conn.commit()
    tmp = dest_path + ".partial"
    if os.path.exists(tmp):
        os.remove(tmp)
    dest = sqlite3.connect(tmp)
    try:
        with dest:
            conn.backup(dest)
    finally:
        dest.close()
    try:
        info = inspect_backup(tmp)
        live = {"projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "issued": conn.execute("SELECT COUNT(*) FROM documents WHERE status='issued'").fetchone()[0]}
        if any(info[k] != v for k, v in live.items()):
            raise ValueError("فشل التحقق من النسخة الاحتياطية: أعداد السجلات لا تطابق القاعدة الحالية؛ لم تُعتمد النسخة")
    except Exception:
        os.remove(tmp)
        raise
    os.replace(tmp, dest_path)
    return dest_path


def restore(src_path, db_path):
    """يفحص النسخة (inspect_backup) قبل أي تغيير، يحفظ القاعدة الحالية في .before_restore، ثم يستبدلها ذريًا
    (نسخ إلى ملف مجاور ثم os.replace) كي لا تبقى قاعدة نصف مكتوبة إن انقطع التنفيذ. يعيد ملخص ما استُعيد."""
    info = inspect_backup(src_path)
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".before_restore")
    tmp = db_path + ".restoring"
    shutil.copy2(src_path, tmp)
    os.replace(tmp, db_path)
    return info
