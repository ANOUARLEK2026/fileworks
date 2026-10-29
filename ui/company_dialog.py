from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QGroupBox)
from worksapp import storage as S


class CompanyDialog(QDialog):
    """بيانات الشركة المتعاقدة (المقاول): ثابتة، تُدخل مرة واحدة وتظهر في ترويسة وتواقيع كل وثائق كل المشاريع.
    تعديلها يسري على المسودات القادمة فقط؛ الوثائق الصادرة تحتفظ بلقطتها."""
    NEW = -1

    def __init__(self, parent, conn, project_id=None, first_run=False):
        super().__init__(parent)
        self.conn, self.pid = conn, project_id
        self.saved_id = None
        self.setWindowTitle("الشركة المتعاقدة")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(660, 680)
        root = QVBoxLayout(self); root.setSpacing(10)
        intro = QLabel(("مرحبًا! أدخل بيانات مؤسستك مرة واحدة هنا. " if first_run else "")
                       + "هذه البيانات ثابتة وتتكرر في كل مشروع، لذلك لا تُدخل داخل المشروع. "
                       "بيانات العقد (اسم المشروع، رقم العقد، المصلحة المتعاقدة…) تُدخل في «بيانات المشروع». "
                       "الحقول الفارغة لا تُطبع في الوثائق.")
        intro.setWordWrap(True); intro.setObjectName("hint"); root.addWidget(intro)

        top = QHBoxLayout()
        top.addWidget(QLabel("الشركة:"))
        self.combo = QComboBox(); self.combo.currentIndexChanged.connect(self._on_pick); top.addWidget(self.combo, 1)
        root.addLayout(top)

        box = QGroupBox("بيانات المؤسسة"); form = QFormLayout(box); form.setVerticalSpacing(8)
        self.name = QLineEdit(); self.name.setPlaceholderText("اسم المؤسسة / الشركة (إجباري)")
        form.addRow("اسم الشركة *", self.name)
        self.f = {}
        hints = {"rc_date": "مثال: 2019-05-14", "rib": "رقم الحساب كما يُطبع", "place": "مثال: الوادي (يظهر في «الوادي في: …»)"}
        for key, label in S.COMPANY_FIELDS:
            self.f[key] = QLineEdit()
            if key in hints:
                self.f[key].setPlaceholderText(hints[key])
            form.addRow(label, self.f[key])
        root.addWidget(box)
        self.default_chk = QCheckBox("الشركة الافتراضية للمشاريع الجديدة"); root.addWidget(self.default_chk)
        self.use_chk = QCheckBox("استعمال هذه الشركة في المشروع الحالي")
        self.use_chk.setVisible(project_id is not None); self.use_chk.setChecked(True); root.addWidget(self.use_chk)
        root.addStretch()
        bar = QHBoxLayout()
        save = QPushButton("حفظ بيانات الشركة"); save.clicked.connect(self.save)
        close = QPushButton("إغلاق"); close.setObjectName("secondary"); close.clicked.connect(self.reject)
        bar.addWidget(save); bar.addStretch(); bar.addWidget(close); root.addLayout(bar)
        self.reload(select_id=(S.company_for_project(conn, project_id) or S.default_company(conn) or {}).get("id")
                    if project_id is not None else (S.default_company(conn) or {}).get("id"))

    def reload(self, select_id=None):
        self.combo.blockSignals(True); self.combo.clear()
        for c in S.list_companies(self.conn):
            self.combo.addItem(c["name"] + ("  (افتراضية)" if c["is_default"] else ""), c["id"])
        self.combo.addItem("＋ شركة جديدة…", self.NEW)
        idx = self.combo.findData(select_id) if select_id is not None else -1
        if idx < 0:
            idx = 0 if self.combo.count() > 1 else self.combo.findData(self.NEW)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self._on_pick()

    def _on_pick(self, *_):
        cid = self.combo.currentData()
        c = S.get_company(self.conn, cid) if cid not in (None, self.NEW) else None
        self.name.setText(c["name"] if c else "")
        for k, w in self.f.items():
            w.setText(c[k] if c else "")
        self.default_chk.setChecked(bool(c and c["is_default"]))
        self.default_chk.setEnabled(not (c and c["is_default"]))      # الافتراضية لا تُلغى إلا بتعيين غيرها
        if c is None:
            self.name.setFocus()

    def save(self):
        cid = self.combo.currentData()
        try:
            new_id = S.save_company(self.conn, None if cid in (None, self.NEW) else cid, self.name.text(),
                                    make_default=True if self.default_chk.isChecked() else None,
                                    **{k: w.text() for k, w in self.f.items()})
            if self.pid is not None and self.use_chk.isChecked():
                S.set_project_company(self.conn, self.pid, new_id)
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحفظ", str(e)); return
        self.saved_id = new_id
        self.reload(select_id=new_id)
        QMessageBox.information(self, "تم", "حُفظت بيانات الشركة. الوثائق الصادرة سابقًا لم تتأثر.")
        self.accept()
