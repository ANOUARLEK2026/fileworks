import json
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)
from worksapp import storage as S, services as SV
from .company_dialog import CompanyDialog


class ProjectTab(QWidget):
    """بيانات المشروع والعقد فقط (تتغير من مشروع لآخر). بيانات الشركة المتعاقدة الثابتة تُعرض هنا ملخصًا وتُعدَّل من نافذتها."""
    def __init__(self, win):
        super().__init__(); self.win = win
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(12)

        card = QFrame(); card.setObjectName("card"); cl = QHBoxLayout(card); cl.setContentsMargins(14, 12, 14, 12)
        info = QVBoxLayout()
        cap = QLabel("الشركة المتعاقدة (ثابتة لكل المشاريع)"); cap.setObjectName("hint"); info.addWidget(cap)
        self.co_name = QLabel(""); self.co_name.setObjectName("companyName"); info.addWidget(self.co_name)
        self.co_meta = QLabel(""); self.co_meta.setObjectName("companyMeta"); self.co_meta.setWordWrap(True); info.addWidget(self.co_meta)
        cl.addLayout(info, 1)
        side = QVBoxLayout()
        self.co_combo = QComboBox(); self.co_combo.currentIndexChanged.connect(self._link); side.addWidget(self.co_combo)
        edit = QPushButton("تعديل بيانات الشركة"); edit.setObjectName("secondary"); edit.clicked.connect(self.edit_company); side.addWidget(edit)
        cl.addLayout(side)
        root.addWidget(card)
        self.co_warn = QLabel("لم تُدخل بيانات الشركة المتعاقدة بعد؛ ستبقى ترويسة الوثائق وتواقيعها ناقصة. اضغط «تعديل بيانات الشركة».")
        self.co_warn.setObjectName("warnBox"); self.co_warn.setWordWrap(True); root.addWidget(self.co_warn)

        box = QGroupBox("بيانات المشروع والعقد"); form = QFormLayout(box); form.setVerticalSpacing(10)
        self.f = {k: QLineEdit() for k in ("name", "contract_no", "contract_date", "owner")}
        self.extra_keys = [k for k, _ in S.PROJECT_EXTRA_FIELDS]
        for k in self.extra_keys:
            self.f[k] = QLineEdit()
        self.f["contract_date"].setPlaceholderText("مثال: 2026-02-23")
        self.f["contract_amount"].setPlaceholderText("كما يُطبع في الوثيقة، مثال: 11 673 305.00")
        for k, lab in (("name", "اسم المشروع / موضوع العقد"), ("contract_no", "رقم العقد"), ("contract_date", "تاريخ العقد"),
                       ("owner", "المصلحة المتعاقدة / صاحب المشروع")):
            form.addRow(lab, self.f[k])
        for k, lab in S.PROJECT_EXTRA_FIELDS:
            form.addRow(lab, self.f[k])
        root.addWidget(box)
        fbox = QGroupBox("مجلدات حفظ الملفات (Word / PDF)"); fg = QGridLayout(fbox); fg.setVerticalSpacing(8)
        fg.setColumnStretch(1, 1)
        self.dir_base = QLineEdit(); self.dir_base.setPlaceholderText("مجلد المشروع، مثال: D:\\وثائق\\ساحة الشباب")
        fg.addWidget(QLabel("مجلد المشروع"), 0, 0); fg.addWidget(self.dir_base, 0, 1)
        fg.addWidget(self._browse_btn(self.dir_base), 0, 2)
        self.dir_sub = QCheckBox("إنشاء مجلد فرعي باسم نوع الوثيقة داخل مجلد المشروع"); self.dir_sub.setChecked(True)
        fg.addWidget(self.dir_sub, 1, 0, 1, 3)
        note = QLabel("اختياريًا خصّص مجلدًا لكل نوع وثيقة (يغلب مجلد المشروع). اترك الحقل فارغًا لاستعمال مجلد المشروع. "
                      "إن لم يُضبط شيء يسألك البرنامج عند كل تصدير. المجلد يُنشأ تلقائيًا إن لم يوجد.")
        note.setObjectName("hint"); note.setWordWrap(True); fg.addWidget(note, 2, 0, 1, 3)
        self.dir_types = {}
        for i, dt in enumerate(S.DOC_TYPES):
            e = QLineEdit(); e.setPlaceholderText("افتراضي: مجلد المشروع"); self.dir_types[dt] = e
            fg.addWidget(QLabel(SV.DOC_LABELS[dt]), 3 + i, 0); fg.addWidget(e, 3 + i, 1); fg.addWidget(self._browse_btn(e), 3 + i, 2)
        root.addWidget(fbox)
        save = QPushButton("حفظ بيانات المشروع"); save.clicked.connect(self.save); root.addWidget(save)
        hint = QLabel("الضرائب والاقتطاعات في تبويب «الضرائب والاقتطاعات». الوثائق الصادرة سابقًا لا تتأثر بأي تعديل.")
        hint.setObjectName("hint"); root.addWidget(hint); root.addStretch()

    def _browse_btn(self, edit):
        b = QPushButton("استعراض…"); b.setObjectName("secondary")
        def pick():
            path = QFileDialog.getExistingDirectory(self, "اختر المجلد", edit.text().strip() or "")
            if path:
                edit.setText(path)
        b.clicked.connect(pick)
        return b

    def refresh_company(self):
        pid = self.win.pid
        if pid is None:
            return
        co = S.company_for_project(self.win.conn, pid)
        self.co_warn.setVisible(co is None)
        self.co_name.setText(co["name"] if co else "— لا توجد شركة —")
        meta = [f"{label}: {co[k]}" for k, label in S.COMPANY_FIELDS if co and co.get(k)]
        self.co_meta.setText("   ·   ".join(meta))
        companies = S.list_companies(self.win.conn)
        self.co_combo.blockSignals(True); self.co_combo.clear()
        for c in companies:
            self.co_combo.addItem(c["name"], c["id"])
        if co:
            self.co_combo.setCurrentIndex(max(0, self.co_combo.findData(co["id"])))
        self.co_combo.blockSignals(False)
        self.co_combo.setVisible(len(companies) > 1)           # شركة واحدة هي الحالة المعتادة

    def _link(self, *_):
        cid = self.co_combo.currentData()
        if self.win.pid is None or cid is None:
            return
        try:
            S.set_project_company(self.win.conn, self.win.pid, cid)
        except Exception as e:
            QMessageBox.warning(self, "تعذر", str(e)); return
        self.refresh_company(); self.win.refresh_docs()

    def edit_company(self):
        dlg = CompanyDialog(self, self.win.conn, self.win.pid)
        dlg.exec()
        self.refresh_company(); self.win.refresh_docs()

    def load(self, pid):
        p = self.win.conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        for k in ("name", "contract_no", "contract_date", "owner"):
            self.f[k].setText(p[k] or "")
        extra = json.loads(p["extra_json"] or "{}")
        for k in self.extra_keys:
            self.f[k].setText(extra.get(k, ""))
        ps = S.project_settings(self.win.conn, pid)
        self.dir_base.setText(ps.get("export_dir") or "")
        self.dir_sub.setChecked(ps.get("export_subfolders", True))
        for dt, e in self.dir_types.items():
            e.setText((ps.get("export_dirs") or {}).get(dt) or "")
        self.refresh_company()

    def save(self):
        pid = self.win.pid
        if pid is None:
            return
        try:
            S.update_project(self.win.conn, pid, **{k: self.f[k].text().strip() or None
                                                    for k in ("name", "contract_no", "contract_date", "owner")})
            S.update_project_extra(self.win.conn, pid, **{k: self.f[k].text().strip() for k in self.extra_keys})
            base, per = SV.validate_export_dirs(self.dir_base.text(), {dt: e.text() for dt, e in self.dir_types.items()})
            ps = S.project_settings(self.win.conn, pid)
            ps.update({"export_dir": base, "export_subfolders": self.dir_sub.isChecked(),
                       "export_dirs": {k: v for k, v in per.items() if v} or None})
            S.set_project_settings(self.win.conn, pid, ps)
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحفظ", str(e)); return
        self.win.refresh_projects(keep=pid); self.win.update_summary(); self.win.refresh_docs()
        QMessageBox.information(self, "تم", "حُفظت بيانات المشروع. الوثائق الصادرة سابقًا لم تتأثر.")
