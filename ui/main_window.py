from datetime import datetime
from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QSettings, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QGraphicsOpacityEffect, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)
from worksapp import storage as S
from worksapp.money import D, fmt_ui, ltr_marks
from . import design
from .fx import Backdrop, Btn, Card, FadeStack, FadeTabs, FocusGlow, HeaderBanner, LogoBadge, PillNav, SearchGrow, Toast
from .widgets import CENTER
from .dialogs import EditorDialog, PreviewDialog, QuantityConflictsDialog, PasteItemsDialog, ask   # noqa: F401 (إعادة تصدير)
from .company_dialog import CompanyDialog
from .project_tab import ProjectTab
from .finance_tab import FinanceTab
from .items_tab import ItemsTab
from .docs_tab import DocsTab
from .doc_center import DocumentCenter
from .home_pages import DashboardPage, BackupPage


def _scroll(widget):
    sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame); sc.setWidget(widget)
    return sc


WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]      # ترتيب datetime.weekday()
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def greeting_text():
    now = datetime.now()
    hello = "صباح الخير" if now.hour < 12 else ("مساء الخير" if now.hour < 18 else "مساء النور")
    return f"{hello}  •  {WEEKDAYS[now.weekday()]}، {now.day} {MONTHS[now.month - 1]} {now.year}"


