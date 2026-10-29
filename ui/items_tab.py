from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)
from worksapp import storage as S, services as SV
from worksapp.money import D, q2
from .dialogs import PasteItemsDialog, ask
from .theme import INPUT_COLOR, CALC_COLOR
from .widgets import make_table, cell, NumberDelegate, CENTER


def _btn(text, fn, name="tool", tip=None):
    b = QPushButton(text); b.setObjectName(name); b.clicked.connect(fn)
    if tip:
        b.setToolTip(tip)
    return b


class ItemsTab(QWidget):
    """بنود العقد: جدول يُعدَّل مباشرة (انقر مرتين على الخلية)، يُحفظ كل تعديل فورًا بعد التحقق منه.
    إعادة الترتيب: أزرار (أعلى/أسفل/بداية/نهاية/نقل إلى موضع) واختصارا Alt+↑ وAlt+↓. الترتيب ينعكس على كل الوثائق الجديدة."""
    COLS = [("#", None), ("رقم البند", "code"), ("وصف البند", "description"), ("الوحدة", "unit"),
            ("سعر الوحدة (دج)", "unit_price"), ("الكمية التعاقدية", "contract_qty"), ("المبلغ HT (دج)", "_amount"),
            ("الفصل (للجرد)", "section")]
    DESC_COL = 2

    def __init__(self, win):
        super().__init__(); self.win = win; self.items = []; self.loading = False
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(_btn("＋ بند جديد", self.add_blank, "primary", "يُضاف بعد البند المحدد"))
        r1.addWidget(_btn("نسخ البند", self.duplicate, tip="ينسخ الوصف والوحدة والسعر والكمية التعاقدية"))
        r1.addWidget(_btn("لصق من Excel", self.paste))
        dele = _btn("حذف البند", self.delete, "danger"); r1.addWidget(dele)
        r1.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText("بحث في البنود (الرقم أو الوصف)…")
        self.search.setClearButtonEnabled(True); self.search.setMinimumWidth(260); self.search.textChanged.connect(self.apply_filter)
        r1.addWidget(self.search)
        root.addLayout(r1)

        r2 = QHBoxLayout(); r2.addWidget(QLabel("ترتيب البنود:"))
        self.move_btns = [_btn("▲ أعلى", lambda: self.move("up"), tip="Alt+↑"), _btn("▼ أسفل", lambda: self.move("down"), tip="Alt+↓"),
                          _btn("⤒ إلى البداية", lambda: self.move("top")), _btn("⤓ إلى النهاية", lambda: self.move("bottom")),
                          _btn("نقل إلى موضع…", self.move_to), _btn("ترتيب حسب الرقم", self.sort_codes)]
        self.move_tips = [b.toolTip() for b in self.move_btns]
        for b in self.move_btns:
            r2.addWidget(b)
        r2.addStretch(); root.addLayout(r2)

        self.hint = QLabel("انقر مرتين على أي خلية لتعديلها؛ يُحفظ التعديل تلقائيًا. تعديل الأسعار والكميات والترتيب لا يغيّر أي وثيقة صادرة.")
        self.hint.setObjectName("hint"); root.addWidget(self.hint)

        self.table = make_table([c[0] for c in self.COLS], editable=True, stretch=self.DESC_COL, min_col=90)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setSectionResizeMode(self.DESC_COL, QHeaderView.ResizeMode.Stretch)
        for c, (_, key) in enumerate(self.COLS):
            if key == "unit_price":
                self.table.setItemDelegateForColumn(c, NumberDelegate(self.table, 2))
            elif key == "contract_qty":
                self.table.setItemDelegateForColumn(c, NumberDelegate(self.table, 3, trim=True))
            elif key == "_amount":
                self.table.setItemDelegateForColumn(c, NumberDelegate(self.table, 2))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx)
        self.table.itemChanged.connect(self.on_changed)
        for seq, where in (("Alt+Up", "up"), ("Alt+Down", "down")):
            sc = QShortcut(QKeySequence(seq), self.table); sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda w=where: self.move(w))
        root.addWidget(self.table, 1)

    # ---------- تحميل وعرض ----------
    @staticmethod
    def _amount(it):
        try:
            p, q = D(it["unit_price"]), D(it["contract_qty"])
        except ValueError:
            return ""
        return "" if p is None or q is None else str(q2(p * q))

    def load(self, pid, select_id=None, edit=False):
        self.loading = True
        self.items = S.list_items(self.win.conn, pid)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            for c, (_, key) in enumerate(self.COLS):
                if key is None:
                    self.table.setItem(r, c, cell(r + 1, color=CALC_COLOR, align=CENTER))
                elif key == "_amount":
                    self.table.setItem(r, c, cell(self._amount(it), color=CALC_COLOR, align=CENTER))
                else:
                    v = it[key]
                    self.table.setItem(r, c, cell("" if v is None else v, editable=True, color=INPUT_COLOR,
                                                  align=CENTER if key != "description" and key != "section" else None))
        self.loading = False
        self.apply_filter()
        if select_id is not None:
            for r, it in enumerate(self.items):
                if it["id"] == select_id:
                    self.table.setCurrentCell(r, self.DESC_COL); self.table.selectRow(r)
                    if edit:
                        self.table.editItem(self.table.item(r, self.DESC_COL))
                    break

    def apply_filter(self, *_):
        q = self.search.text().strip().lower()
        for r, it in enumerate(self.items):
            hit = not q or q in str(it["code"]).lower() or q in str(it["description"] or "").lower()
            self.table.setRowHidden(r, not hit)
        for b, tip in zip(self.move_btns, self.move_tips):
            b.setEnabled(not q)
            b.setToolTip("أفرغ مربع البحث لتفعيل إعادة الترتيب" if q else tip)

    def _current_row(self):
        r = self.table.currentRow()
        return r if 0 <= r < len(self.items) else None

    def _selected_id(self):
        r = self._current_row()
        return None if r is None else self.items[r]["id"]

    def _refresh_after(self, select_id=None, edit=False):
        self.load(self.win.pid, select_id=select_id, edit=edit)
        self.win.update_summary(); self.win.refresh_docs()

    # ---------- التعديل المباشر ----------
    def on_changed(self, item):
        if self.loading:
            return
        r, c = item.row(), item.column()
        key = self.COLS[c][1]
        if key in (None, "_amount") or r >= len(self.items):
            return
        err = None
        try:
            S.update_item_field(self.win.conn, self.items[r]["id"], key, item.text())
        except ValueError as e:
            err = f"البند {self.items[r]['code']}: {e}"
        sel = self.items[r]["id"]
        # لا نعيد بناء الجدول من داخل إشارة الخلية نفسها (قد يُتلف عنصرها)؛ نؤجله إلى حلقة الأحداث التالية
        QTimer.singleShot(0, lambda: self._after_change(err, sel))

    def _after_change(self, err, sel):
        if err:
            QMessageBox.warning(self, "تعذر حفظ التعديل", err)
        self._refresh_after(select_id=sel)

    # ---------- إضافة وحذف ونسخ ----------
    def _need_project(self):
        if not self.win.pid:
            QMessageBox.information(self, "اختر مشروعًا", "اختر مشروعًا من القائمة أو أنشئ مشروعًا جديدًا أولًا.")
            return False
        return True

    def add_blank(self):
        if not self._need_project():
            return
        code = SV.next_item_code(self.win.conn, self.win.pid)
        new_id = S.insert_item_after(self.win.conn, self.win.pid, self._selected_id(), code, "", None, None, None)
        self._refresh_after(select_id=new_id, edit=True)

    def duplicate(self):
        if not self._need_project():
            return
        sel = self._selected_id()
        if sel is None:
            QMessageBox.information(self, "اختر بندًا", "حدد البند الذي تريد نسخه أولًا."); return
        try:
            new_id = S.duplicate_item(self.win.conn, sel, SV.next_item_code(self.win.conn, self.win.pid))
        except Exception as e:
            QMessageBox.warning(self, "تعذر النسخ", str(e)); return
        self._refresh_after(select_id=new_id)

    def paste(self):
        if not self._need_project():
            return
        if PasteItemsDialog(self, self.win.conn, self.win.pid).exec():
            self._refresh_after()

    def delete(self):
        r = self._current_row()
        if r is None:
            QMessageBox.information(self, "اختر بندًا", "حدد صفًا من الجدول أولًا."); return
        it = self.items[r]
        if ask(self, "حذف بند", f"حذف البند {it['code']} مع كمياته وأسطر قياسه؟\nالوثائق الصادرة تحتفظ بنسختها ولا تتأثر."):
            S.delete_item(self.win.conn, it["id"])
            nxt = self.items[r + 1]["id"] if r + 1 < len(self.items) else (self.items[r - 1]["id"] if r > 0 else None)
            self._refresh_after(select_id=nxt)

    # ---------- إعادة الترتيب ----------
    def move(self, where):
        sel = self._selected_id()
        if sel is None:
            QMessageBox.information(self, "اختر بندًا", "حدد البند الذي تريد نقله أولًا."); return
        try:
            S.move_item(self.win.conn, sel, where)
        except ValueError as e:
            QMessageBox.warning(self, "تعذر النقل", str(e)); return
        self._refresh_after(select_id=sel)

    def move_to(self):
        sel, r = self._selected_id(), self._current_row()
        if sel is None:
            QMessageBox.information(self, "اختر بندًا", "حدد البند الذي تريد نقله أولًا."); return
        n = len(self.items)
        pos, ok = QInputDialog.getInt(self, "نقل البند", f"الموضع الجديد (من 1 إلى {n}):", r + 1, 1, n)
        if ok:
            self.move(pos)

    def sort_codes(self):
        if not self._need_project():
            return
        if ask(self, "ترتيب حسب الرقم", "ترتيب كل البنود تصاعديًا حسب رقم البند؟ (يمكنك بعدها نقل أي بند يدويًا)"):
            S.sort_items_by_code(self.win.conn, self.win.pid)
            self._refresh_after(select_id=self._selected_id())

    def _ctx(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0 or r >= len(self.items):
            return
        self.table.setCurrentCell(r, self.DESC_COL); self.table.selectRow(r)
        m = QMenu(self)
        for text, fn in (("نسخ البند", self.duplicate), ("نقل للأعلى", lambda: self.move("up")), ("نقل للأسفل", lambda: self.move("down")),
                         ("نقل إلى موضع…", self.move_to), ("حذف هذا البند…", self.delete)):
            m.addAction(text).triggered.connect(lambda _=False, f=fn: f())
        m.exec(QCursor.pos())
