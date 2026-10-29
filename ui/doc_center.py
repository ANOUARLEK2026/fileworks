"""مركز الوثائق: بحث وتصفية وإدارة الوثائق (جديدة وقديمة) في نطاق مشروع واحد أو كل المشاريع أو الأرشيف.

التمييز بين العمليات واضح: تعديل المسودة (المحرر) ≠ الإصدار (نافذة المعاينة) ≠ التصحيح (نسخة جديدة مرتبطة) ≠ الأرشفة (إخفاء).
التصدير لا يغيّر حالة أي وثيقة."""
import os
import re
from PySide6.QtCore import Qt, QSettings, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QAbstractItemView, QHeaderView, QMenu, QMessageBox, QVBoxLayout, QWidget, QApplication)
from worksapp import storage as S, services as SV, export as EX
from worksapp.money import fmt_ui, ltr_marks
from .dialogs import EditorDialog, PreviewDialog, ask
from .widgets import cell, CENTER
from .fx import Btn, FancyDialog, FocusGlow, HoverTable, DocDelegate, ROLE_STATE, ROLE_PILL
from .design import STATUS_KEYS

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADERS = ["الوثيقة", "الرقم", "المشروع", "رقم العقد", "الحالة", "التاريخ", "المبلغ (دج)"]
KINDS = {0: "title", 1: "muted", 2: "person", 3: "muted", 4: "pill", 5: "muted", 6: "text"}


def make_doc_table(headers, kinds, empty_text, stretch):
    """جدول بتمرير متحرك وشارات حالة (HoverTable + DocDelegate)؛ عمود واحد (stretch) يأخذ المتبقي."""
    t = HoverTable(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setItemDelegate(DocDelegate(t, kinds))
    t.set_empty_text(empty_text)
    t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)       # عجلة تمرير ناعمة بالبكسل
    h = t.horizontalHeader()
    h.setStretchLastSection(False)
    for c in range(len(headers)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == stretch else QHeaderView.ResizeMode.ResizeToContents)
    return t


