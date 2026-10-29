"""يُشغّل فحوص الواجهة المتاحة دون PySide6 حقيقي ضمن unittest: الفحص الساكن + اختبار الدخان + فحص QSS."""
import os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UiChecks(unittest.TestCase):
    def run_script(self, name):
        r = subprocess.run([sys.executable, os.path.join("tests", name)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_static_names_and_attributes(self):
        self.assertIn("لا مشكلات", self.run_script("static_ui_check.py"))

    def test_smoke_and_stylesheet(self):
        self.assertIn("UI smoke OK", self.run_script("ui_smoke.py"))


def _palette(name):
    import re
    src = open(os.path.join(ROOT, "ui", "design.py"), encoding="utf-8").read()
    block = src[src.index(f"{name} = dict("):]
    return dict(re.findall(r"(\w+)='(#[0-9A-Fa-f]{6})'", block[:block.index("\n)")]))


def _contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class LayoutRules(unittest.TestCase):
    def src(self, name):
        with open(os.path.join(ROOT, "ui", name), encoding="utf-8") as fh:
            return fh.read()

    def test_no_top_menu_bar(self):
        self.assertNotIn("menuBar", self.src("main_window.py"))

    def test_dates_and_contract_numbers_are_direction_protected(self):
        self.assertIn("ltr_marks", self.src("doc_center.py"))
        mw = self.src("main_window.py")
        self.assertIn("ltr_marks(p['contract_no'])", mw)
        self.assertIn("ltr_marks(r['contract_no'])", mw)

    def test_project_documents_tab_scrolls_instead_of_squeezing(self):
        self.assertIn("QScrollArea", self.src("docs_tab.py"))


class Polish(unittest.TestCase):
    def src(self, name):
        with open(os.path.join(ROOT, "ui", name), encoding="utf-8") as fh:
            return fh.read()

    def test_transitions_are_wired(self):
        mw = self.src("main_window.py")
        for needle in ("FadeTabs()", "windowOpacity", "self.grab()", "ScrollPerPixel"):
            self.assertIn(needle, mw)
        self.assertIn("HoverCard", self.src("docs_tab.py"))
        self.assertIn("QTimer.singleShot(70 * i", self.src("home_pages.py"))

    def test_checkbox_tick_icon_is_generated_and_used(self):
        d = self.src("design.py")
        self.assertIn("'check': ('check'", d)
        self.assertIn("image: url(@ico_check@)", d)

    def test_font_download_validation_rejects_html_and_truncated_files(self):
        sys.path.insert(0, os.path.join(ROOT, "fonts"))
        import download_fonts as d
        self.assertFalse(d.is_font(b"<html>" + b"x" * 30000))
        self.assertFalse(d.is_font(b"OTTO" + b"x" * 100))
        self.assertTrue(d.is_font(b"\x00\x01\x00\x00" + b"x" * 30000))


class PaletteContrast(unittest.TestCase):
    def test_white_text_on_buttons_and_header_is_readable_in_both_themes(self):
        for name in ("LIGHT", "DARK"):
            P = _palette(name)
            for key in ("primary", "accent", "hero_b", "hero_c", "danger", "danger2", "success", "success2"):
                self.assertGreaterEqual(_contrast("#FFFFFF", P[key]), 4.0, f"{name}.{key}")

    def test_body_text_is_readable_in_both_themes(self):
        for name in ("LIGHT", "DARK"):
            P = _palette(name)
            self.assertGreaterEqual(_contrast(P["text"], P["surface"]), 7.0, name)
            self.assertGreaterEqual(_contrast(P["text_muted"], P["surface"]), 4.5, name)
            self.assertGreaterEqual(_contrast(P["primary_dark"], P["primary_soft"]), 4.5, name)


if __name__ == "__main__":
    unittest.main()
