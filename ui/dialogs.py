import json
import os
import shutil
import tempfile
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton, QComboBox,
                               QMessageBox, QTableWidgetItem, QGroupBox, QPlainTextEdit, QTabWidget, QWidget)
from worksapp import storage as S, services as SV
from worksapp.money import D
from .widgets import make_table, cell, AlertsTable, qty_text, protect_numbers, NumberDelegate
from .theme import INPUT_COLOR, CALC_COLOR, CELL_TEXT
from .fx import ask as _ask


def ask(parent, title, text):
    return _ask(parent, title, text)


class NewItemDialog(QDialog):
    def __init__(self, parent, project_id, conn):
        super().__init__(parent)
        self.conn, self.pid = conn, project_id
        self.setWindowTitle("إضافة بند إلى العقد")
        form = QFormLayout(self)
        self.code, self.desc, self.unit = QLineEdit(), QLineEdit(), QLineEdit()
        self.price, self.qty, self.section = QLineEdit(), QLineEdit(), QLineEdit()
        for label, w in (("رقم البند", self.code), ("وصف البند", self.desc), ("الوحدة (و، م², م³، مط، ج...)", self.unit),
                         ("سعر الوحدة (دج)", self.price), ("الكمية التعاقدية", self.qty),
                         ("الفصل (للجرد، اختياري)", self.section)):
            form.addRow(label, w)
        ok = QPushButton("حفظ البند"); ok.clicked.connect(self.save); form.addRow(ok)

    def save(self):
        try:
            if not self.code.text().strip():
                raise ValueError("رقم البند مطلوب")
            S.add_item(self.conn, self.pid, self.code.text().strip(), self.desc.text(), self.unit.text() or None,
                       D(self.price.text()), D(self.qty.text()), section=self.section.text().strip() or None)
            self.accept()
        except Exception as e:     # رسالة تشرح المشكلة والحقل
            QMessageBox.warning(self, "تعذر الحفظ", f"{e}\nتحقق من الحقول: رقم البند فريد داخل المشروع، والأرقام صحيحة.")


class PasteItemsDialog(QDialog):
    """إدراج عدة بنود دفعة واحدة من Excel أو أي جدول (نسخ ثم لصق). يتحقق من كل سطر قبل أي كتابة."""
    def __init__(self, parent, conn, project_id):
        super().__init__(parent)
        self.conn, self.pid = conn, project_id
        self.setWindowTitle("لصق بنود من جدول"); self.resize(900, 520)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("انسخ الأعمدة من Excel ثم الصقها هنا. الترتيب: رقم البند | وصف | وحدة | سعر الوحدة | الكمية | الفصل (اختياري).\n"
                              "سطر العناوين يُتجاهل تلقائيًا. الأرقام تقبل 1 500,00 أو 1500.00 أو الأرقام العربية."))
        self.text = QPlainTextEdit(); root.addWidget(self.text)
        self.msg = QLabel(""); self.msg.setWordWrap(True); root.addWidget(self.msg)
        row = QHBoxLayout()
        clip = QPushButton("لصق من الحافظة"); clip.setObjectName("secondary"); clip.clicked.connect(lambda: self.text.setPlainText(QApplication.clipboard().text()))
        add = QPushButton("تحقق وأضف البنود"); add.clicked.connect(self.add)
        row.addWidget(clip); row.addStretch(); row.addWidget(add); root.addLayout(row)

    def add(self):
        rows, errors = SV.parse_items_text(self.conn, self.pid, self.text.toPlainText())
        if errors:
            self.msg.setText("لم يُضف أي بند. صحّح الأسطر التالية:\n" + "\n".join(errors[:12]) + ("\n…" if len(errors) > 12 else ""))
            return
        if not rows:
            self.msg.setText("لا توجد أسطر للإضافة."); return
        try:
            S.add_items_bulk(self.conn, self.pid, rows)
        except Exception as e:
            self.msg.setText(f"تعذر الحفظ: {e}"); return
        QMessageBox.information(self, "تم", f"أُضيف {len(rows)} بندًا.")
        self.accept()