class MainWindow(QMainWindow):
    NAV = (("الرئيسية", "home"), ("المشاريع", "folder"), ("الوثائق", "doc"), ("الأرشيف", "archive"), ("النسخ الاحتياطي", "shield"))

    def __init__(self, conn):
        super().__init__(); self.conn, self.pid = conn, None
        self.setWindowTitle("إدارة وثائق الأشغال"); self.resize(1400, 850); self.setMinimumSize(1100, 700)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        central = Backdrop(); self.setCentralWidget(central)
        outer = QVBoxLayout(central); outer.setContentsMargins(14, 6, 14, 4); outer.setSpacing(0)

        # ---- الترويسة المتدرجة
        self.header = HeaderBanner(); hl = self.header.lay
        hl.addWidget(LogoBadge())
        col = QVBoxLayout(); col.setSpacing(2); col.addStretch()
        t = QLabel("إدارة وثائق الأشغال"); t.setObjectName("heroTitle")
        self.project_title = QLabel(greeting_text()); self.project_title.setObjectName("heroSub")
        col.addWidget(t); col.addWidget(self.project_title); col.addStretch(); hl.addLayout(col); hl.addStretch()
        self.hsearch = QLineEdit(); self.hsearch.setObjectName("heroSearch"); self.hsearch.setPlaceholderText("بحث سريع في كل الوثائق…  (Enter)")
        self.hsearch.addAction(QIcon(design.icon_pixmap("search", "#FFFFFF", 18)), QLineEdit.ActionPosition.LeadingPosition)
        self.hsearch.setMinimumWidth(240); self.hsearch.setMaximumWidth(270); SearchGrow(self.hsearch, 270, 400)
        self.hsearch.returnPressed.connect(self.quick_search); hl.addWidget(self.hsearch)
        self.company_btn = Btn("الشركة المتعاقدة", "glass", "users"); self.company_btn.clicked.connect(self.edit_company); hl.addWidget(self.company_btn)
        self.theme_btn = Btn("", "glass", "sun" if design.mode() == "dark" else "moon"); self.theme_btn.setToolTip("تبديل المظهر: فاتح / داكن")
        self.theme_btn.clicked.connect(self.toggle_theme); hl.addWidget(self.theme_btn)
        outer.addWidget(self.header)

        # ---- التنقل والصفحات
        navrow = QHBoxLayout(); navrow.setContentsMargins(0, 2, 0, 0)
        self.nav = PillNav([n for n, _ in self.NAV], [i for _, i in self.NAV]); navrow.addWidget(self.nav); navrow.addStretch(); outer.addLayout(navrow)
        self.pages = FadeStack(); outer.addWidget(self.pages, 1)
        self.dashboard = DashboardPage(self)
        self.center_all = DocumentCenter(self, scope="all", on_change=lambda: self.docs_changed(source=self.center_all))
        self.center_archive = DocumentCenter(self, scope="archive", on_change=lambda: self.docs_changed(source=self.center_archive))
        self.backup_page = BackupPage(self)
        split = QSplitter()
        self.pages.addWidget(self.dashboard); self.pages.addWidget(split)
        for w in (self.center_all, self.center_archive):
            holder = Card(); holder.body.addWidget(w); self.pages.addWidget(holder)
        self.pages.addWidget(self.backup_page)
        self.nav.currentChanged.connect(self._go)
        self.toast_widget = Toast(central)

        side = QFrame(); side.setObjectName("sidebar"); ll = QVBoxLayout(side); ll.setContentsMargins(14, 14, 14, 14); ll.setSpacing(8)
        h = QLabel("المشاريع"); h.setObjectName("title"); ll.addWidget(h)
        self.search = QLineEdit(); self.search.setPlaceholderText("بحث بالاسم أو رقم العقد…"); FocusGlow(self.search)
        self.search.textChanged.connect(self.refresh_projects); ll.addWidget(self.search)
        self.plist = QListWidget(); self.plist.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); self.plist.currentItemChanged.connect(self.select); ll.addWidget(self.plist, 1)
        self.show_archived = QCheckBox("إظهار المشاريع المؤرشفة"); self.show_archived.toggled.connect(self.refresh_projects)
        ll.addWidget(self.show_archived)
        new = Btn("مشروع جديد", "primary", "plus"); new.clicked.connect(self.new_project); ll.addWidget(new)
        arch = Btn("أرشفة / إلغاء أرشفة", "soft", "archive"); arch.clicked.connect(self.toggle_archive); ll.addWidget(arch)
        dele = Btn("حذف المشروع", "danger", "trash"); dele.clicked.connect(self.delete_project); ll.addWidget(dele)

        self.stack = QStackedWidget()
        empty = QLabel("اختر مشروعًا من القائمة، أو أنشئ مشروعًا جديدًا للبدء."); empty.setObjectName("empty"); empty.setAlignment(CENTER)
        self.stack.addWidget(empty)
        work = QWidget(); wl = QVBoxLayout(work); wl.setContentsMargins(12, 12, 12, 12); wl.setSpacing(10)
        self.summary = QLabel(""); self.summary.setObjectName("summary"); self.summary.setWordWrap(True); wl.addWidget(self.summary)
        self.tabs = FadeTabs(); wl.addWidget(self.tabs, 1)
        self.ptab, self.ftab, self.itab, self.dtab = ProjectTab(self), FinanceTab(self), ItemsTab(self), DocsTab(self)
        self.tabs.addTab(_scroll(self.ptab), "بيانات المشروع")
        self.tabs.addTab(self.itab, "بنود العقد")
        self.tabs.addTab(_scroll(self.ftab), "الضرائب والاقتطاعات")
        self.tabs.addTab(self.dtab, "الوثائق")
        self.stack.addWidget(work)
        split.addWidget(side); split.addWidget(self.stack); split.setSizes([300, 1100])   # RTL: القائمة على اليمين

        # بلا شريط قوائم علوي: الشركة من الترويسة، والنسخ الاحتياطي من صفحته، والتنقل بالاختصارات Ctrl+1…5
        for i, (label, _) in enumerate(self.NAV):
            act = QAction(label, self); act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _=False, k=i: self.show_page(k)); self.addAction(act)
        self.settings = QSettings("WorksApp", "WorksApp")
        self.has_saved_geometry = self.settings.value("geometry") is not None
        if self.has_saved_geometry:
            self.restoreGeometry(self.settings.value("geometry"))
        saved_split = self.settings.value("split")
        if saved_split is not None:
            split.restoreState(saved_split)
        self.split = split
        self.statusBar().showMessage("جاهز")
        self.refresh_projects()
        self.show_page(0)
        QTimer.singleShot(400, self.first_run_check)

    # ---------- الشركة ----------
    def first_run_check(self):
        if S.default_company(self.conn) is None:
            CompanyDialog(self, self.conn, self.pid, first_run=True).exec()
            self.refresh_company_views()

    def edit_company(self):
        CompanyDialog(self, self.conn, self.pid).exec()
        self.refresh_company_views()

    def refresh_company_views(self):
        if self.pid is not None:
            self.ptab.refresh_company(); self.dtab.load(self.pid)

    # ---------- ملخص ----------
    def update_summary(self):
        if self.pid is None:
            return
        items = S.list_items(self.conn, self.pid)
        total = D(0)
        for it in items:
            try:
                if it["unit_price"] and it["contract_qty"]:
                    total += D(it["unit_price"]) * D(it["contract_qty"])
            except ValueError:
                pass
        p = self.conn.execute("SELECT name, contract_no FROM projects WHERE id=?", (self.pid,)).fetchone()
        self.summary.setText(f"عقد رقم: {ltr_marks(p['contract_no']) or '—'}     ·     عدد البنود: {len(items)}     ·     "
                             f"مبلغ العقد خارج الرسم (HT): {fmt_ui(total)} دج")
        self.project_title.setText(p["name"])

    # ---------- نسخ احتياطي ----------
    def db_path(self):
        return self.conn.execute("PRAGMA database_list").fetchone()[2]

    def do_backup(self):
        default = f"works_backup_{datetime.now():%Y-%m-%d}.db"
        path, _ = QFileDialog.getSaveFileName(self, "نسخة احتياطية", default, "قاعدة البيانات (*.db)")
        if not path:
            return
        try:
            S.backup(self.conn, path)
            info = S.inspect_backup(path)
        except Exception as e:
            QMessageBox.warning(self, "تعذر إنشاء النسخة", f"{e}\nلم تُعتمد أي نسخة ناقصة، وبياناتك الحالية لم تتأثر."); return
        QSettings("WorksApp", "WorksApp").setValue("last_backup", f"{path}  ({datetime.now():%Y-%m-%d %H:%M})")
        QMessageBox.information(self, "تمت النسخة وتم التحقق منها",
                                f"{path}\nتحتوي {info['projects']} مشروع و{info['documents']} وثيقة ({info['issued']} صادرة).")
        self.backup_page.refresh()

    def do_restore(self):
        src, _ = QFileDialog.getOpenFileName(self, "اختر نسخة احتياطية", "", "قاعدة البيانات (*.db)")
        if not src:
            return
        try:
            info = S.inspect_backup(src)                       # فحص قبل أي سؤال أو تغيير
        except ValueError as e:
            QMessageBox.warning(self, "نسخة غير صالحة", str(e)); return
        cur = self.conn.execute("SELECT (SELECT COUNT(*) FROM projects), (SELECT COUNT(*) FROM documents)").fetchone()
        if not ask(self, "استعادة نسخة احتياطية",
                   f"النسخة المختارة: {info['projects']} مشروع، {info['documents']} وثيقة (الإصدار {info['version']}).\n"
                   f"بياناتك الحالية: {cur[0]} مشروع، {cur[1]} وثيقة، وستُستبدل بها.\n"
                   "تُحفظ نسخة من الحالية بجانبها باللاحقة .before_restore. المتابعة؟"):
            return
        path = self.db_path()
        try:
            self.conn.close()
            S.restore(src, path)
        except Exception as e:
            self.conn = S.connect(path)
            QMessageBox.warning(self, "لم تتم الاستعادة", f"{e}\nلم يتغير شيء من بياناتك.")
            return
        self.conn = S.connect(path); self._reset_view()
        self.show_page(0)
        QMessageBox.information(self, "تمت الاستعادة", "استُعيدت البيانات. اختر مشروعًا من القائمة للمتابعة.")

    # ---------- التنقل وتحديث الصفحات ----------
    def show_page(self, i):
        if self.nav.currentIndex() != i:
            self.nav.setCurrentIndex(i)          # يُطلق currentChanged ← _go
        else:
            self._go(i)

    def _go(self, i):
        self.pages.set_index_animated(i)
        if i == 0:
            self.dashboard.refresh(); self.dashboard.replay()
        elif i == 2:
            self.center_all.load()
        elif i == 3:
            self.center_archive.load()
        elif i == 4:
            self.backup_page.refresh()

    def quick_search(self):
        self.center_all.search.setText(self.hsearch.text())
        self.show_page(2); self.center_all.load()

    def toast(self, text, kind="success"):
        self.toast_widget.show_message(text, kind)

    def toggle_theme(self):
        new = "light" if design.mode() == "dark" else "dark"
        ov = None
        try:                                           # لقطة للمظهر الحالي تتلاشى فوق المظهر الجديد (انتقال ناعم بدل القفزة)
            ov = QLabel(self); ov.setPixmap(self.grab()); ov.setGeometry(self.rect())
            ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True); ov.show(); ov.raise_()
        except Exception:
            ov = None
        design.apply(QApplication.instance(), new); self.settings.setValue("theme", new)
        self.theme_btn.icon_kind = "sun" if new == "dark" else "moon"; self.theme_btn.update()
        if ov is not None:
            fx = QGraphicsOpacityEffect(ov); ov.setGraphicsEffect(fx)
            a = QPropertyAnimation(fx, b"opacity", self); a.setDuration(340); a.setStartValue(1.0); a.setEndValue(0.0)
            a.setEasingCurve(QEasingCurve.Type.InOutQuad); a.finished.connect(ov.deleteLater); a.start(); self._theme_anim = a

    def open_project(self, pid, tab=None):
        self.search.setText("")
        self.refresh_projects(keep=pid)
        self.select(self.plist.currentItem())
        if tab is not None:
            self.tabs.setCurrentIndex(tab)

    def docs_changed(self, source=None):
        """بعد أي عملية على وثيقة: حدّث كل العروض المتأثرة عدا مصدر الحدث (فقد حدّث نفسه)."""
        if self.pid is not None and source is not self.dtab:
            self.dtab.load(self.pid)
        for c in (self.center_all, self.center_archive):
            if c is not source:
                c.load()
        self.dashboard.refresh()

    def show_initial(self):
        self.setWindowOpacity(0.0)
        self.show() if self.has_saved_geometry else self.showMaximized()
        a = QPropertyAnimation(self, b"windowOpacity", self); a.setDuration(360); a.setStartValue(0.0); a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic); a.start(); self._intro_anim = a      # ظهور تدريجي عند فتح البرنامج

    def closeEvent(self, ev):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("split", self.split.saveState())
        super().closeEvent(ev)

    # ---------- المشاريع ----------
    def refresh_projects(self, *_, keep=None):
        keep = keep or self.pid
        q = self.search.text().strip()
        show = self.show_archived.isChecked()
        self.plist.blockSignals(True); self.plist.clear()
        for r in self.conn.execute("SELECT id,name,contract_no,archived FROM projects WHERE (name LIKE ? OR contract_no LIKE ?)"
                                   + ("" if show else " AND archived=0") + " ORDER BY id DESC", (f"%{q}%", f"%{q}%")):
            it = QListWidgetItem(("[مؤرشف] " if r["archived"] else "") + f"{r['name']}\nعقد: {ltr_marks(r['contract_no']) or 'بلا رقم'}")
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.plist.addItem(it)
            if r["id"] == keep:
                self.plist.setCurrentItem(it)
        self.plist.blockSignals(False)

    def select(self, item, _prev=None):
        if item is None:
            return
        self.pid = item.data(Qt.ItemDataRole.UserRole)
        self.stack.setCurrentIndex(1)
        if self.pages.currentIndex() != 1:
            self.show_page(1)
        self.ptab.load(self.pid); self.ftab.load(self.pid); self.itab.load(self.pid); self.dtab.load(self.pid)
        self.update_summary()
        self.statusBar().showMessage("تم فتح المشروع")

    def refresh_docs(self):
        if self.pid:
            self.dtab.load(self.pid)

    def _reset_view(self):
        self.pid = None; self.stack.setCurrentIndex(0); self.project_title.setText(greeting_text()); self.refresh_projects()

    def toggle_archive(self):
        if self.pid is None:
            QMessageBox.information(self, "اختر مشروعًا", "اختر مشروعًا من القائمة أولًا."); return
        cur = self.conn.execute("SELECT archived FROM projects WHERE id=?", (self.pid,)).fetchone()[0]
        S.archive_project(self.conn, self.pid, not cur)
        if cur:
            self.refresh_projects()
        else:
            self._reset_view()
            self.statusBar().showMessage("أُرشف المشروع (يظهر بتفعيل «إظهار المشاريع المؤرشفة»). وثائقه الصادرة محفوظة.")

    def delete_project(self):
        if self.pid is None:
            QMessageBox.information(self, "اختر مشروعًا", "اختر مشروعًا من القائمة أولًا."); return
        n = S.issued_count(self.conn, self.pid)
        name = self.conn.execute("SELECT name FROM projects WHERE id=?", (self.pid,)).fetchone()[0]
        if n:
            if ask(self, "لا يمكن الحذف", f"للمشروع «{name}» {n} وثيقة صادرة، والوثائق الصادرة ثابتة ولا تُحذف.\nهل تريد أرشفته (إخفاءه من القائمة) بدلًا من ذلك؟"):
                self.toggle_archive()
            return
        n_items = len(S.list_items(self.conn, self.pid))
        if not ask(self, "حذف مشروع", f"حذف المشروع «{name}» نهائيًا مع {n_items} بند وكل مسوداته؟\nلا يمكن التراجع (إلا باستعادة نسخة احتياطية).\n\nننصح بإنشاء نسخة احتياطية من قائمة «ملف» أولًا."):
            return
        try:
            S.delete_project(self.conn, self.pid)
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحذف", str(e)); return
        self._reset_view(); self.statusBar().showMessage("حُذف المشروع")

    def new_project(self):
        name, ok = QInputDialog.getText(self, "مشروع جديد", "اسم المشروع / العملية:")
        if ok and name.strip():
            pid = S.create_project(self.conn, name.strip())
            self.search.setText("")
            self.refresh_projects(keep=pid); self.select(self.plist.currentItem())
            self.tabs.setCurrentIndex(0)
