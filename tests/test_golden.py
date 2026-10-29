"""اختبارات «ذهبية»: أرقام مأخوذة حرفيًا من الوثائق الممسوحة الأصلية. إن فشل أحدها فالبرنامج لا يطابق النماذج."""
import json, os, tempfile, unittest
from decimal import Decimal as Dm

from worksapp import storage as S, services as SV, export as E
from worksapp.inventory import compute_inventory
from worksapp.numwords import amount_in_words as W, integer_in_words
from worksapp.qtyfmt import format_qty as FQ, unit_kind
from tests.test_export import Export, doc_text

NB = "\u00a0"

# (رقم، وحدة، كمية العقد، سعر، نقصان، زيادة | مبلغ العقد، مبلغ النقصان، مبلغ الزيادة، المبلغ الكلي) — من «الجرد العام والنهائي»
INV = {
    "الأشغال الكبرى": [  # القسم 1: المجموع الفرعي 1 786 000.00 / 35 535.00 / 3 960.00 / 1 754 425.00
        ("1.01", "و", "1", 50000, 0, 0, 50000, 0, 0, 50000),
        ("1.02", "م3", "1.5", 10000, "0.225", 0, 15000, 2250, 0, 12750),
        ("1.03", "م3", "1.5", 10000, "0.137", 0, 15000, 1370, 0, 13630),
        ("1.04", "م3", "9", 29000, "0.364", 0, 261000, 10556, 0, 250444),
        ("1.05", "م2", "55", 300, 0, "13.2", 16500, 0, 3960, 20460),
        ("1.06", "م2", "55", 3000, 0, 0, 165000, 0, 0, 165000),
        ("1.07", "م3", "11", 28000, 0, 0, 308000, 0, 0, 308000),
        ("1.08", "م2", "55", 3500, 0, 0, 192500, 0, 0, 192500),
        ("1.09", "م2", "70", 2000, 0, 0, 140000, 0, 0, 140000),
        ("1.10", "م2", "55", 1400, 0, 0, 77000, 0, 0, 77000),
        ("1.11", "م2", "190", 850, "8.24", 0, 161500, 7004, 0, 154496),
        ("1.12", "م2", "50", 800, "1.79", 0, 40000, 1432, 0, 38568),
        ("1.13", "م2", "20", 900, 0, 0, 18000, 0, 0, 18000),
        ("1.14", "م2", "120", 1000, "8.62", 0, 120000, 8620, 0, 111380),
        ("1.15", "م2", "55", 1600, "1.33", 0, 88000, 2128, 0, 85872),
        ("1.16", "م/ط", "70", 750, "2.9", 0, 52500, 2175, 0, 50325),
        ("1.17", "م2", "30", 2200, 0, 0, 66000, 0, 0, 66000),
    ],
    "المساحة": [  # القسم 2: 239 700.00
        ("2.01", "م2", "61", 1500, 0, 0, 91500, 0, 0, 91500), ("2.02", "م2", "61", 300, 0, 0, 18300, 0, 0, 18300),
        ("2.03", "م2", "61", 500, 0, 0, 30500, 0, 0, 30500), ("2.04", "م2", "61", 1200, 0, 0, 73200, 0, 0, 73200),
        ("2.05", "م2", "61", 200, 0, 0, 12200, 0, 0, 12200), ("2.06", "مط", "14", 1000, 0, 0, 14000, 0, 0, 14000),
    ],
    "شبكة الغاز": [  # القسم 7: 149 000.00 / 7 250.00 / 141 750.00
        ("7.01", "مط", "30", 2000, "1.5", 0, 60000, 3000, 0, 57000), ("7.02", "مط", "15", 3000, "1", 0, 45000, 3000, 0, 42000),
        ("7.03", "مط", "10", 2500, "0.5", 0, 25000, 1250, 0, 23750), ("7.04", "مط", "3", 3000, 0, 0, 9000, 0, 0, 9000),
        ("7.05", "مط", "5", 2000, 0, 0, 10000, 0, 0, 10000),
    ],
    "الطلاء": [  # القسم 8: 139 500.00 / 8 980.00 / 130 520.00
        ("8.01", "م2", "65", 500, "9.72", 0, 32500, 4860, 0, 27640), ("8.02", "م2", "20", 600, 0, 0, 12000, 0, 0, 12000),
        ("8.03", "م2", "190", 500, "8.24", 0, 95000, 4120, 0, 90880),
    ],
    "التهيئة": [  # القسم 9: 130 550.00 / 5 740.00 / 31 050.00 / 155 860.00
        ("9.01", "م/ط", "40", 820, "7", 0, 32800, 5740, 0, 27060), ("9.02", "م2", "85", 1150, 0, "27", 97750, 0, 31050, 128800),
    ],
}
SUBTOTALS = {"الأشغال الكبرى": (1786000, 35535, 3960, 1754425), "المساحة": (239700, 0, 0, 239700),
             "شبكة الغاز": (149000, 7250, 0, 141750), "الطلاء": (139500, 8980, 0, 130520),
             "التهيئة": (130550, 5740, 31050, 155860)}


