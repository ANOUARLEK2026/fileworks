from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget
from worksapp import storage as S, services as SV
from .dialogs import EditorDialog, QuantityConflictsDialog
from .widgets import AlertsTable
from .doc_center import DocumentCenter
from .fx import Btn, HoverCard


class DocsTab(QWidget):
    """وثائق المشروع المفتوح: بطاقات إنشاء مسودة لكل نوع + مركز الوثائق (بحث/تصفية/إدارة) + تنبيهات المشروع."""

    def __init__(self, win):
        super().__init__(); self.win = win
        # المحتوى أطول من ارتفاع التبويب في الشاشات الصغيرة: نضعه في منطقة تمرير بدل ضغط العناصر فوق بعضها
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget(); scroll.setWidget(inner)
        inner.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(inner); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(10)
        cards = QHBoxLayout(); cards.setSpacing(0); self.state = {}
        look = {"bayan": ("file", "#0B7A70", "#0E8A7E"), "hawsala": ("chart", "#0369A1", "#0284C7"),
                "situation": ("doc", "#B45309", "#D97706"), "inventory": ("check_circle", "#15803D", "#4D7C0F")}
        for dt in S.DOC_TYPES:
            g = HoverCard(*look.get(dt, ("doc", "#0B7A70", "#0E8A7E"))); gl = g.body
            t = QLabel(SV.DOC_LABELS[dt]); t.setObjectName("cardTitle"); t.setWordWrap(True); gl.addWidget(t)
            self.state[dt] = QLabel("لا وثائق"); self.state[dt].setObjectName("badgeNone"); gl.addWidget(self.state[dt])
            b = Btn("مسودة جديدة", "primary", "plus"); b.clicked.connect(lambda _=False, t=dt: self.new_draft(t)); gl.addWidget(b)
            cards.addWidget(g)
        root.addLayout(cards)
        self.center = DocumentCenter(win, scope="project", on_change=self.after_change)
        self.center.setMinimumHeight(430)
        root.addWidget(self.center, 3)
        row = QHBoxLayout()
        b = Btn("حسم تعارض الكميات", "soft", "alert"); b.clicked.connect(self.resolve_conflicts); row.addWidget(b)
        row.addStretch(); root.addLayout(row)
        root.addWidget(QLabel("تنبيهات المشروع:")); self.alerts = AlertsTable(); self.alerts.setMinimumHeight(150); root.addWidget(self.alerts, 1)

    def load(self, pid):
        ov = SV.documents_overview(self.win.conn, pid)
        for dt, o in ov.items():
            self.state[dt].setText(o["state"])
            kind = "badgeNone" if not o["docs"] else ("badgeIssued" if o["docs"][0]["status"] == "issued" else "badgeDraft")
            self.state[dt].setObjectName(kind)
            self.state[dt].setStyleSheet("")          # يعيد تطبيق نمط الاسم الجديد
            self.state[dt].style().unpolish(self.state[dt]); self.state[dt].style().polish(self.state[dt])
        self.center.load()
        self.alerts.set_alerts(SV.project_alerts(self.win.conn, pid))

    def after_change(self):
        """بعد أي عملية في المركز: حدّث البطاقات والتنبيهات ولوحة الملخص وبقية صفحات الوثائق."""
        if self.win.pid is not None:
            ov = SV.documents_overview(self.win.conn, self.win.pid)
            for dt, o in ov.items():
                self.state[dt].setText(o["state"])
            self.alerts.set_alerts(SV.project_alerts(self.win.conn, self.win.pid))
        self.win.docs_changed(source=self)

    def new_draft(self, dt):
        if self.win.pid is None:
            return
        did = SV.create_draft(self.win.conn, self.win.pid, dt)
        self.load(self.win.pid); EditorDialog(self, self.win.conn, did).exec(); self.after_change(); self.center.load()

    def resolve_conflicts(self):
        if self.win.pid is None:
            return
        if not SV.quantity_conflicts(self.win.conn, self.win.pid):
            QMessageBox.information(self, "لا توجد تعارضات", "لا توجد حاليًا كميات متعارضة تحتاج إلى حسم."); return
        QuantityConflictsDialog(self, self.win.conn, self.win.pid).exec()
        self.load(self.win.pid); self.win.update_summary(); self.win.docs_changed(source=self)
