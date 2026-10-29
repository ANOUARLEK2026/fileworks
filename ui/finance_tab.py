import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)
from worksapp import storage as S
from worksapp.money import D
from .widgets import field_label

METHODS = [("غير مضبوط", None), ("نسبة مئوية", "percent"), ("مبلغ ثابت", "fixed"), ("قيمة تدخل يدويًا", "manual"),
           ("غير مطبق (صراحةً)", "none")]
BASES = [("—", None), ("HT مبلغ الفترة", "ht_period"), ("HT التراكمي", "ht_cumulative"), ("الضريبة (الفترة)", "tva_period"),
         ("TTC مبلغ الفترة", "ttc_period"), ("TTC التراكمي", "ttc_cumulative")]
SCOPES = [("—", None), ("على مبلغ الوضعية", "per_situation"), ("هدف تراكمي", "cumulative_target")]
MODES = [("غير محدد", None), ("مبالغ الفترة", "period"), ("مبالغ تراكمية", "cumulative")]
PRESETS = [("guarantee", "Retenue de garantie"), ("advance", "Remboursement d'avance"), ("penalty", "Pénalités de retard")]


def combo(options, current=None):
    cb = QComboBox()
    for label, val in options:
        cb.addItem(label, val)
    cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


def parse_rate(text, what):
    """نسبة بين 0 و1 (0.19) أو بعلامة % (19%). الرقم 19 وحده يُرفض كي لا يُحسب 1900%."""
    t = (text or "").strip()
    if not t:
        return None
    pct = t.endswith("%")
    n = D(t[:-1] if pct else t)
    if pct:
        n = n / D("100")
    if n < 0 or n > 1:
        raise ValueError(f"{what}: أدخل نسبة بين 0 و1 (مثل 0.19) أو بعلامة % (مثل 19%)")
    return format(n.normalize(), "f")


def non_negative(text, what):
    t = (text or "").strip()
    if not t:
        return None
    n = D(t)
    if n < 0:
        raise ValueError(f"{what}: لا تقبل قيمة سالبة")
    return str(n)


class DeductionCard(QFrame):
    """اقتطاع واحد في بطاقة مستقلة (بدل جدول مضغوط): كل الحقول ظاهرة دون تمرير أفقي."""
    def __init__(self, data, on_delete):
        super().__init__()
        self.setObjectName("dedCard")
        self.code = data.get("code") or "x"
        g = QGridLayout(self); g.setContentsMargins(14, 10, 14, 12); g.setHorizontalSpacing(12); g.setVerticalSpacing(4)
        for c in range(4):
            g.setColumnStretch(c, 1)
        self.enabled = QCheckBox("مطبّق في الوضعيات"); self.enabled.setChecked(data.get("enabled", True))
        self.enabled.toggled.connect(self._style)
        self.label = QLineEdit(data.get("label", "")); self.label.setPlaceholderText("اسم الاقتطاع (مثل Retenue de garantie)")
        dele = QPushButton("حذف"); dele.setObjectName("danger"); dele.clicked.connect(lambda: on_delete(self))
        g.addWidget(self.enabled, 0, 0); g.addWidget(self.label, 0, 1, 1, 2); g.addWidget(dele, 0, 3)
        self.method = combo(METHODS, data.get("method")); self.method.currentIndexChanged.connect(self._sync)
        self.rate = QLineEdit("" if data.get("rate") is None else str(data["rate"])); self.rate.setPlaceholderText("0.10 أو 10%")
        self.base = combo(BASES, data.get("base")); self.scope = combo(SCOPES, data.get("scope"))
        self.previous = QLineEdit("" if data.get("previous") is None else str(data["previous"]))
        self.previous.setPlaceholderText("مبلغ مقتطع في وضعيات سابقة")
        extra = data.get("amount") if data.get("method") in ("fixed", "manual") else data.get("remaining_cap")
        self.extra = QLineEdit("" if extra is None else str(extra))
        self.extra_label = field_label("مبلغ / سقف متبقٍ")
        self.pairs = {}
        for i, (key, text, w) in enumerate((("method", "الطريقة", self.method), ("rate", "النسبة", self.rate),
                                            ("base", "الأساس", self.base), ("scope", "النطاق", self.scope))):
            lab = field_label(text); g.addWidget(lab, 1, i); g.addWidget(w, 2, i); self.pairs[key] = (lab, w)
        lp = field_label("المقتطع سابقًا"); g.addWidget(lp, 3, 0); g.addWidget(self.previous, 4, 0)
        self.pairs["previous"] = (lp, self.previous)
        g.addWidget(self.extra_label, 3, 1); g.addWidget(self.extra, 4, 1)
        self.pairs["extra"] = (self.extra_label, self.extra)
        self._sync(); self._style()

    def _style(self, *_):
        self.setProperty("disabledCard", not self.enabled.isChecked())
        self.style().unpolish(self); self.style().polish(self)

    def _sync(self, *_):
        m = self.method.currentData()
        show = {"rate": m == "percent", "base": m == "percent", "scope": m == "percent", "previous": m == "percent",
                "extra": m in ("percent", "fixed", "manual"), "method": True}
        for key, (lab, w) in self.pairs.items():
            lab.setVisible(show[key]); w.setVisible(show[key])
        self.extra_label.setText("المبلغ (دج)" if m in ("fixed", "manual") else "سقف متبقٍ (اختياري)")

    def data(self):
        label = self.label.text().strip()
        if not label:
            raise ValueError("أحد الاقتطاعات بلا اسم؛ اكتب اسمه أو احذفه")
        m = self.method.currentData()
        d = {"code": self.code, "label": label, "method": m, "enabled": self.enabled.isChecked(),
             "rate": parse_rate(self.rate.text(), f"نسبة «{label}»") if m == "percent" else None,
             "base": self.base.currentData() if m == "percent" else None,
             "scope": self.scope.currentData() if m == "percent" else None,
             "previous": non_negative(self.previous.text(), f"المقتطع سابقًا «{label}»") if m == "percent" else None}
        extra = non_negative(self.extra.text(), f"قيمة «{label}»") if m in ("percent", "fixed", "manual") else None
        d["amount" if m in ("fixed", "manual") else "remaining_cap"] = extra
        return d