class NumWords(unittest.TestCase):
    def test_exact_phrases_from_scans(self):
        self.assertEqual(W("9333403.84"), "تسعة ملايين وثلاثمائة وثلاثة وثلاثون ألف وأربعمائة وثلاثة دينار جزائري و 84 سنتيم")
        self.assertEqual(W("3799021.45"), "ثلاثة ملايين وسبعمائة وتسعة وتسعون ألف وواحد وعشرون دينار جزائري و 45 سنتيم")

    def test_edges(self):
        self.assertEqual(W(0), "صفر دينار جزائري")
        self.assertEqual(W(1), "دينار جزائري واحد")
        self.assertEqual(W(200), "مائتا دينار جزائري")
        self.assertEqual(W(202), "مائتان واثنان دينار جزائري")
        self.assertEqual(W(3000), "ثلاثة آلاف دينار جزائري")
        self.assertEqual(W(11000), "أحد عشر ألف دينار جزائري")
        self.assertEqual(W(2000000), "مليونا دينار جزائري")
        self.assertEqual(W("1002003.07"), "مليون وألفان وثلاثة دينار جزائري و 07 سنتيم")
        self.assertEqual(W("100.005"), "مائة دينار جزائري و 01 سنتيم")        # HALF_UP كسياسة التطبيق
        self.assertIsNone(W(None))
        with self.assertRaises(ValueError):
            W("-5")
        self.assertEqual(integer_in_words(12), "اثنا عشر")


class QtyFormat(unittest.TestCase):
    def test_unit_kinds(self):
        for u, k in (("م3", "m3"), ("م 3", "m3"), ("م³", "m3"), ("م2", "m2"), ("م/ط", "ml"), ("م ط", "ml"), ("مط", "ml"),
                     ("و", "count"), ("ج", "count"), ("كغ", "other"), (None, "other")):
            self.assertEqual(unit_kind(u), k, u)

    def test_forms_seen_in_scans(self):
        self.assertEqual(FQ("15", "و", "hawsala"), "15")
        self.assertEqual(FQ("1", "ج", "hawsala"), "01")
        self.assertEqual(FQ("0", "و", "situation"), "00")
        self.assertEqual(FQ("645", "مط", "hawsala"), "645.00")
        self.assertEqual(FQ("12", "م3", "hawsala"), "12")
        self.assertEqual(FQ("12", "م3", "bayan"), "12.000")
        self.assertEqual(FQ("1.275", "م3", "inventory"), "1.275")
        self.assertEqual(FQ("68.2", "م2", "inventory"), "68.20")
        self.assertEqual(FQ(None, "م2", "inventory"), "—")

    def test_never_hides_precision(self):
        self.assertEqual(FQ("1.363", "م2", "inventory"), "1.363")      # لا يُقرَّب إلى 1.36
        self.assertEqual(FQ("2.5", "و", "hawsala"), "2.50")             # عدد غير صحيح لا يُحشى كصحيح

    def test_project_override(self):
        self.assertEqual(FQ("12", "م3", "hawsala", {"hawsala": {"m3": "dec3"}}), "12.000")