class MeasureLinesDialog(QDialog):
    """أسطر القياس لبند واحد: اختيار معادلة، مدخلاتها، نتيجة كل سطر، المجموع، والتعديل اليدوي مع الأصل."""
    def __init__(self, parent, conn, item):
        super().__init__(parent)
        self.conn, self.item = conn, item
        self.setWindowTitle(f"أسطر القياس — بند {item['code']}")
        self.resize(900, 520)
        self.formulas = S.load_formulas(conn)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(item["description"] or ""))
        self.table = make_table(["المعادلة", "المدخلات", "الوصف", "الموقع", "النتيجة (دقة كاملة)"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        root.addWidget(self.table)
        line_actions = QHBoxLayout()
        self.edit_selected_btn = QPushButton("تعديل السطر المحدد"); self.edit_selected_btn.clicked.connect(self.edit_selected_line)
        self.delete_selected_btn = QPushButton("حذف السطر المحدد"); self.delete_selected_btn.setObjectName("danger"); self.delete_selected_btn.clicked.connect(self.delete_selected_line)
        line_actions.addWidget(self.edit_selected_btn); line_actions.addWidget(self.delete_selected_btn); line_actions.addStretch()
        root.addLayout(line_actions)
        self.edit_line_id = None
        box = QGroupBox("إضافة سطر قياس"); bl = QVBoxLayout(box)
        self.combo = QComboBox()
        sug = None
        from worksapp.formulas import suggest_for_unit
        sug = suggest_for_unit(item.get("unit"))
        for code, f in self.formulas.items():
            self.combo.addItem(f.name + ("  (مقترحة)" if code == sug else ""), code)
        if sug:
            self.combo.setCurrentIndex(self.combo.findData(sug))
        self.combo.currentIndexChanged.connect(self.build_inputs)
        bl.addWidget(self.combo)
        self.inputs_row = QHBoxLayout(); bl.addLayout(self.inputs_row)
        self.label_edit, self.loc_edit = QLineEdit(), QLineEdit()
        self.label_edit.setPlaceholderText("وصف (اختياري)"); self.loc_edit.setPlaceholderText("موقع الأشغال (اختياري)")
        bl.addWidget(self.label_edit); bl.addWidget(self.loc_edit)
        self.add_btn = QPushButton("إضافة السطر"); self.add_btn.clicked.connect(self.add_line); bl.addWidget(self.add_btn)
        self.cancel_edit_btn = QPushButton("إلغاء التعديل"); self.cancel_edit_btn.setObjectName("secondary")
        self.cancel_edit_btn.clicked.connect(self.cancel_edit); self.cancel_edit_btn.setVisible(False); bl.addWidget(self.cancel_edit_btn)
        root.addWidget(box)
        self.total = QLabel(); self.total.setObjectName("title"); root.addWidget(self.total)
        ov = QHBoxLayout()
        self.ov_qty, self.ov_reason = QLineEdit(), QLineEdit()
        self.ov_qty.setPlaceholderText("الكمية بعد التعديل اليدوي"); self.ov_reason.setPlaceholderText("سبب التعديل")
        b = QPushButton("تطبيق تعديل يدوي"); b.setObjectName("secondary"); b.clicked.connect(self.override)
        ov.addWidget(self.ov_qty); ov.addWidget(self.ov_reason); ov.addWidget(b); root.addLayout(ov)
        self.fields = {}
        self.build_inputs(); self.refresh()

    def build_inputs(self):
        while self.inputs_row.count():
            w = self.inputs_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.fields = {}
        f = self.formulas[self.combo.currentData()]
        for spec in f.inputs:
            e = QLineEdit(); e.setPlaceholderText(spec["label"] + (f" (افتراضي {spec['default']})" if spec.get("default") else ""))
            self.fields[spec["name"]] = e; self.inputs_row.addWidget(e)

    def add_line(self):
        vals = {k: e.text().strip() for k, e in self.fields.items() if e.text().strip()}
        try:
            from worksapp.formulas import evaluate
            evaluate(self.formulas[self.combo.currentData()], vals)       # تحقق قبل الحفظ
            if self.edit_line_id is None:
                S.add_measure_line(self.conn, self.item["id"], self.combo.currentData(), vals,
                                   self.label_edit.text(), self.loc_edit.text())
            else:
                S.update_measure_line(self.conn, self.edit_line_id, self.combo.currentData(), vals,
                                      self.label_edit.text(), self.loc_edit.text())
        except Exception as e:
            QMessageBox.warning(self, "سطر غير صالح", str(e)); return
        self.cancel_edit(); self.refresh()

    def edit_selected_line(self):
        idx = self.table.currentRow()
        if idx < 0 or idx >= len(getattr(self, "measure_rows", [])):
            QMessageBox.information(self, "اختر سطرًا", "حدد سطر القياس الذي تريد تعديله أولًا.")
            return
        row = self.measure_rows[idx]
        self.edit_line_id = row["id"]
        found = self.combo.findData(row["formula_code"])
        if found >= 0:
            self.combo.setCurrentIndex(found)
        values = json.loads(row["inputs_json"] or "{}")
        for key, widget in self.fields.items():
            widget.setText(str(values.get(key, "")))
        self.label_edit.setText(row["label"] or "")
        self.loc_edit.setText(row["location"] or "")
        self.add_btn.setText("حفظ تعديل السطر")
        self.cancel_edit_btn.setVisible(True)

    def delete_selected_line(self):
        idx = self.table.currentRow()
        if idx < 0 or idx >= len(getattr(self, "measure_rows", [])):
            QMessageBox.information(self, "اختر سطرًا", "حدد سطر القياس الذي تريد حذفه أولًا.")
            return
        row = self.measure_rows[idx]
        if not ask(self, "حذف سطر القياس", f"حذف سطر القياس رقم {row['position']}؟ سيُعاد حساب مجموع البند."):
            return
        try:
            S.delete_measure_line(self.conn, row["id"])
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحذف", str(e)); return
        if self.edit_line_id == row["id"]:
            self.cancel_edit()
        self.refresh()

    def cancel_edit(self):
        self.edit_line_id = None
        for widget in getattr(self, "fields", {}).values():
            widget.clear()
        if hasattr(self, "label_edit"):
            self.label_edit.clear(); self.loc_edit.clear()
        if hasattr(self, "add_btn"):
            self.add_btn.setText("إضافة السطر")
        if hasattr(self, "cancel_edit_btn"):
            self.cancel_edit_btn.setVisible(False)

    def override(self):
        if not self.ov_qty.text().strip():
            S.set_override(self.conn, self.item["id"], None, ""); self.refresh(); return
        if not self.ov_reason.text().strip() and not ask(self, "تعديل بلا سبب", "لم تكتب سببًا للتعديل. المتابعة دون سبب؟"):
            return
        S.set_override(self.conn, self.item["id"], D(self.ov_qty.text()), self.ov_reason.text()); self.refresh()

    def refresh(self):
        rows = self.conn.execute("SELECT * FROM measure_lines WHERE item_id=? ORDER BY position", (self.item["id"],)).fetchall()
        self.measure_rows = [dict(row) for row in rows]
        from worksapp.formulas import evaluate
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            f = self.formulas[row["formula_code"]]; vals = json.loads(row["inputs_json"])
            res = evaluate(f, vals)
            for c, v in enumerate([f.name, "  ×  ".join(f"{k}={v}" for k, v in vals.items()), row["label"], row["location"], str(res)]):
                self.table.setItem(r, c, cell(v, color=CALC_COLOR if c == 4 else None))
        q = S.get_quantity(self.conn, self.item["id"])
        txt = f"المجموع الكلي: {qty_text(q.shown)} {self.item.get('unit') or ''}"
        if q.overridden:
            txt += f"   (عُدّلت يدويًا؛ المحسوب الأصلي: {qty_text(q.computed)})"
        self.total.setText(txt)


class QuantityConflictsDialog(QDialog):
    """قرار بشري موثّق لاختيار المصدر المعتمد عند تعارض كميات البند."""
    def __init__(self, parent, conn, project_id):
        super().__init__(parent)
        self.conn, self.pid = conn, project_id
        self.setWindowTitle("حسم تعارض الكميات")
        self.resize(1000, 560)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("تختلف الكمية بين مصدرين أو أكثر. اختر البند ثم مصدر الكمية الصحيح، واكتب سبب القرار. لا يختار البرنامج كمية نيابةً عنك."))
        self.table = make_table(["رقم البند", "تعيين الأشغال", "بيان الأشغال", "حوصلة الأشغال", "وضعية الأشغال"])
        root.addWidget(self.table, 1)
        form = QFormLayout()
        self.source = QComboBox()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("مثال: محضر القياس الميداني المؤرخ ...")
        form.addRow("المصدر/الكمية المعتمدة", self.source)
        form.addRow("سبب الاعتماد (إجباري)", self.reason)
        root.addLayout(form)
        bar = QHBoxLayout()
        approve = QPushButton("اعتماد الكمية المختارة")
        approve.clicked.connect(self.approve)
        cancel = QPushButton("إغلاق")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        bar.addStretch(); bar.addWidget(cancel); bar.addWidget(approve)
        root.addLayout(bar)
        self.records = []
        self.table.currentCellChanged.connect(self.load_choices)
        self.load()

    def load(self):
        self.records = SV.quantity_conflicts(self.conn, self.pid)
        self.table.setRowCount(len(self.records))
        for r, item in enumerate(self.records):
            vals = [item["code"], item["description"],
                    qty_text(item["values"].get("بيان الأشغال")),
                    qty_text(item["values"].get("حوصلة الأشغال")),
                    qty_text(item["values"].get("وضعية الأشغال"))]
            for c, value in enumerate(vals):
                self.table.setItem(r, c, cell(value))
        if self.records:
            self.table.setCurrentCell(0, 0)
            self.load_choices(0, 0, -1, -1)
        else:
            self.source.clear()

    def load_choices(self, row, *_):
        self.source.clear()
        if row < 0 or row >= len(self.records):
            return
        for source, qty in self.records[row]["values"].items():
            self.source.addItem(f"{source}: {qty_text(qty)}", (source, str(qty)))

    def approve(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            QMessageBox.information(self, "اختر بندًا", "حدد بندًا من الجدول أولًا.")
            return
        selected = self.source.currentData()
        if not selected:
            QMessageBox.warning(self, "مصدر غير محدد", "اختر المصدر والكمية المعتمدة.")
            return
        reason = self.reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "سبب الاعتماد مطلوب", "اكتب سبب القرار حتى يبقى قابلًا للمراجعة لاحقًا.")
            return
        item = self.records[row]
        source, qty = selected
        try:
            S.approve_quantity(self.conn, item["item_id"], qty, source, reason)
        except Exception as e:
            QMessageBox.warning(self, "تعذر اعتماد الكمية", str(e))
            return
        self.reason.clear()
        self.load()
        if not self.records:
            QMessageBox.information(self, "اكتمل الحسم", "حُسمت كل تعارضات الكميات. ستستعمل الحسابات الكمية المعتمدة مع حفظ المصدر والسبب.")
            self.accept()
        else:
            QMessageBox.information(self, "تم تسجيل القرار", f"اعتمدت كمية البند {item['code']} من {source}. بقيت {len(self.records)} حالة تحتاج قرارًا.")


class EditorDialog(QDialog):
    """محرر مسودة: جدول مدخلات حسب نوع الوثيقة. الحقول الملونة بالأبيض يدخلها المستخدم، والرمادية للقراءة."""
    def __init__(self, parent, conn, doc_id):
        super().__init__(parent)
        self.conn, self.doc_id = conn, doc_id
        self.doc = S.get_document(conn, doc_id)
        self.dt = self.doc["doc_type"]
        self._dirty = False
        self.setWindowTitle(f"{SV.DOC_LABELS[self.dt]} — مسودة")
        self.resize(1280, 720)
        root = QVBoxLayout(self)
        self.items = S.list_items(conn, self.doc["project_id"])
        if self.dt != "inventory":
            self.final_chk = QCheckBox("إضافة «والنهائي» إلى عنوان الوثيقة (مثل: رقم: 01 والنهائي)")
            cur = json.loads(self.doc["payload_json"] or "{}").get("config", {}).get("final")
            self.final_chk.setChecked(bool(cur))
            self.final_chk.toggled.connect(self.save_final)
            root.addWidget(self.final_chk)
        if self.dt == "bayan":
            self.build_bayan(root)
        else:
            self.build_grid(root)
        cfg = json.loads(self.doc["payload_json"] or "{}").get("config", {})
        meta = QHBoxLayout()
        self.date_edit, self.place_edit = QLineEdit(cfg.get("date", "")), QLineEdit(cfg.get("place", ""))
        self.date_edit.setPlaceholderText("مثال: 2026-03-31 (يُطبع كما يُكتب)")
        self.place_edit.setPlaceholderText("الافتراضي: مدينة الشركة")
        for lab, w in (("تاريخ الوثيقة:", self.date_edit), ("مكان التحرير:", self.place_edit)):
            meta.addWidget(QLabel(lab)); meta.addWidget(w)
        self.date_edit.editingFinished.connect(self.save_meta); self.place_edit.editingFinished.connect(self.save_meta)
        root.addLayout(meta)
        btns = QHBoxLayout()
        if self.dt != "bayan":
            save = QPushButton("حفظ المسودة"); save.clicked.connect(self.save); btns.addWidget(save)
        prev = QPushButton("معاينة وتنبيهات"); prev.clicked.connect(self.open_preview); btns.addWidget(prev)
        root.addLayout(btns)

    def save_meta(self):
        S.set_doc_config(self.conn, self.doc_id, date=self.date_edit.text().strip(), place=self.place_edit.text().strip())
        self.doc = S.get_document(self.conn, self.doc_id)

    def save_final(self, on):
        pl = json.loads(S.get_document(self.conn, self.doc_id)["payload_json"] or "{}")
        pl.setdefault("config", {})["final"] = bool(on)
        S.update_draft_payload(self.conn, self.doc_id, pl)
        self.doc = S.get_document(self.conn, self.doc_id)

    # --- بيان الأشغال ---
    def build_bayan(self, root):
        root.addWidget(QLabel("لكل بند: إدخال مباشر للكمية، أو أسطر قياس. البنود بلا كمية لا تظهر في البيان ولا تُعتبر صفرًا."))
        self.btable = make_table(["الرقم", "تعيين الأشغال", "الوحدة", "الكمية الحالية", "إدخال مباشر", "أسطر القياس"], editable=True)
        self.btable.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            self.btable.setItem(r, 0, cell(it["code"])); self.btable.setItem(r, 1, cell(it["description"]))
            self.btable.setItem(r, 2, cell(it["unit"]))
            self.btable.setItem(r, 4, cell("", editable=True, color=INPUT_COLOR))
            b = QPushButton("أسطر القياس…"); b.setObjectName("secondary")
            b.clicked.connect(lambda _=False, item=it: self.open_lines(item))
            self.btable.setCellWidget(r, 5, b)
        self.btable.itemChanged.connect(self.on_direct)
        root.addWidget(self.btable); self.refresh_bayan()

    def refresh_bayan(self):
        self.btable.blockSignals(True)
        for r, it in enumerate(self.items):
            has = self.conn.execute("SELECT 1 FROM item_quantities WHERE item_id=?", (it["id"],)).fetchone()
            self.btable.setItem(r, 3, cell(qty_text(S.get_quantity(self.conn, it["id"]).shown) if has else "—", color=CALC_COLOR, align=Qt.AlignmentFlag.AlignCenter))
        self.btable.blockSignals(False)

    def on_direct(self, item):
        if item.column() != 4 or not item.text().strip():
            return
        it = self.items[item.row()]
        try:
            if S.count_measure_lines(self.conn, it["id"]) and not ask(
                    self, "استبدال", "للبند أسطر قياس. الإدخال المباشر سيستبدل طريقة الحساب (تبقى الأسطر محفوظة). المتابعة؟"):
                item.setText(""); return
            S.set_direct_quantity(self.conn, it["id"], D(item.text()))
        except Exception as e:
            QMessageBox.warning(self, "قيمة غير صالحة", f"البند {it['code']}: {e}"); item.setText(""); return
        self.refresh_bayan()

    def open_lines(self, it):
        MeasureLinesDialog(self, self.conn, it).exec(); self.refresh_bayan()

    # --- بقية الوثائق ---
    def build_grid(self, root):
        self.cols = SV.EDITOR_COLUMNS[self.dt]
        payload = json.loads(self.doc["payload_json"] or "{}")
        self.table = make_table([c[1] for c in self.cols], editable=True)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            row = {"code": it["code"], "description": it["description"], "unit": it["unit"],
                   "price": it["unit_price"], "contract_qty": it["contract_qty"]}
            row.update(payload.get("rows", {}).get(it["code"], {}))
            for c, (key, _, edit) in enumerate(self.cols):
                if key == "increase_status":
                    cb = QComboBox()
                    for k, lab in SV.INCREASE_STATUS_LABELS.items():
                        cb.addItem(lab, k)
                    cb.setCurrentIndex(max(0, cb.findData(row.get("increase_status") or "pending")))
                    cb.currentIndexChanged.connect(self._mark_dirty)
                    self.table.setCellWidget(r, c, cb)
                else:
                    self.table.setItem(r, c, cell(row.get(key), editable=edit, color=INPUT_COLOR if edit else CALC_COLOR))
        for c, (key, _, edit) in enumerate(self.cols):          # عرض الأرقام المقروءة فقط منسقة وبحماية الاتجاه
            if not edit and key in ("price",):
                self.table.setItemDelegateForColumn(c, NumberDelegate(self.table, 2))
            elif not edit and key == "contract_qty":
                self.table.setItemDelegateForColumn(c, NumberDelegate(self.table, 3, trim=True))
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.itemChanged.connect(self._cell_changed)        # بعد التعبئة: لا تُعدّ التعبئة الأولية تغييرًا
        root.addWidget(self.table)

    def collect(self):
        rows = {}
        for r, it in enumerate(self.items):
            row = {}
            for c, (key, _, edit) in enumerate(self.cols):
                if not edit:
                    continue
                w = self.table.cellWidget(r, c)
                if w is not None:
                    row[key] = w.currentData()
                else:
                    t = self.table.item(r, c).text().strip()
                    row[key] = t or None
            rows[it["code"]] = row
        return rows

    # --- التحقق الفوري وتتبع التغييرات ---
    def _mark_dirty(self, *_):
        self._dirty = True

    @staticmethod
    def _problem(text):
        """سبب رفض قيمة رقمية (أو None إن كانت صالحة/فارغة). يظهر بجانب الحقل نفسه."""
        t = (text or "").strip()
        if not t:
            return None
        try:
            v = D(t)
        except ValueError:
            return "ليست رقمًا صالحًا. اكتب أرقامًا فقط مثل 12.5 (بلا حروف)."
        if v < 0:
            return "لا تُقبل قيمة سالبة هنا."
        return None

    def _cell_changed(self, item):
        self._mark_dirty()
        key = self.cols[item.column()][0]
        if not self.cols[item.column()][2] or key == "increase_status":
            return
        why = self._problem(item.text())
        self.table.blockSignals(True)
        item.setBackground(QColor("#fbd9d6") if why else INPUT_COLOR)
        item.setForeground(CELL_TEXT)
        item.setToolTip(why or "")
        self.table.blockSignals(False)

    def _invalid_cells(self):
        bad = []
        for r, it in enumerate(self.items):
            for c, (key, label, edit) in enumerate(self.cols):
                if edit and key != "increase_status":
                    why = self._problem(self.table.item(r, c).text())
                    if why:
                        bad.append(f"البند {it['code']} — «{label}»: {why}")
        return bad

    def save(self):
        bad = self._invalid_cells()
        if bad:
            QMessageBox.warning(self, "لم تُحفظ المسودة", "صحّح القيم التالية (مظللة بالأحمر في الجدول) ثم احفظ:\n\n" + "\n".join(bad[:12])
                                + ("\n…" if len(bad) > 12 else ""))
            return False
        payload = json.loads(S.get_document(self.conn, self.doc_id)["payload_json"] or "{}")
        payload["rows"] = self.collect()
        S.update_draft_payload(self.conn, self.doc_id, payload)
        self._dirty = False
        QMessageBox.information(self, "تم الحفظ", "حُفظت المسودة. لم تُعتمد بعد.")
        return True

    def reject(self):
        """إغلاق (Esc أو زر الإغلاق): ينبّه إن كانت هناك تغييرات لم تُحفظ."""
        if self._dirty and self.dt != "bayan":
            box = QMessageBox(self); box.setWindowTitle("تغييرات غير محفوظة")
            box.setText("في المسودة تغييرات لم تُحفظ بعد. ماذا تريد؟")
            b_save = box.addButton("حفظ ثم إغلاق", QMessageBox.ButtonRole.AcceptRole)
            b_drop = box.addButton("إغلاق دون حفظ", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("متابعة التحرير", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            chosen = box.clickedButton()
            if chosen == b_save:
                if not self.save():
                    return
            elif chosen != b_drop:
                return
        super().reject()

    def open_preview(self):
        if self.dt != "bayan" and not self.save():
            return
        PreviewDialog(self, self.conn, self.doc_id).exec()


class PreviewDialog(QDialog):
    """تبويبان: «البيانات والتنبيهات» (فوري) و«شكل الوثيقة» (صفحات PDF مولّدة بنفس مسار التصدير، تُحمَّل عند الطلب).
    إن تعذرت المعاينة المطابقة تُعلَم المستخدم صراحةً أن ما يراه تقريبي وليس نسخة مطابقة."""
    def __init__(self, parent, conn, doc_id):
        super().__init__(parent)
        self.conn, self.doc_id = conn, doc_id
        self._tmp, self._pdf_doc, self._pdf_loaded = None, None, False
        self.setWindowTitle("معاينة الوثيقة والتنبيهات"); self.resize(1200, 760)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        try:
            c = SV.preview(conn, doc_id)
        except ValueError as e:
            root.addWidget(QLabel(str(e))); return
        self.c = c
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        data = QWidget(); dl = QVBoxLayout(data)
        headers, rows = c["view"]
        t = make_table(headers); t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for k, v in enumerate(row):
                t.setItem(r, k, cell(protect_numbers(v)))
        dl.addWidget(t, 3)
        dl.addWidget(QLabel("التنبيهات والنواقص والتعارضات (راجعها قبل الاعتماد):"))
        al = AlertsTable(); al.set_alerts(c["alerts"]); dl.addWidget(al, 2)
        self.tabs.addTab(data, "البيانات والتنبيهات")
        self.page_tab = QWidget(); self.page_layout = QVBoxLayout(self.page_tab)
        self.page_note = QLabel("افتح هذا التبويب لتوليد صفحات الوثيقة بالشكل النهائي (قد يستغرق بضع ثوانٍ)."); self.page_note.setWordWrap(True)
        self.page_layout.addWidget(self.page_note)
        self.tabs.addTab(self.page_tab, "شكل الوثيقة (مطابق للتصدير)")
        self.tabs.currentChanged.connect(self._tab_changed)
        row = QHBoxLayout()
        self.btn = QPushButton("اعتماد وإصدار")
        self.btn.setEnabled(c["doc"]["status"] == "draft")
        self.btn.clicked.connect(self.issue); row.addWidget(self.btn)
        close = QPushButton("إغلاق (تبقى مسودة)" if c["doc"]["status"] == "draft" else "إغلاق"); close.setObjectName("secondary")
        close.clicked.connect(self.reject)
        row.addWidget(close); root.addLayout(row)
        self.finished.connect(self._cleanup)

    def _tab_changed(self, i):
        if i == 1 and not self._pdf_loaded:
            self._load_pages()

    def _load_pages(self):
        self._pdf_loaded = True
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
        except ImportError:
            self.page_note.setText("عرض صفحات PDF غير متاح في هذا التثبيت من PySide6. استعمل «تصدير PDF» لرؤية الشكل النهائي؛ "
                                   "والجدول في تبويب البيانات معاينة تقريبية وليس مطابقًا لتنسيق الصفحة.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._tmp = tempfile.mkdtemp(prefix="works_prev_")
            path = SV.preview_pdf(self.conn, self.doc_id, os.path.join(self._tmp, "preview.pdf"))
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.page_note.setText(f"تعذرت المعاينة المطابقة: {e}\nما تراه في تبويب البيانات معاينة تقريبية لا تعكس تنسيق الصفحة، "
                                   "ولا يُغني عن مراجعة الملف المصدَّر.")
            return
        QApplication.restoreOverrideCursor()
        doc = QPdfDocument(self)
        doc.load(path)
        if doc.pageCount() == 0:
            self.page_note.setText("تعذر عرض ملف المعاينة. استعمل «تصدير PDF» لرؤية الشكل النهائي.")
            return
        view = QPdfView(self)
        view.setDocument(doc); view.setPageMode(QPdfView.PageMode.MultiPage); view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.page_layout.addWidget(view, 1)
        self._pdf_doc = doc
        self.page_note.setText(f"صفحات مولّدة بنفس مسار التصدير (Word ← PDF) فهي مطابقة للملف النهائي. عدد الصفحات: {doc.pageCount()}")

    def _cleanup(self, *_):
        if self._pdf_doc is not None:
            self._pdf_doc.close()
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def issue(self):
        if not ask(self, "اعتماد وإصدار",
                   "سيُحفظ نسخة ثابتة من الوثيقة وبياناتها وحساباتها ولن يمكن تعديلها لاحقًا (التصحيح بنسخة جديدة). المتابعة؟"):
            return
        try:
            n = SV.issue(self.conn, self.doc_id, explicit_approval=True)
        except S.IssueBlocked as e:
            QMessageBox.warning(self, "لا يمكن الاعتماد", "توجد مشكلات تمنع الاعتماد:\n" + "\n".join(
                f"• {b['problem']} ({b['affected']}) — {b['action']}" for b in e.blocking))
            return
        QMessageBox.information(self, "تم الإصدار", f"صدرت الوثيقة برقم {n}.")
        self.accept()
