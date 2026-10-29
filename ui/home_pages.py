"""صفحتا «الرئيسية» (لوحة ملخص) و«النسخ الاحتياطي»."""
import os
from PySide6.QtCore import Qt, QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget)
from worksapp import services as SV
from worksapp.money import fmt_ui
from .doc_center import make_doc_table
from .fx import Btn, Card, DonutChart, GradCard, ROLE_PILL, ROLE_STATE
from .design import STATUS_KEYS, status_colors
from .widgets import cell, CENTER

KPIS = (("projects", "مشاريع نشطة", "folder", "#0B7A70", "#0E8A7E"),
        ("drafts", "مسودات", "edit", "#B45309", "#D97706"),
        ("issued", "وثائق صادرة", "check_circle", "#15803D", "#4D7C0F"),
        ("corrections", "نسخ تصحيحية", "restore", "#0369A1", "#0284C7"),
        ("total_net", "صافي الوضعيات الصادرة (دج)", "chart", "#92400E", "#B45309"))


def _scroll_page():
    sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.viewport().setAutoFillBackground(False); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sc


def _title(text):
    l = QLabel(text); l.setObjectName("cardTitle"); return l


class DashboardPage(QScrollArea):
    def __init__(self, win):
        super().__init__(); self.win = win
        self.setWidgetResizable(True); self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False); self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget(); self.setWidget(inner)
        inner.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(inner); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        row = QHBoxLayout(); row.setSpacing(0); self.cards = {}
        for key, cap, icon, c1, c2 in KPIS:
            g = GradCard(cap, icon, c1, c2, numeric=True); self.cards[key] = g; row.addWidget(g)
        root.addLayout(row)

        mid = QHBoxLayout(); mid.setSpacing(0)
        c1 = Card(); head = QHBoxLayout(); head.addWidget(_title("تتطلب إجراءً — انقر مرتين للانتقال إليها")); head.addStretch()
        new = Btn("مشروع جديد", "primary", "plus"); new.clicked.connect(self.win.new_project); head.addWidget(new)
        c1.body.addLayout(head)
        self.todo = QListWidget(); self.todo.setMinimumHeight(190); self.todo.itemDoubleClicked.connect(self.go)
        c1.body.addWidget(self.todo, 1); mid.addWidget(c1, 3)
        c2 = Card(); c2.body.addWidget(_title("توزيع الوثائق حسب الحالة"))
        self.donut = DonutChart(); self.donut.center_label, self.donut.empty_label = "إجمالي الوثائق", "لا وثائق بعد"
        c2.body.addWidget(self.donut, 1); mid.addWidget(c2, 2)
        root.addLayout(mid)

        c3 = Card(); c3.body.addWidget(_title("آخر الوثائق"))
        self.recent = make_doc_table(["الوثيقة", "الرقم", "المشروع", "الحالة", "التاريخ"],
                                     {0: "title", 1: "muted", 2: "person", 3: "pill", 4: "muted"}, "لا وثائق بعد — افتح مشروعًا وأنشئ أول مسودة", 2)
        self.recent.setMinimumHeight(250); self.recent.setSelectionMode(self.recent.SelectionMode.NoSelection)
        c3.body.addWidget(self.recent); root.addWidget(c3)
        root.addStretch()

    def refresh(self):
        st = SV.dashboard_stats(self.win.conn)
        for k in ("projects", "drafts", "issued", "corrections"):
            self.cards[k].set_value(st[k])
        self.cards["total_net"].set_text(fmt_ui(st["total_net"]))
        items = []
        for k in SV.DISPLAY_STATUSES:
            items.append((SV.DISPLAY_LABELS[k], st["by_display"][k], status_colors(STATUS_KEYS[k])[2].name()))
        self.donut.set_data(items)
        self.todo.clear()
        if not st["attention"]:
            self.todo.addItem("لا شيء يحتاج إجراءً الآن ✓")
        for a in st["attention"]:
            it = QListWidgetItem(a["text"]); it.setData(Qt.ItemDataRole.UserRole, a["project_id"]); self.todo.addItem(it)
        docs = SV.search_documents(self.win.conn, limit=8)
        self.recent.setUpdatesEnabled(False); self.recent.setRowCount(len(docs))
        for r, d in enumerate(docs):
            num = f"{d['number']:02d}" if d["number"] is not None else "—"
            for c, v in enumerate((d["label"], num, d["project_name"], SV.DISPLAY_LABELS[d["display"]], (d["issued_at"] or d["created_at"])[:10])):
                it = cell(v, align=None if c in (0, 2) else CENTER, protect=c in (1, 4))
                it.setData(ROLE_STATE, "scheduled"); it.setData(ROLE_PILL, STATUS_KEYS[d["display"]]); self.recent.setItem(r, c, it)
        self.recent.setUpdatesEnabled(True); self.recent.refresh_empty()

    def replay(self):
        for i, g in enumerate(self.cards.values()):
            QTimer.singleShot(70 * i, g.replay)            # ظهور متتابع بدل ظهور الجميع دفعة واحدة
        QTimer.singleShot(280, self.donut.replay)

    def go(self, item):
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self.win.open_project(pid, tab=3)


class BackupPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        card = Card(); root.addWidget(card); root.addStretch()
        t = QLabel("النسخ الاحتياطي والاستعادة"); t.setObjectName("title"); card.body.addWidget(t)
        info = QLabel("النسخة الاحتياطية تُفحص تلقائيًا بعد إنشائها (سلامة الملف وتطابق أعداد المشاريع والوثائق) ولا تُعتمد إن فشل الفحص.\n"
                      "الاستعادة تفحص الملف أولًا، وتحفظ بياناتك الحالية بجانب القاعدة باللاحقة .before_restore قبل الاستبدال.")
        info.setObjectName("hint"); info.setWordWrap(True); card.body.addWidget(info)
        self.status = QLabel(""); self.status.setObjectName("summary"); self.status.setWordWrap(True); card.body.addWidget(self.status)
        row = QHBoxLayout(); row.setSpacing(0)
        for text, variant, icon, fn in (("إنشاء نسخة احتياطية الآن", "primary", "shield", win.do_backup),
                                        ("استعادة من نسخة…", "soft", "restore", win.do_restore),
                                        ("فتح مجلد قاعدة البيانات", "soft", "folder", self.open_folder)):
            b = Btn(text, variant, icon); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); card.body.addLayout(row)

    def refresh(self):
        cfg = QSettings("WorksApp", "WorksApp")
        last = cfg.value("last_backup", "")
        counts = self.win.conn.execute("SELECT (SELECT COUNT(*) FROM projects), (SELECT COUNT(*) FROM documents)").fetchone()
        self.status.setText(f"قاعدة البيانات: {self.win.db_path()}\nالمحتوى الحالي: {counts[0]} مشروع، {counts[1]} وثيقة.\n"
                            + (f"آخر نسخة احتياطية من هذا البرنامج: {last}" if last else "لم تُنشأ نسخة احتياطية من هذا البرنامج بعد — يُنصح بإنشاء واحدة الآن."))

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.win.db_path())))