class InventoryGolden(unittest.TestCase):
    def test_rows_and_subtotals_match_scan(self):
        items = []
        for sec, rows in INV.items():
            for code, unit, cq, price, dec, inc, *_ in rows:
                items.append({"code": code, "section": sec, "unit": unit, "price": str(price), "contract_qty": cq,
                              "decrease": str(dec), "increases": [{"qty": str(inc), "status": "approved"}] if inc else []})
        res = compute_inventory(items, "0.19", ["approved"])
        got = {r["code"]: r for r in res["rows"]}
        sub = {s: [Dm(0)] * 4 for s in INV}
        for sec, rows in INV.items():
            for code, _u, _q, _p, _d, _i, ca, da, ia, fin in rows:
                r = got[code]
                self.assertEqual(r["contract_amount"], Dm(ca), code)
                self.assertEqual(r["decrease_amount"], Dm(da), code)
                self.assertEqual(r["increase_amount_by_status"]["approved"], Dm(ia), code)
                self.assertEqual(r["contract_amount"] - r["decrease_amount"] + r["increase_amount_by_status"]["approved"], Dm(fin), code)
                for k, v in enumerate((ca, da, ia, fin)):
                    sub[sec][k] += Dm(v)
        for sec, exp in SUBTOTALS.items():
            self.assertEqual(tuple(sub[sec]), tuple(Dm(x) for x in exp), sec)

    def test_column_tva_matches_scan_page3(self):
        # الأعمدة الكلية في الجرد: 3 225 010.00 / 67 565.00 / 35 010.00 → TVA 19% لكل عمود
        for ht, tva in ((3225010, "612751.90"), (67565, "12837.35"), (35010, "6651.90"), (3192455, "606566.45")):
            self.assertEqual((Dm(ht) * Dm("0.19")).quantize(Dm("0.01")), Dm(tva))
        self.assertEqual(Dm("3837761.90") - Dm("80402.35") + Dm("41661.90"), Dm("3799021.45"))


class DocFields(unittest.TestCase):
    setUp = Export.setUp
    situation = Export.situation

    def _export(self, d, name):
        p = os.path.join(self.dir, name); E.export_docx(self.c, d, p); return doc_text(p).replace("\u200e", "")

    def test_situation_words_date_place_and_legal(self):
        S.update_project_extra(self.c, self.pid, manager="بكاري", place="الوادي", wilaya="الوادي", nif="002539054556904",
                               contract_amount=f"11{NB}673{NB}305.00")
        d = self.situation(); S.set_doc_config(self.c, d, date="2026-03-31")
        t = self._export(d, "s.docx")
        self.assertIn("تسعة ملايين وثلاثمائة وثلاثة وثلاثون ألف وأربعمائة وثلاثة دينار جزائري و 84 سنتيم", t)
        self.assertIn("بتاريخ: 2026-03-31", t)
        self.assertIn("الوادي في: 2026-03-31", t)
        self.assertIn("الرقم الجبائي: 002539054556904", t)
        self.assertIn("ولاية الوادي", t)

    def test_unfilled_legal_fields_are_not_invented(self):
        t = self._export(self.situation(), "s2.docx")
        for label in ("السجل التجاري", "الرقم الجبائي", "رقم المادة", "رقم الحساب البنكي", "مبلغ العقد"):
            self.assertNotIn(label, t)
        self.assertNotIn("التاريخ:", t); self.assertNotIn("الوادي في", t)       # لا سطر مكان/تاريخ لم يُدخل

    def test_inventory_sentence_uses_final_ttc(self):
        S.set_project_settings(self.c, self.pid, {**S.project_settings(self.c, self.pid), "increase_statuses": ["approved"]})
        inv = SV.create_draft(self.c, self.pid, "inventory")
        t = self._export(inv, "i.docx")
        self.assertIn("أوقف هذا الجرد على مبلغ بكامل الرسوم قدره:", t)
        self.assertIn("تسعة ملايين وثلاثمائة وثلاثة وثلاثون ألف وأربعمائة وثلاثة دينار جزائري و 84 سنتيم", t)

    def test_issued_doc_config_is_frozen(self):
        d = self.situation(); S.set_doc_config(self.c, d, date="2026-03-31"); SV.issue(self.c, d, explicit_approval=True)
        with self.assertRaises(ValueError):
            S.set_doc_config(self.c, d, date="2026-04-01")
        self.assertIn("2026-03-31", self._export(d, "f.docx"))

    def test_hawsala_counts_padded(self):
        h = SV.create_draft(self.c, self.pid, "hawsala")
        pl = json.loads(S.get_document(self.c, h)["payload_json"]); pl["rows"]["05"].update({"prev": "0", "period": "1"})
        S.update_draft_payload(self.c, h, pl)
        t = self._export(h, "h.docx")
        self.assertIn("\n01\n", t); self.assertIn("\n00\n", t)


if __name__ == "__main__":
    unittest.main()