class HistoryDialog(FancyDialog):
    def __init__(self, parent, conn, doc_id):
        d = S.get_document(conn, doc_id)
        super().__init__("سجل الوثيقة", SV.DOC_LABELS[d["doc_type"]], "clock", parent)
        self.resize(780, 520)
        events = S.document_history(conn, doc_id)
        t = make_doc_table(["التاريخ والوقت", "العملية", "التفاصيل"], {0: "muted", 1: "title", 2: "text"}, "لا أحداث", 2)
        t.setRowCount(len(events))
        for r, (at, kind, detail) in enumerate(events):
            for c, v in enumerate((at.replace("T", "  "), kind, detail or "")):
                t.setItem(r, c, cell(v, align=None if c == 2 else CENTER, protect=(c == 0)))
        t.refresh_empty()
        self.cl.addWidget(t, 1)
        close = Btn("إغلاق", "soft"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addWidget(close); row.addStretch(); self.cl.addLayout(row)


class DocumentCenter(QWidget):
    """scope: 'project' (وثائق المشروع المفتوح) | 'all' (كل المشاريع) | 'archive' (الوثائق المؤرشفة فقط)."""

    def __init__(self, win, scope="all", on_change=None):
        super().__init__()
        self.win, self.scope, self.on_change = win, scope, on_change
        self.docs, self._busy = [], False
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(8)

        f1 = QHBoxLayout()
        self.search = QLineEdit(); self.search.setClearButtonEnabled(True); FocusGlow(self.search)
        self.search.setPlaceholderText("بحث: رقم الوثيقة، رقم العقد، اسم المشروع، السبب، المبلغ…   (Ctrl+F)")
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(250)
        self._timer.timeout.connect(self.load)
        self.search.textChanged.connect(lambda *_: self._timer.start())       # لا نعيد البناء مع كل حرف
        f1.addWidget(self.search, 1)
        self.type_box = QComboBox(); self.type_box.addItem("كل الأنواع", None)
        for dt in S.DOC_TYPES:
            self.type_box.addItem(SV.DOC_LABELS[dt], dt)
        self.status_box = QComboBox(); self.status_box.addItem("كل الحالات", None)
        for k in SV.DISPLAY_STATUSES:
            if k != "archived":
                self.status_box.addItem(SV.DISPLAY_LABELS[k], k)
        for w in (self.type_box, self.status_box):
            w.currentIndexChanged.connect(lambda *_: self.load()); f1.addWidget(w)
        root.addLayout(f1)

        f2 = QHBoxLayout()
        self.date_from, self.date_to = QLineEdit(), QLineEdit()
        for w, ph in ((self.date_from, "من تاريخ  " + ltr_marks("2026-01-01")), (self.date_to, "إلى تاريخ  " + ltr_marks("2026-12-31"))):
            w.setPlaceholderText(ph); w.setMaximumWidth(190); w.editingFinished.connect(self.load); f2.addWidget(w)
        self.with_archived = QCheckBox("تضمين المؤرشفة")
        self.with_archived.toggled.connect(lambda *_: self.load())
        if scope != "archive":
            f2.addWidget(self.with_archived)
        reset = Btn("مسح التصفية", "ghost", "restore"); reset.clicked.connect(self.reset_filters); f2.addWidget(reset)
        f2.addStretch()
        self.count = QLabel(""); self.count.setObjectName("hint"); f2.addWidget(self.count)
        root.addLayout(f2)
        self.filter_msg = QLabel(""); self.filter_msg.setObjectName("warnBox"); self.filter_msg.hide(); root.addWidget(self.filter_msg)

        self.table = make_doc_table(HEADERS, KINDS, "لا توجد وثائق مطابقة", 2)
        self.table.verticalHeader().setDefaultSectionSize(46); self.table.setMinimumHeight(220)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx)
        self.table.cellDoubleClicked.connect(lambda r, c: self.open_selected())
        root.addWidget(self.table, 1)

        # صف واحد: الإجراءات الشائعة يمينًا، والحذف منفصلًا في أقصى اليسار (بعيدًا عن النقر الخاطئ)
        self.buttons, self.by_name = [], {}
        h = QHBoxLayout(); h.setSpacing(0)
        specs = (("open", "فتح", "فتح الوثيقة (Enter)", self.open_selected, "primary", "file"),
                 ("preview", "معاينة", "معاينة قبل الإصدار أو التصدير", self.preview, "soft", "eye"),
                 ("word", "Word", "تصدير إلى Word (Ctrl+E)", self.export_word, "soft", "doc"),
                 ("pdf", "PDF", "تصدير إلى PDF (Ctrl+Shift+E)", self.export_pdf, "soft", "download"),
                 ("history", "السجل", "سجل الوثيقة الزمني", self.history, "soft", "clock"),
                 ("copy", "نسخة جديدة", "إنشاء مسودة جديدة من هذه الوثيقة (Ctrl+D)", self.duplicate, "soft", "copy"),
                 ("correct", "تصحيح", "نسخة تصحيحية من وثيقة صادرة", self.correct, "soft", "edit"),
                 ("archive", "أرشفة", "أرشفة الوثيقة الصادرة أو استرجاعها من الأرشيف", self.toggle_archive, "soft", "archive"))
        for key, text, tip, fn, variant, icon in specs:
            b = Btn(text, variant, icon, compact=True); b.setToolTip(tip); b.clicked.connect(fn)
            self.buttons.append(b); self.by_name[key] = b; h.addWidget(b)
        h.addStretch()
        b = Btn("حذف المسودة", "danger", "trash", compact=True); b.setToolTip("حذف المسودة نهائيًا (Delete)"); b.clicked.connect(self.delete_draft)
        self.buttons.append(b); self.by_name["delete"] = b; h.addWidget(b)
        root.addLayout(h)
        self._full_needed = sum(x.full_width() for x in self.buttons) + 24
        self.table.itemSelectionChanged.connect(self._update_buttons)
        hint = QLabel("انقر مرتين لفتح الوثيقة: المسودة تُحرَّر، والصادرة تُعاين. التصدير لا يغيّر حالة الوثيقة ولا يعني اعتمادها.")
        hint.setObjectName("hint"); hint.setWordWrap(True); root.addWidget(hint)

        for seq, fn in (("F5", self.load), ("Return", self.open_selected), ("Ctrl+E", self.export_word),
                        ("Ctrl+Shift+E", self.export_pdf), ("Ctrl+D", self.duplicate), ("Delete", self.delete_draft)):
            sc = QShortcut(QKeySequence(seq), self.table); sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        sc = QShortcut(QKeySequence("Ctrl+F"), self); sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.focus_search)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        narrow = self.width() < self._full_needed
        for b in self.buttons:
            b.set_icon_only(narrow)             # أيقونات فقط حين لا يتسع النص، والنص الكامل في التلميح

    def _update_buttons(self):
        """يفعّل الأزرار المناسبة للوثيقة المحددة فقط: التصحيح والأرشفة للصادرة، والحذف للمسودة."""
        d = self._sel_doc(quiet=True)
        for k, b in self.by_name.items():
            ok = d is not None
            if ok and k in ("correct", "archive"):
                ok = d["status"] == "issued"
            elif ok and k == "delete":
                ok = d["status"] == "draft"
            b.setEnabled(ok and not self._busy)
        if d is not None and d["status"] == "issued":
            self.by_name["archive"].setToolTip("استرجاع الوثيقة من الأرشيف" if d["archived"] else "أرشفة الوثيقة (تُخفى دون حذف)")

    # ---------- تحميل وتصفية ----------
    def focus_search(self):
        self.search.setFocus(); self.search.selectAll()

    def reset_filters(self):
        for w in (self.search, self.date_from, self.date_to):
            w.clear()
        self.type_box.setCurrentIndex(0); self.status_box.setCurrentIndex(0); self.with_archived.setChecked(False)
        self.load()

    def _date(self, edit, label):
        v = edit.text().strip()
        if not v:
            return None, None
        if not _DATE.match(v):
            return None, f"{label}: استعمل الصيغة {ltr_marks('2026-03-31')} (سنة-شهر-يوم). لم تُطبَّق هذه التصفية."
        return v, None

    def load(self, *_):
        keep = self._sel_id()
        d1, e1 = self._date(self.date_from, "من تاريخ")
        d2, e2 = self._date(self.date_to, "إلى تاريخ")
        msgs = [m for m in (e1, e2) if m]
        self.filter_msg.setText("\n".join(msgs)); self.filter_msg.setVisible(bool(msgs))
        pid = self.win.pid if self.scope == "project" else None
        if self.scope == "project" and pid is None:
            self.docs = []
        else:
            self.docs = SV.search_documents(
                self.win.conn, text=self.search.text(), doc_type=self.type_box.currentData(),
                status=None if self.scope == "archive" else self.status_box.currentData(), project_id=pid,
                date_from=d1, date_to=d2, include_archived=self.with_archived.isChecked() and self.scope != "archive",
                only_archived=self.scope == "archive")
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self.docs))
        for r, d in enumerate(self.docs):
            number = f"{d['number']:02d}" if d["number"] is not None else "—"
            if d["revision"]:
                number += f" (تصحيح {d['revision']})"
            vals = [d["label"], number, d["project_name"], d["contract_no"] or "—", SV.DISPLAY_LABELS[d["display"]],
                    (d["issued_at"] or d["created_at"])[:10], fmt_ui(d["amount"]) if d["amount"] is not None else "—"]
            state = "cancel" if d["archived"] else "scheduled"
            for c, v in enumerate(vals):
                it = cell(v, align=None if c in (0, 2) else CENTER, protect=c in (1, 3, 5, 6))
                it.setData(ROLE_STATE, state); it.setData(ROLE_PILL, STATUS_KEYS[d["display"]])
                self.table.setItem(r, c, it)
            if d["id"] == keep:
                self.table.selectRow(r)
        self.table.setUpdatesEnabled(True); self.table.refresh_empty()
        self._update_buttons()
        n = len(self.docs)
        self.count.setText("لا توجد وثائق مطابقة" if not n else f"{n} وثيقة")
        if not n and self.scope == "project" and pid is not None and not self.search.text().strip():
            self.count.setText("لا وثائق لهذا المشروع بعد — أنشئ مسودة من الأزرار أعلاه")

    def _sel_id(self):
        d = self._sel_doc(quiet=True)
        return d["id"] if d else None

    def _sel_doc(self, quiet=False):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.docs):
            if not quiet:
                QMessageBox.information(self, "اختر وثيقة", "حدد وثيقة من الجدول أولًا.")
            return None
        return self.docs[r]

    def _changed(self):
        self.load()
        if self.on_change:
            self.on_change()

    # ---------- حماية من النقر المتكرر ----------
    def _begin(self):
        if self._busy:
            return False
        self._busy = True
        for b in self.buttons:
            b.setEnabled(False)
        return True

    def _end(self):
        def release():
            self._busy = False
            self._update_buttons()
        QTimer.singleShot(400, release)       # يُبقي الأزرار معطّلة لحظة بعد الانتهاء فتسقط النقرات المتراكمة

    # ---------- قائمة سياقية ----------
    def _ctx(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        self.table.selectRow(r); self.table.setCurrentCell(r, 0)
        m = QMenu(self)
        d = self.docs[r]
        items = [("فتح", self.open_selected), ("معاينة", self.preview), ("تصدير Word", self.export_word), ("تصدير PDF", self.export_pdf),
                 ("سجل الوثيقة", self.history), ("نسخة جديدة منها", self.duplicate)]
        if d["status"] == "issued":
            items.append(("نسخة تصحيحية…", self.correct))
            items.append(("استرجاع من الأرشيف" if d["archived"] else "أرشفة…", self.toggle_archive))
        else:
            items.append(("حذف المسودة…", self.delete_draft))
        for text, fn in items:
            m.addAction(text).triggered.connect(lambda _=False, f=fn: f())
        m.exec(QCursor.pos())

    # ---------- العمليات ----------
    def open_selected(self):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            if d["status"] == "draft":
                EditorDialog(self, self.win.conn, d["id"]).exec()
            else:
                PreviewDialog(self, self.win.conn, d["id"]).exec()
        finally:
            self._end()
        self._changed()

    def preview(self):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            PreviewDialog(self, self.win.conn, d["id"]).exec()
        finally:
            self._end()
        self._changed()

    def history(self):
        d = self._sel_doc()
        if d is not None:
            HistoryDialog(self, self.win.conn, d["id"]).exec()

    def _export(self, ext, title, filt, fn):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            cfg = QSettings("WorksApp", "WorksApp")
            name = SV.suggested_export_path(self.win.conn, d["id"], ext)
            if os.path.dirname(name) == "":                          # لا مجلد مضبوط للمشروع: ابدأ من آخر مجلد استُعمل
                last = cfg.value("last_export_dir", "")
                if last and os.path.isdir(str(last)):
                    name = os.path.join(str(last), name)
            path, _ = QFileDialog.getSaveFileName(self, title, name, filt)
            if not path:
                return
            if not path.lower().endswith("." + ext):
                path += "." + ext
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                saved = fn(self.win.conn, d["id"], path) or path
            except PermissionError:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "تعذر الحفظ", "الملف مفتوح في برنامج آخر أو المجلد غير قابل للكتابة.\nأغلق الملف أو اختر اسمًا أو مجلدًا مختلفًا ثم أعد المحاولة."); return
            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "تعذر التصدير", f"{e}\n\nلم يتغير شيء في الوثيقة. يمكنك إعادة المحاولة."); return
            QApplication.restoreOverrideCursor()
            cfg.setValue("last_export_dir", os.path.dirname(saved))
            note = "المسودة صُدّرت للمراجعة فقط ولم تُعتمد." if d["status"] == "draft" else "صُدّرت من النسخة الصادرة المحفوظة."
            box = QMessageBox(self); box.setWindowTitle("تم التصدير"); box.setText(f"{saved}\n{note}")
            b_open = box.addButton("فتح الملف", QMessageBox.ButtonRole.AcceptRole)
            b_dir = box.addButton("فتح المجلد", QMessageBox.ButtonRole.ActionRole)
            box.addButton("إغلاق", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == b_open:
                QDesktopServices.openUrl(QUrl.fromLocalFile(saved))
            elif box.clickedButton() == b_dir:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(saved)))
        finally:
            self._end()

    def export_word(self):
        self._export("docx", "حفظ الوثيقة", "Word (*.docx)", EX.export_docx)

    def export_pdf(self):
        self._export("pdf", "حفظ الوثيقة PDF", "PDF (*.pdf)", EX.export_pdf)

    def duplicate(self):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            if not ask(self, "نسخة جديدة", f"ستُنشأ مسودة جديدة من «{d['label']}» بنسخ بيانات الإدخال فقط.\n"
                       "الوثيقة الأصلية تبقى كما هي، ويُدخَل تاريخ الوثيقة الجديدة من جديد. المتابعة؟"):
                return
            try:
                new_id = S.duplicate_document(self.win.conn, d["id"])
            except Exception as e:
                QMessageBox.warning(self, "تعذر", str(e)); return
            self.load()
            EditorDialog(self, self.win.conn, new_id).exec()
        finally:
            self._end()
        self._changed()

    def correct(self):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            if d["status"] != "issued":
                QMessageBox.information(self, "مسودة", "التصحيح يخص الوثيقة الصادرة. المسودة تُعدَّل مباشرة."); return
            if d["archived"]:
                QMessageBox.information(self, "وثيقة مؤرشفة", "استرجع الوثيقة من الأرشيف أولًا ثم أنشئ نسخة تصحيحية."); return
            open_id = SV.open_correction_draft(self.win.conn, d["id"])
            if open_id:
                QMessageBox.information(self, "نسخة تصحيحية مفتوحة",
                                        "توجد نسخة تصحيحية غير مُصدرة لهذه الوثيقة. أكملها أو احذفها قبل إنشاء أخرى (حتى لا تتوازى نسختان)."); return
            reason, ok = QInputDialog.getText(self, "نسخة تصحيحية", "سبب التصحيح (مطلوب، ويُطبع على الوثيقة):")
            if not ok or not reason.strip():
                return
            try:
                S.create_correction(self.win.conn, d["id"], reason.strip())
            except ValueError as e:
                QMessageBox.warning(self, "تعذر", str(e)); return
            self.win.toast("أُنشئت نسخة تصحيحية (مسودة) — الأصل محفوظ كما هو؛ افتحها لتعديلها ثم أصدرها", "info")
        finally:
            self._end()
        self._changed()

    def toggle_archive(self):
        d = self._sel_doc()
        if d is None or not self._begin():
            return
        try:
            if d["status"] != "issued":
                QMessageBox.information(self, "مسودة", "الأرشفة للوثائق الصادرة فقط. المسودة التي لا حاجة لها تُحذف."); return
            if d["archived"]:
                if ask(self, "استرجاع", "ستعود الوثيقة إلى القوائم العادية دون أي تغيير في محتواها. المتابعة؟"):
                    S.restore_document(self.win.conn, d["id"]); self.win.toast("استُرجعت الوثيقة من الأرشيف")
            else:
                if ask(self, "أرشفة وثيقة", f"ستُخفى «{d['label']}» من القوائم الافتراضية.\n"
                       "لا يتغير محتواها ولا تُحذف، ويمكن استرجاعها من صفحة «الأرشيف» في أي وقت. المتابعة؟"):
                    S.archive_document(self.win.conn, d["id"]); self.win.toast("أُرشفت الوثيقة — تجدها في صفحة الأرشيف")
        except Exception as e:
            QMessageBox.warning(self, "تعذر", str(e))
        finally:
            self._end()
        self._changed()

    def delete_draft(self):
        d = self._sel_doc(quiet=True)
        if d is None or not self._begin():
            return
        try:
            if d["status"] != "draft":
                QMessageBox.information(self, "وثيقة صادرة", "الوثيقة الصادرة ثابتة ولا تُحذف أبدًا.\nللتصحيح استعمل «نسخة تصحيحية»، ولإخفائها استعمل «أرشفة»."); return
            extra = f"\nالرقم المحجوز لها ({d['number']:02d}) لن يُعاد استعماله." if d["number"] is not None else ""
            if ask(self, "حذف مسودة", f"حذف مسودة «{d['label']}» نهائيًا مع بياناتها المُدخلة؟\n"
                   f"لا يتأثر المشروع ولا الوثائق الصادرة، ولا يمكن التراجع.{extra}"):
                S.delete_draft(self.win.conn, d["id"]); self.win.toast("حُذفت المسودة", "warn")
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحذف", str(e))
        finally:
            self._end()
        self._changed()
