import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStyledItemDelegate,
                               QFrame, QLabel, QVBoxLayout)
from worksapp.money import D, fmt, bidi_safe, fmt_ui
from .theme import SEVERITY_LABEL, SEVERITY_COLOR, CELL_TEXT

CENTER = Qt.AlignmentFlag.AlignCenter
_NUMERIC = re.compile(r"^[\s\u00a0\u200e\d.,\-—/:%+]+$")


def qty_text(v, max_places=3):
    """كمية للعرض في الواجهة: فاصل آلاف، حتى 3 منازل بلا أصفار زائدة، ومحمية من انعكاس RTL."""
    if v is None or v == "":
        return "—"
    try:
        raw = fmt(v, max_places)
    except ValueError:
        return str(v)
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    return bidi_safe(raw)


def protect_numbers(text):
    """يحمي الخلايا العددية فقط (مبالغ/كميات/تواريخ) ويترك النص العربي كما هو."""
    if isinstance(text, str) and text and _NUMERIC.match(text) and any(ch.isdigit() for ch in text):
        return bidi_safe(text)
    return text


class NumberDelegate(QStyledItemDelegate):
    """يعرض الخلية رقمًا منسقًا (فاصل آلاف + حماية الاتجاه) ويُبقي القيمة الخام للتحرير والحفظ."""
    def __init__(self, parent=None, places=2, trim=False):
        super().__init__(parent)
        self.places, self.trim = places, trim

    def displayText(self, value, locale):
        text = "" if value is None else str(value)
        if not text.strip():
            return ""
        try:
            n = D(text)
        except ValueError:
            return text                       # نص غير رقمي أثناء الإدخال: لا نخفيه
        return qty_text(n, self.places) if self.trim else fmt_ui(n, self.places)


def make_table(headers, editable=False, stretch=None, min_col=70):
    """جدول بأعمدة تتسع لمحتواها، وعمود واحد (stretch) يأخذ الباقي، وحدٌّ أدنى للعرض كي لا ينضغط شيء."""
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    h = t.horizontalHeader()
    h.setMinimumSectionSize(min_col)
    h.setStretchLastSection(stretch is None)
    for c in range(len(headers)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == stretch else QHeaderView.ResizeMode.ResizeToContents)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    if not editable:
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return t


def cell(text, editable=False, color=None, align=None, protect=False):
    txt = "" if text is None else str(text)
    it = QTableWidgetItem(protect_numbers(txt) if protect else txt)
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color is not None:
        it.setBackground(color)
        it.setForeground(CELL_TEXT)       # خلفية فاتحة ثابتة ← نص داكن ثابت (يصلح للوضع الداكن أيضًا)
    if align is not None:
        it.setTextAlignment(align)
    return it


def field_label(text):
    lab = QLabel(text); lab.setObjectName("fieldLabel")
    return lab


class AlertsTable(QTableWidget):
    """تنبيهات: الشدة، المشكلة، البند/الحقل، لماذا، الإجراء (كما طلبت)."""
    HEADERS = ["الشدة", "المشكلة", "المتأثر", "لماذا يحتاج مراجعة", "الإجراء المقترح"]

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWordWrap(True)

    def set_alerts(self, alerts):
        order = {"blocking": 0, "warning": 1, "info": 2}
        alerts = sorted(alerts, key=lambda a: order.get(a.severity, 3))
        self.clearSpans()
        if not alerts:                                     # حالة فارغة واضحة بدل جدول بلا صفوف
            self.setRowCount(1)
            msg = cell("✓  لا توجد تنبيهات — لا شيء يحتاج مراجعة", align=CENTER)
            msg.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.setItem(0, 0, msg); self.setSpan(0, 0, 1, len(self.HEADERS))
            return
        self.setRowCount(len(alerts))
        for r, a in enumerate(alerts):
            vals = [SEVERITY_LABEL.get(a.severity, a.severity), a.problem,
                    a.affected + (f" — {a.detail}" if a.detail else ""), a.why, a.action]
            for c, v in enumerate(vals):
                self.setItem(r, c, cell(v, color=SEVERITY_COLOR.get(a.severity)))
        self.resizeRowsToContents()
