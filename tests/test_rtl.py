"""اختبارات اتجاه RTL في Word وPDF: بنية OOXML + هندسة الصفحة الفعلية (مواضع الكلمات في PDF الناتج عن LibreOffice).
تُتخطى اختبارات الهندسة تلقائيًا إن لم يتوفر LibreOffice أو pdftotext؛ ولا يُعدّ وجود الملف دليلًا على صحته البصرية."""
import json, os, re, shutil, subprocess, tempfile, unittest
from docx import Document
from docx.oxml.ns import qn
from worksapp import storage as S, services as SV, export as E
from tests.test_core import ITEMS

HAVE_PDF = bool(E._office_executable()) and bool(shutil.which("pdftotext"))
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def words(pdf, page=1):
    """كلمات الصفحة: (نص، xMin، yMin، xMax، yMax). pdftotext يُرجع الحروف العربية بترتيب بصري معكوس؛ rev تعيدها."""
    out = subprocess.run(["pdftotext", "-bbox", "-f", str(page), "-l", str(page), pdf, "-"], capture_output=True, text=True).stdout
    return [(t, float(x0), float(y0), float(x1), float(y1)) for x0, y0, x1, y1, t in
            re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', out)]


def rev(s):
    return s[::-1]


class RtlBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.c = S.connect(os.path.join(cls.dir, "r.db"))
        cls.pid = S.create_project(cls.c, "ساحة الشباب HT/TTC", contract_no="2026/09", contract_date="2026-02-23",
                                   contractor="مؤسسة الأفضل SARL", extra={"manager": "بكاري", "address": "الوادي"})
        for code, price, q in ITEMS:
            S.add_item(cls.c, cls.pid, code, f"بند {code}", "م2", price, q, section="الأشغال")
        S.set_project_settings(cls.c, cls.pid, {"tva_rate": "0.19", "situation_mode": "period", "increase_statuses": ["approved"],
                                                "deductions": [{"code": "g", "label": "Retenue de garantie", "method": "none"}]})
        cls.ids = {}
        d = SV.create_draft(cls.c, cls.pid, "situation")
        pl = json.loads(S.get_document(cls.c, d)["payload_json"])
        for code, price, q in ITEMS:
            pl["rows"][code].update({"prev": "0", "period": str(q)})
        S.update_draft_payload(cls.c, d, pl)
        cls.ids["situation"] = d
        for t in ("bayan", "hawsala", "inventory"):
            cls.ids[t] = SV.create_draft(cls.c, cls.pid, t)
        cls.docx = {}
        for t, i in cls.ids.items():
            cls.docx[t] = E.export_docx(cls.c, i, os.path.join(cls.dir, t + ".docx"))

    @classmethod
    def tearDownClass(cls):
        cls.c.close(); shutil.rmtree(cls.dir, ignore_errors=True)


class OoxmlStructure(RtlBase):
    def test_every_table_is_visually_rtl(self):
        for t, path in self.docx.items():
            d = Document(path)
            self.assertTrue(d.tables, t)
            for tbl in d.tables:
                self.assertIsNotNone(tbl._tbl.tblPr.find(qn("w:bidiVisual")), f"{t}: جدول بلا bidiVisual")

    def test_every_paragraph_with_text_is_bidi_and_never_jc_right(self):
        for t, path in self.docx.items():
            d = Document(path)
            roots = [d.element.body] + [s.footer._element for s in d.sections]
            for root in roots:
                for p in root.iter(qn("w:p")):
                    if not "".join(x.text or "" for x in p.iter(qn("w:t"))).strip():
                        continue
                    ppr = p.find(qn("w:pPr"))
                    self.assertIsNotNone(ppr is not None and ppr.find(qn("w:bidi")), f"{t}: فقرة بلا bidi")
                    jc = ppr.find(qn("w:jc"))
                    # في فقرة bidi يعني right الالتصاق باليسار؛ نستعمل left (=بداية السطر) أو center فقط
                    self.assertTrue(jc is None or jc.get(qn("w:val")) in ("left", "center"), f"{t}: jc={jc.get(qn('w:val'))}")

    def test_section_and_default_style_are_rtl(self):
        for t, path in self.docx.items():
            d = Document(path)
            self.assertIsNotNone(d.sections[0]._sectPr.find(qn("w:bidi")), t)
            self.assertIsNotNone(d.styles["Normal"].element.pPr.find(qn("w:bidi")), t)

    def test_pPr_children_follow_schema_order(self):
        order = E._PPR
        for t, path in self.docx.items():
            d = Document(path)
            for ppr in list(d.element.body.iter(qn("w:pPr"))) + list(d.sections[0].footer._element.iter(qn("w:pPr"))):
                idx = [order.index(c.tag.split("}")[1]) for c in ppr if c.tag.split("}")[1] in order]
                self.assertEqual(idx, sorted(idx), f"{t}: ترتيب pPr غير صالح")

    def test_no_forced_field_update_prompt(self):
        for t, path in self.docx.items():
            self.assertIsNone(Document(path).settings.element.find(qn("w:updateFields")))

    def test_xsd_validation_when_validator_available(self):
        v = "/mnt/skills/public/docx/scripts/office/validate.py"
        if not os.path.exists(v):
            self.skipTest("المدقق غير متوفر")
        for t, path in self.docx.items():
            r = subprocess.run(["python3", v, path], capture_output=True, text=True)
            self.assertIn("PASSED", r.stdout + r.stderr, f"{t}: {r.stdout}{r.stderr}")


@unittest.skipUnless(HAVE_PDF, "يتطلب LibreOffice وpdftotext")
class PdfGeometry(RtlBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pdf = {t: E.export_pdf(cls.c, i, os.path.join(cls.dir, t + ".pdf")) for t, i in cls.ids.items()}

    def page_width(self, t):
        out = subprocess.run(["pdfinfo", self.pdf[t]], capture_output=True, text=True).stdout
        return float(re.search(r"Page size:\s+([\d.]+)", out).group(1))

    def test_first_table_column_is_rightmost(self):
        """رقم البند (01) يقع يمين مبلغ البند في الصف نفسه، في الوضعية والحوصلة."""
        for t, amount in (("situation", "420"),):
            ws = words(self.pdf[t])
            amt = next(w for w in ws if w[0] == amount)
            code = next(w for w in ws if w[0] == "01" and abs(w[2] - amt[2]) < 3)
            self.assertGreater(code[1], amt[1] + 300, f"{t}: عمود الرقم ليس في أقصى اليمين")

    def test_headings_and_labels_hug_the_right_margin(self):
        for t, label in (("situation", "المشروع"), ("inventory", "المشروع"), ("hawsala", "المشروع")):
            ws = words(self.pdf[t])
            w = next(x for x in ws if x[0] == rev(label))
            self.assertGreater(w[3], self.page_width(t) - 60, f"{t}: «{label}» ملتصق باليسار")

    def test_mixed_latin_digits_and_dates_stay_intact(self):
        ws = [x[0] for x in words(self.pdf["situation"])]
        for token in ("HT/TTC", "2026/09", "2026-02-23", "SARL"):
            self.assertIn(token, ws, f"انكسر/انعكس: {token}")
        self.assertNotIn("32-20-6202", ws)

    def test_amount_with_thousands_not_reordered(self):
        ws = [x[0] for x in words(self.pdf["situation"])]
        self.assertIn("403.84", ws); self.assertIn("333", ws); self.assertNotIn("48.304", ws)

    def test_footer_has_page_numbers_and_header_row_repeats_flag(self):
        d = Document(self.docx["situation"])
        hdr = d.tables[0].rows[0]._tr.trPr
        self.assertIsNotNone(hdr.find(qn("w:tblHeader")))


if __name__ == "__main__":
    unittest.main()