class FinanceTab(QWidget):
    """الضرائب والاقتطاعات وطريقة الوضعية. زر الحفظ في أعلى الصفحة كي لا تحتاج للتمرير إليه."""
    def __init__(self, win):
        super().__init__(); self.win = win; self.cards = []
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(12)
        bar = QHBoxLayout()
        hint = QLabel("لا قيم افتراضية: كل ما يحدده العقد يُضبط هنا لكل مشروع. الوثائق الصادرة سابقًا لا تتأثر بأي تعديل.")
        hint.setObjectName("hint"); hint.setWordWrap(True); bar.addWidget(hint, 1)
        save = QPushButton("حفظ الإعدادات"); save.clicked.connect(self.save); bar.addWidget(save)
        root.addLayout(bar)

        box = QGroupBox("الضريبة وطريقة احتساب الوثائق"); form = QFormLayout(box); form.setVerticalSpacing(10)
        self.tva = QLineEdit(); self.tva.setPlaceholderText("مثال: 0.19 أو 19%")
        form.addRow("معدل TVA", self.tva)
        self.mode = combo(MODES); form.addRow("طريقة وضعية الأشغال", self.mode)
        self.tva_basis = combo([("ضريبة على كل عمود (العقد/النقصان/الزيادة)", "per_column"),
                                ("ضريبة على الصافي النهائي", "on_net")], "per_column")
        form.addRow("أساس TVA في الجرد", self.tva_basis)
        self.style_cb = combo([("ملخص مبسط (HT، TVA، TTC، الاقتطاعات، الصافي)", "simple"),
                               ("على نسق نموذج الوضعية: (1) (2) (3) ثم الاستردادات (4) والضمان (5) والصافي (6)", "form")], "simple")
        form.addRow("شكل ملخص الوضعية", self.style_cb)
        self.words = combo([("كما في النماذج: «… دينار جزائري و 84 سنتيم»", "form"),
                            ("صيغة رسمية: «فقط … لا غير»", "formal")], "form")
        form.addRow("صيغة المبلغ بالحروف", self.words)
        root.addWidget(box)

        ibox = QGroupBox("سياسة إدراج الزيادات في الإجمالي النهائي للجرد"); il = QVBoxLayout(ibox)
        t = QLabel("اختر الحالات التي تدخل في الإجمالي النهائي. عند عدم اختيار أي حالة، سيطلب البرنامج الحسم إذا وجدت زيادات غير محسومة أو مرفوضة.")
        t.setWordWrap(True); il.addWidget(t)
        ist = QHBoxLayout()
        self.increase_status_boxes = {"approved": QCheckBox("الزيادات المعتمدة"), "pending": QCheckBox("الزيادات غير المحسومة"),
                                      "rejected": QCheckBox("الزيادات المرفوضة")}
        for cb in self.increase_status_boxes.values():
            ist.addWidget(cb)
        ist.addStretch(); il.addLayout(ist); root.addWidget(ibox)

        dbox = QGroupBox("الاقتطاعات"); dl = QVBoxLayout(dbox); dl.setSpacing(10)
        self.cards_layout = QVBoxLayout(); self.cards_layout.setSpacing(10); dl.addLayout(self.cards_layout)
        row = QHBoxLayout()
        add = QPushButton("＋ إضافة اقتطاع"); add.setObjectName("secondary")
        menu = QMenu(add)
        for code, label in PRESETS:
            menu.addAction(label).triggered.connect(lambda _=False, c=code, l=label: self.add_card({"code": c, "label": l}))
        menu.addAction("اقتطاع آخر…").triggered.connect(lambda _=False: self.add_card({"label": ""}))
        add.setMenu(menu)
        row.addWidget(add); row.addStretch(); dl.addLayout(row)
        root.addWidget(dbox); root.addStretch()

    def _unique_code(self, wanted):
        used = {c.code for c in self.cards}
        if wanted and wanted not in used:
            return wanted
        n = 1
        while f"x{n}" in used or (wanted and f"{wanted}{n}" in used):
            n += 1
        return f"{wanted}{n}" if wanted else f"x{n}"

    def add_card(self, d):
        d = dict(d); d["code"] = self._unique_code(d.get("code"))
        card = DeductionCard(d, self.remove_card)
        self.cards.append(card); self.cards_layout.addWidget(card)
        return card

    def remove_card(self, card):
        self.cards.remove(card); self.cards_layout.removeWidget(card); card.setParent(None); card.deleteLater()

    def load(self, pid):
        ps = S.project_settings(self.win.conn, pid)
        self.tva.setText(str(ps.get("tva_rate") or ""))
        self.mode.setCurrentIndex(max(0, self.mode.findData(ps.get("situation_mode"))))
        self.tva_basis.setCurrentIndex(max(0, self.tva_basis.findData(ps.get("tva_basis") or "per_column")))
        self.style_cb.setCurrentIndex(max(0, self.style_cb.findData(ps.get("summary_style") or "simple")))
        self.words.setCurrentIndex(max(0, self.words.findData(ps.get("words_style") or "form")))
        for status, cb in self.increase_status_boxes.items():
            cb.setChecked(status in (ps.get("increase_statuses") or []))
        for card in list(self.cards):
            self.remove_card(card)
        for d in (ps.get("deductions") or [{"code": c, "label": l} for c, l in PRESETS[:2]]):
            self.add_card(d)

    def save(self):
        pid = self.win.pid
        if pid is None:
            return
        try:
            tva = parse_rate(self.tva.text(), "معدل TVA")
            ded = [c.data() for c in self.cards]
            ps = S.project_settings(self.win.conn, pid)
            ps.update({"tva_rate": tva, "situation_mode": self.mode.currentData(), "deductions": ded,
                       "summary_style": self.style_cb.currentData(), "tva_basis": self.tva_basis.currentData(),
                       "words_style": self.words.currentData(),
                       "increase_statuses": [s for s, cb in self.increase_status_boxes.items() if cb.isChecked()] or None})
            S.set_project_settings(self.win.conn, pid, ps)
        except Exception as e:
            QMessageBox.warning(self, "تعذر الحفظ", f"{e}"); return
        self.win.statusBar().showMessage("حُفظت الإعدادات المالية", 4000)
        self.win.refresh_docs()
        QMessageBox.information(self, "تم", "حُفظت الإعدادات. الوثائق الصادرة سابقًا لم تتأثر.")
