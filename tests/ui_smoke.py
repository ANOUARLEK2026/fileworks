# اختبار دخان بوحدات PySide6 وهمية: يتأكد أن بناء النوافذ ومنطق التحميل/الحفظ لا يرمي أخطاء أسماء.
import sys, types, os, tempfile
class W:
    _txt = ""
    def __init__(self, *a, **k): self._items = {}; self._rows = 0; self._cur = 0
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return W()
    def __call__(self, *a, **k): return W()
    def text(self): return self._txt
    def isChecked(self): return True
    def currentData(self): return None
    def count(self): return 0
    def item(self, r, c): return self._items.get((r, c)) or Cell("")
    def setItem(self, r, c, it): self._items[(r, c)] = it
    def rowCount(self): return self._rows
    def setRowCount(self, n): self._rows = n
    def insertRow(self, r): self._rows += 1
    def currentRow(self): return -1
    def findData(self, v): return 0
    def exec(self): return 0
    def cellWidget(self, r, c): return W()
    def __add__(self, o): return W()
    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __add__
    def __lt__(self, o): return False
    __gt__ = __le__ = __ge__ = __lt__
    def __int__(self): return 0
    def __float__(self): return 0.0
class Cell(W):
    def __init__(self, t="", *a): super().__init__(); self._t = t
    def text(self): return self._t
    def flags(self): return 0
    def data(self, role): return "x"
class Flag(int):
    def __invert__(self): return Flag(0)
    def __and__(self, o): return Flag(0)
    def __or__(self, o): return Flag(0)
class Enum:
    def __call__(self,*a,**k): return self
    def __getattr__(self, n): return Enum() if not n.startswith("__") else (_ for _ in ()).throw(AttributeError)
    def __or__(self, o): return self
    def __invert__(self): return self
    def __rand__(self, o): return self
    def __and__(self, o): return self
class Meta(type):
    def __getattr__(cls, n):
        if n.startswith("__"): raise AttributeError(n)
        return Enum()
class Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        if n == "QTableWidgetItem": return Cell
        if n == "Qt": return Enum()
        if n in ("QColor",): return lambda *a: W()
        return Meta(n, (W,), {})
for name in ("PySide6", "PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtGui"):
    sys.modules[name] = Mod(name)
sys.path.insert(0, os.getcwd())
from worksapp import storage as S
import ui.widgets, ui.dialogs, ui.main_window as MW
from ui import design
design.icon_pixmap = design.draw_icon = lambda *a, **k: None      # الرسم يحتاج Qt حقيقيًا؛ نتحقق منه بالفاحص الساكن فقط
conn = S.connect(os.path.join(tempfile.mkdtemp(), "x.db"))
pid = S.create_project(conn, "اختبار", contract_no="1")
for c, p, q in (("01", 100, 5), ("02", 50, 2)):
    S.add_item(conn, pid, c, "بند", "م²", p, q)
win = MW.MainWindow(conn)
win.pid = pid
win.ptab.load(pid); win.ftab.load(pid); win.itab.load(pid); win.dtab.load(pid)
# Construct the new conflict dialog in the no-conflict state to exercise its UI wiring.
from ui.dialogs import QuantityConflictsDialog
QuantityConflictsDialog(win, conn, pid)
win.ptab.save(); win.ftab.save()
from ui.company_dialog import CompanyDialog
CompanyDialog(win, conn, pid)
win.itab.move("up"); win.itab.duplicate(); win.itab.sort_codes(); win.itab.apply_filter(); win.refresh_company_views()
win.toggle_archive(); win.refresh_projects()
for dt in S.DOC_TYPES:
    from worksapp import services as SV
    did = SV.create_draft(conn, pid, dt)
    ed = MW.EditorDialog(win, conn, did)
    if dt != "bayan":
        ed.collect()
    MW.PreviewDialog(win, conn, did)
win.itab.add_blank(); win.itab.load(pid); win.itab.delete(); win.update_summary(); win.dtab.load(pid)
# --- المكوّنات الجديدة: لوحة المتابعة ومراكز الوثائق والسجل والنسخ الاحتياطي والتحقق الفوري ---
from worksapp import services as SV2
from ui.doc_center import HistoryDialog
did = SV2.create_draft(conn, pid, "bayan")
win.dashboard.refresh(); win.center_all.load(); win.center_archive.load(); win.backup_page.refresh()
win.show_page(2); win.show_page(0); win.docs_changed(); win.dtab.center.load(); win.dtab.after_change()
for fn in ("open_selected", "preview", "history", "duplicate", "correct", "toggle_archive", "delete_draft", "reset_filters"):
    getattr(win.dtab.center, fn)()
HistoryDialog(win, conn, did)
pv = MW.PreviewDialog(win, conn, did); pv._tab_changed(1); pv._cleanup()
assert MW.EditorDialog._problem("abc") and MW.EditorDialog._problem("-1") and MW.EditorDialog._problem("1.5") is None and MW.EditorDialog._problem("") is None
# --- صف أزرار واحد، تفعيل حسب الحالة، وتبديل الأيقونات عند الضيق ---
cen = win.center_all
assert len(cen.buttons) == 9 and set(cen.by_name) == {"open", "preview", "word", "pdf", "history", "copy", "correct", "archive", "delete"}
cen._update_buttons()
for b in cen.buttons:
    b.set_icon_only(True); b.set_icon_only(False); b.full_width()
# --- ورقة الأنماط: لا رموز ناقصة، أقواس متوازنة، وخصائص QSS معروفة (للمظهرين) ---
import re
KNOWN = set("""alternate-background-color background background-color border border-bottom border-color border-left border-radius border-right
border-top color combobox-popup font-size font-weight gridline-color height image margin margin-bottom margin-left margin-right margin-top
max-height min-height min-width outline padding padding-bottom padding-left padding-right padding-top placeholder-text-color right
selection-background-color selection-color spacing subcontrol-origin subcontrol-position top width""".split())
design._ICONS.update({"ico_check": "c.png", "ico_down": "d.png", "ico_up": "u.png", "ico_cal_prev": "p.png", "ico_cal_next": "n.png"})   # تُولَّد في apply()
for mode in ("light", "dark"):
    design.P.clear(); design.P.update(design.DARK if mode == "dark" else design.LIGHT)
    qss = re.sub(r"/\*.*?\*/", "", design.build_qss(), flags=re.S)
    assert "#FF00FF" not in qss and "@" not in qss, f"رمز لون ناقص في QSS ({mode})"
    assert qss.count("{") == qss.count("}"), "أقواس QSS غير متوازنة"
    for body in re.findall(r"\{([^{}]*)\}", qss):
        for decl in [d for d in body.split(";") if d.strip()]:
            name = decl.split(":", 1)[0].strip()
            assert ":" in decl and name in KNOWN, f"خاصية QSS غير معروفة أو تصريح معطوب: {decl.strip()[:60]}"
design.P.clear(); design.P.update(design.LIGHT)
print("UI smoke OK")
