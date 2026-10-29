import os, sqlite3, tempfile, unittest, json, shutil
from decimal import Decimal as Dm
from worksapp.money import D, q3, q2, fmt
from worksapp import storage as S, alerts as A
from worksapp.formulas import Formula, MissingInput, FormulaError, validate_expr, BUILTIN_FORMULAS
from worksapp.quantities import item_quantity, resolve_period_cumulative, detect_conflict
from worksapp.situation import compute_situation, default_deductions
from worksapp.inventory import compute_inventory

F = {f.code: f for f in BUILTIN_FORMULAS}
F["mult3"] = Formula("mult3", "جداء", "a*b*c", [{"name": n, "label": n, "default": None} for n in "abc"])

# بنود 06 من بيان الأشغال: (عدد، طول، عرض، ارتفاع)
BAYAN_06 = [(15, "2.15", ".25", ".60"), (15, "2.15", ".15", ".10"), (9, "2.15", ".25", ".60"), (9, "2.15", ".15", ".10"),
            (2, "2.18", ".25", ".63"), (2, "2.18", ".15", ".10"), (1, "1.65", ".25", ".60"), (1, "1.65", ".15", ".10"),
            (1, "2.75", ".25", ".60"), (1, "2.75", ".15", ".10"), (4, "2.75", ".25", ".60"), (4, "2.75", ".15", ".10"),
            (1, "1.17", ".25", ".60"), (1, "1.17", ".15", ".10")]


class Quantities(unittest.TestCase):
    def test_item06_no_early_rounding(self):
        lines = [("volume", dict(n=n, L=L, l=l, h=h), "") for n, L, l, h in BAYAN_06]
        r = item_quantity("measured", lines=lines, formulas=F)
        self.assertEqual(r.shown, Dm("12.000"))                    # كما في النموذج
        early = sum(q3(x) for x in r.line_results)                  # لو قُرّب كل سطر أولًا
        self.assertEqual(early, Dm("12.003"))                       # فرق يثبت أهمية الدقة الداخلية
        self.assertEqual(q3(r.line_results[0]), Dm("4.838"))        # 4.8375 -> 4.838 (HALF_UP)

    def test_item03_lines_and_total(self):
        r = item_quantity("measured", lines=[("length", dict(n=15, L=43), ""), ("mult3", dict(a=2, b=3, c=32), "")], formulas=F)
        self.assertEqual(r.shown, Dm("837.000"))

    def test_direct_and_missing(self):
        self.assertEqual(item_quantity("direct", direct="15").shown, Dm("15.000"))
        m = item_quantity("direct", direct=None)
        self.assertIsNone(m.final)                                  # لا صفر مفترض
        self.assertIn("QTY_MISSING", [p[0] for p in m.problems])

    def test_override_keeps_computed(self):
        r = item_quantity("measured", lines=[("length", dict(n=2, L="5"), "")], formulas=F, override="9.5", override_reason="قياس ميداني")
        self.assertEqual((r.computed, r.final, r.overridden), (Dm("10"), Dm("9.5"), True))

    def test_negative_line_info_and_missing_input(self):
        r = item_quantity("measured", lines=[("area", dict(n=1, L="0.12", l="-1"), "فتحة")], formulas=F)
        self.assertIn("NEGATIVE_LINE", [p[0] for p in r.problems])
        r2 = item_quantity("measured", lines=[("area", dict(n=1, L="2"), "x")], formulas=F)
        self.assertIsNone(r2.final)
        self.assertIn("LINE_INVALID", [p[0] for p in r2.problems])

    def test_formula_safety(self):
        for bad in ("__import__('os')", "a.b", "a**100", "a if b else c"):
            with self.assertRaises(Exception):
                validate_expr(bad, ["a", "b", "c"])

    def test_period_cumulative(self):
        a = resolve_period_cumulative("10", period="5")
        self.assertEqual(a["cumulative"], Dm("15"))
        b = resolve_period_cumulative("10", cumulative="17.5")
        self.assertEqual(b["period"], Dm("7.5"))
        self.assertIn("QTY_INCONSISTENT", [p[0] for p in resolve_period_cumulative("10", "5", "20")["problems"]])
        self.assertIn("PREV_MISSING", [p[0] for p in resolve_period_cumulative(None, "5")["problems"]])

    def test_conflict_item03(self):   # 837 (بيان) مقابل 645 (حوصلة/وضعية) كما في الملفات
        c = detect_conflict({"بيان الأشغال": "837", "وضعية الأشغال": "645", "حوصلة الأشغال": "645"})
        self.assertTrue(c["conflict"])
        self.assertFalse(detect_conflict({"a": "5", "b": "5.0004"})["conflict"])   # نفس القيمة عند 3 منازل


ITEMS = [("01", 28000, 15), ("02", 13000, 32), ("03", 2200, 645), ("05", 150000, 1), ("06", 70000, 12),
         ("09", 3500, 35), ("10", 1450000, 2), ("11", 633000, 2), ("13", 600, 280), ("14", 550, "257.63")]


def sit_items(prev=0):
    return [{"code": c, "price": p, "qty_prev": prev, "qty_period": q} for c, p, q in ITEMS]


class Situation(unittest.TestCase):
    def test_matches_original_form(self):
        r = compute_situation(sit_items(), {"mode": "period", "tva_rate": "0.19",
                                            "deductions": [{"code": "guarantee", "label": "g", "method": "none"}]})
        t = r["totals"]
        self.assertEqual(t["ht_period"], Dm("7843196.50"))
        self.assertEqual(t["tva_period"], Dm("1490207.34"))
        self.assertEqual(t["ttc_period"], Dm("9333403.84"))
        self.assertEqual(r["net"], Dm("9333403.84"))
        self.assertEqual(fmt(r["net"]), "9 333 403.84")

    def test_cumulative_mode_no_double_count(self):
        items = [{"code": "a", "price": 100, "qty_prev": 10, "qty_cum": 25}]
        r = compute_situation(items, {"mode": "cumulative", "tva_rate": "0.19", "deductions": []})
        self.assertEqual((r["totals"]["ht_cumulative"], r["totals"]["ht_previous"], r["totals"]["ht_period"]),
                         (Dm("2500"), Dm("1000"), Dm("1500")))

    def test_missing_data_is_not_zero(self):
        r = compute_situation([{"code": "a", "price": 100, "qty_prev": 0}], {"mode": "period", "tva_rate": None})
        self.assertIsNone(r["totals"]["ht_period"]); self.assertIsNone(r["net"])
        codes = {a.code for a in r["alerts"]}
        self.assertTrue({"QTY_MISSING", "TVA_INCOMPLETE", "NET_INCOMPLETE"} <= codes)

    def test_default_deductions_unconfigured_blocks_net(self):
        r = compute_situation(sit_items(), {"mode": "period", "tva_rate": "0.19", "deductions": default_deductions()})
        self.assertIsNone(r["net"])
        self.assertIn("DEDUCTION_INCOMPLETE", {a.code for a in r["alerts"]})

    def test_guarantee_cumulative_target_no_double(self):
        items = [{"code": "a", "price": 1000, "qty_prev": 1000, "qty_cum": 2000}]   # تراكمي 2,000,000
        g = {"code": "g", "label": "g", "method": "percent", "rate": "0.05", "base": "ht_cumulative",
             "scope": "cumulative_target", "previous": "60000"}
        r = compute_situation(items, {"mode": "cumulative", "tva_rate": "0.19", "deductions": [g]})
        self.assertEqual(r["deductions"][0]["amount"], Dm("40000.00"))       # 100,000 − 60,000

    def test_guarantee_per_situation_differs(self):
        items = [{"code": "a", "price": 1000, "qty_prev": 1000, "qty_cum": 2000}]
        g = {"code": "g", "label": "g", "method": "percent", "rate": "0.05", "base": "ht_period", "scope": "per_situation"}
        r = compute_situation(items, {"mode": "cumulative", "tva_rate": "0.19", "deductions": [g]})
        self.assertEqual(r["deductions"][0]["amount"], Dm("50000.00"))

    def test_advance_cap_policies(self):
        base = {"code": "adv", "label": "adv", "method": "percent", "rate": "0.10", "base": "ht_period",
                "scope": "per_situation", "remaining_cap": "50000"}
        items = [{"code": "a", "price": 1000, "qty_prev": 0, "qty_period": 1000}]
        warn = compute_situation(items, {"mode": "period", "tva_rate": "0.19", "deductions": [dict(base)]})
        self.assertEqual(warn["deductions"][0]["amount"], Dm("100000.00"))       # لا قص صامت
        self.assertIn("DEDUCTION_EXCEEDS_CAP", {a.code for a in warn["alerts"]})
        clamp = compute_situation(items, {"mode": "period", "tva_rate": "0.19", "deductions": [dict(base, cap_policy="clamp")]})
        self.assertEqual(clamp["deductions"][0]["amount"], Dm("50000.00"))

    def test_extra_deduction_does_not_change_others(self):
        g = {"code": "g", "label": "g", "method": "percent", "rate": "0.05", "base": "ht_period", "scope": "per_situation"}
        x = {"code": "x", "label": "اقتطاع إضافي", "method": "fixed", "amount": "5000"}
        a = compute_situation(sit_items(), {"mode": "period", "tva_rate": "0.19", "deductions": [g]})
        b = compute_situation(sit_items(), {"mode": "period", "tva_rate": "0.19", "deductions": [g, x]})
        self.assertEqual(a["deductions"][0]["amount"], b["deductions"][0]["amount"])
        self.assertEqual(a["net"] - b["net"], Dm("5000.00"))


class Inventory(unittest.TestCase):
    def test_decrease_increase_and_exceeds(self):
        rows = compute_inventory([
            {"code": "1.02", "price": 10000, "contract_qty": "1.5", "decrease": "0.225"},
            {"code": "1.05", "price": 300, "contract_qty": 55, "increases": [{"qty": "13.20", "status": "approved"}], "executed": "68.20"},
        ], tva_rate="0.19")
        r1, r2 = rows["rows"]
        self.assertEqual(r1["decrease_amount"], Dm("2250.00")); self.assertEqual(r1["final_approved"], Dm("1.275"))
        self.assertEqual(r2["increase_amount_by_status"]["approved"], Dm("3960.00"))
        self.assertIn("EXCEEDS_CONTRACT", {a.code for a in rows["alerts"]})
        self.assertEqual(r2["contract_amount"], Dm("16500.00"))               # الأصل لم يُستبدل

    def test_tva_per_column_matches_original_totals(self):
        items = [{"code": "A", "price": 3157445, "contract_qty": 1}, {"code": "B", "price": 67565, "contract_qty": 1, "decrease": 1},
                 {"code": "C", "price": 35010, "contract_qty": 0, "increases": [{"qty": 1, "status": "approved"}]}]
        t = compute_inventory(items, "0.19")["totals"]
        self.assertEqual(t["ht"]["contract"], Dm("3225010")); self.assertEqual(t["tva"]["contract"], Dm("612751.90"))
        self.assertEqual(t["tva"]["decrease"], Dm("12837.35")); self.assertEqual(t["tva"]["increase"], Dm("6651.90"))
        self.assertEqual(t["final_contractual_ttc"], Dm("3799021.45"))

    def test_invalid_rates_and_negative_inventory_values_block(self):
        r = compute_inventory([{"code": "A", "price": 100, "contract_qty": 10,
                                "decrease": -1, "increases": [{"qty": -2, "status": "approved"}]}],
                              tva_rate="19", include_statuses=["approved"])
        codes = {a.code for a in r["alerts"]}
        self.assertIn("TVA_INVALID", codes)
        self.assertIn("NEGATIVE_QTY", codes)
        A.apply_policy(r["alerts"], {"TVA_INVALID": "info", "NEGATIVE_QTY": "info"})
        self.assertEqual({a.severity for a in r["alerts"] if a.code in {"TVA_INVALID", "NEGATIVE_QTY"}}, {A.BLOCKING})

    def test_increase_statuses_not_merged(self):
        items = [{"code": "A", "price": 100, "contract_qty": 10, "increases": [
            {"qty": 2, "status": "approved"}, {"qty": 3, "status": "pending"}]}]
        r = compute_inventory(items, "0.19")
        self.assertIsNone(r["totals"]["final_contractual_ht"])
        self.assertIn("INCREASE_POLICY_UNSET", {a.code for a in r["alerts"]})
        h = r["totals"]["ht"]
        self.assertEqual((h["increase_registered"], h["increase_approved"], h["increase_pending"]), (Dm("500"), Dm("200"), Dm("300")))
        r2 = compute_inventory(items, "0.19", include_statuses=["approved"])
        self.assertEqual(r2["totals"]["final_contractual_ht"], Dm("1200"))


class Storage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.path = os.path.join(self.dir, "t.db")
        self.c = S.connect(self.path)
        self.pid = S.create_project(self.c, "إعادة الاعتبار لساحة الشباب", contract_no="2026/09", contract_date="2026-02-23")
        self.it = S.add_item(self.c, self.pid, "01", "عمود إنارة", "و", 28000, 15)

    def tearDown(self):
        try: self.c.close()
        except Exception: pass

    def test_persistence(self):
        self.c.close(); c2 = S.connect(self.path)
        try:
            self.assertEqual(S.list_items(c2, self.pid)[0]["code"], "01")
        finally:
            c2.close()

    def test_direct_creates_no_lines(self):
        S.set_direct_quantity(self.c, self.it, 15)
        self.assertEqual(S.count_measure_lines(self.c, self.it), 0)
        self.assertEqual(S.get_quantity(self.c, self.it).shown, Dm("15.000"))

    def test_measured_and_override_audit(self):
        S.add_measure_line(self.c, self.it, "length", dict(n=2, L="7.5"))
        S.add_measure_line(self.c, self.it, "length", dict(n=1, L="1.25"))
        self.assertEqual(S.get_quantity(self.c, self.it).shown, Dm("16.250"))
        S.set_override(self.c, self.it, "16", "تقريب ميداني")
        r = S.get_quantity(self.c, self.it)
        self.assertEqual((r.computed, r.final, r.overridden), (Dm("16.25"), Dm("16"), True))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM audit_log WHERE field='override_qty'").fetchone()[0], 1)

    def test_invalid_measurement_is_rejected_before_changing_approval(self):
        S.set_direct_quantity(self.c, self.it, 10)
        S.approve_quantity(self.c, self.it, 10, "بيان الأشغال", "قرار صحيح سابق")
        with self.assertRaises(Exception):
            S.add_measure_line(self.c, self.it, "length", {"n": 2})
        self.assertTrue(S.get_quantity(self.c, self.it).approved)
        self.assertEqual(S.count_measure_lines(self.c, self.it), 0)

    def test_manual_override_requires_a_calculated_base(self):
        with self.assertRaisesRegex(ValueError, "كمية مباشرة أو سطر قياس"):
            S.set_override(self.c, self.it, 5, "تصحيح")

    def test_measure_line_edit_delete_is_audited_and_recalculates(self):
        S.add_measure_line(self.c, self.it, "length", dict(n=2, L="5"))
        line = self.c.execute("SELECT id FROM measure_lines WHERE item_id=?", (self.it,)).fetchone()[0]
        S.approve_quantity(self.c, self.it, 10, "حوصلة الأشغال", "مطابقة محضر القياس")
        S.update_measure_line(self.c, line, "length", dict(n=2, L="6"), "العمود", "الموقع أ")
        q = S.get_quantity(self.c, self.it)
        self.assertEqual(q.final, Dm("12"))
        self.assertFalse(q.approved)
        S.delete_measure_line(self.c, line)
        q = S.get_quantity(self.c, self.it)
        self.assertIsNone(q.final)
        self.assertIn("QTY_MISSING", [p[0] for p in q.problems])
        actions = self.c.execute("SELECT COUNT(*) FROM audit_log WHERE entity='measure_line'").fetchone()[0]
        self.assertEqual(actions, 3)  # إضافة، تعديل، حذف

    def test_custom_formula(self):
        S.add_formula(self.c, "wall", "جدار بخصم", "n*(L*h-a)", [{"name": n, "label": n, "default": None} for n in ("n", "L", "h", "a")])
        S.add_measure_line(self.c, self.it, "wall", dict(n=1, L=10, h=3, a=2))
        self.assertEqual(S.get_quantity(self.c, self.it).shown, Dm("28.000"))
        with self.assertRaises(Exception):
            S.add_formula(self.c, "bad", "x", "__import__('os')", [])

    def test_numbering_independent_and_flexible(self):
        nums = []
        for t in ("situation", "situation", "hawsala", "inventory"):
            d = S.create_draft(self.c, self.pid, t)           # كل نوع دون الآخر (مرونة)
            nums.append((t, S.issue_document(self.c, d, [], {}, explicit_approval=True)))
        self.assertEqual(nums, [("situation", 1), ("situation", 2), ("hawsala", 1), ("inventory", 1)])

    def test_numbering_mode_draft(self):
        S.set_setting(self.c, "numbering_mode", "draft")
        d = S.create_draft(self.c, self.pid, "bayan")
        self.assertEqual(S.get_document(self.c, d)["number"], 1)

    def test_issue_requires_explicit_approval_and_blocks(self):
        d = S.create_draft(self.c, self.pid, "situation")
        with self.assertRaises(PermissionError):
            S.issue_document(self.c, d, [], {})
        with self.assertRaises(S.IssueBlocked):
            S.issue_document(self.c, d, [A.make("TVA_INCOMPLETE", "المشروع")], {}, explicit_approval=True)
        self.assertEqual(S.get_document(self.c, d)["status"], "draft")        # بقيت مسودة
        S.set_setting(self.c, "alert_severity", {"TVA_INCOMPLETE": "warning"})  # الشدّة قابلة للضبط
        S.issue_document(self.c, d, [A.make("TVA_INCOMPLETE", "المشروع")], {}, explicit_approval=True)
        self.assertEqual(S.get_document(self.c, d)["status"], "issued")

    def test_issued_is_frozen_and_correction_links(self):
        S.set_direct_quantity(self.c, self.it, 15)
        d = S.create_draft(self.c, self.pid, "situation", {"x": 1})
        S.issue_document(self.c, d, [], {"net": "9333403.84"}, explicit_approval=True)
        before = S.get_document(self.c, d)["snapshot_json"]
        S.update_item_price(self.c, self.it, 99999, "تعديل لاحق")
        S.update_project(self.c, self.pid, name="اسم جديد")
        self.assertEqual(S.get_document(self.c, d)["snapshot_json"], before)    # لم تتغير
        snap = json.loads(before)
        self.assertEqual(snap["state"]["items"][0]["unit_price"], "28000")       # السعر القديم محفوظ
        for sql in ("UPDATE documents SET payload_json='{}' WHERE id=?", "DELETE FROM documents WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.c.execute(sql, (d,))                                         # حتى SQL المباشر مرفوض
        with self.assertRaises(ValueError):
            S.create_correction(self.c, d, "")
        k = S.create_correction(self.c, d, "خطأ في كمية البند 03")
        kd = S.get_document(self.c, k)
        self.assertEqual((kd["parent_id"], kd["status"], kd["revision"], kd["number"]), (d, "draft", 1, 1))
        self.assertEqual(S.get_document(self.c, d)["status"], "issued")

    def test_backup_restore(self):
        d = S.create_draft(self.c, self.pid, "situation"); S.issue_document(self.c, d, [], {}, explicit_approval=True)
        bk = os.path.join(self.dir, "bk.db"); S.backup(self.c, bk)
        S.create_project(self.c, "مشروع بعد النسخة")
        self.c.close(); S.restore(bk, self.path); c2 = S.connect(self.path)
        try:
            self.assertEqual(c2.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
            self.assertEqual(S.get_document(c2, d)["status"], "issued")
        finally:
            c2.close()
        bad = os.path.join(self.dir, "bad.db")
        with open(bad, "wb") as fh:
            fh.write(b"not a db")
        with self.assertRaises(Exception):
            S.restore(bad, self.path)
        wrong_version = os.path.join(self.dir, "wrong-version.db")
        shutil.copy2(bk, wrong_version)
        badconn = sqlite3.connect(wrong_version)
        badconn.execute("UPDATE schema_info SET value='999' WHERE key='version'")
        badconn.commit(); badconn.close()
        with self.assertRaisesRegex(ValueError, "غير متوافق"):
            S.restore(wrong_version, self.path)

    def test_approve_quantity_needs_reason(self):
        with self.assertRaises(ValueError):
            S.approve_quantity(self.c, self.it, 645, "وضعية الأشغال", "")
        S.approve_quantity(self.c, self.it, 645, "وضعية الأشغال", "القياس الميداني")
        result = S.get_quantity(self.c, self.it)
        self.assertEqual(result.final, Dm("645"))
        self.assertEqual(result.approved_source, "وضعية الأشغال")
        S.set_direct_quantity(self.c, self.it, 17)
        changed = S.get_quantity(self.c, self.it)
        self.assertEqual(changed.final, Dm("17"))
        self.assertFalse(changed.approved)  # تعديل المصدر يلغي القرار القديم كي لا يُطبّق على بيانات جديدة


if __name__ == "__main__":
    unittest.main()


from worksapp import services as SV


class Services(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.c = S.connect(os.path.join(self.dir, "s.db"))
        self.pid = S.create_project(self.c, "ساحة الشباب", contract_no="2026/09", contract_date="2026-02-23",
                                    owner="البلدية", contractor="الأفضل")
        for code, price, cq in ITEMS:
            S.add_item(self.c, self.pid, code, f"بند {code}", "و", price, cq)
        S.set_project_settings(self.c, self.pid, {"tva_rate": "0.19", "situation_mode": "period",
                                                  "deductions": [{"code": "g", "label": "Retenue de garantie", "method": "percent",
                                                                  "rate": "0.05", "base": "ht_period", "scope": "per_situation",
                                                                  "enabled": False}]})

    def tearDown(self):
        try: self.c.close()
        except Exception: pass

    def fill(self, doc, field="period"):
        pl = json.loads(S.get_document(self.c, doc)["payload_json"])
        for code, price, q in ITEMS:
            pl["rows"][code].update({"prev": "0", field: str(q)})
        S.update_draft_payload(self.c, doc, pl)

    def test_situation_flow_and_guarantee_toggle(self):
        d = SV.create_draft(self.c, self.pid, "situation"); self.fill(d)
        c = SV.preview(self.c, d)
        self.assertEqual(c["results"]["net"], Dm("9333403.84"))          # الضمان غير مطبق صراحةً => 0.00
        self.assertEqual(SV.issue(self.c, d, explicit_approval=True), 1)
        # تفعيل الضمان للوضعية التالية: 5% على HT الفترة
        ps = S.project_settings(self.c, self.pid); ps["deductions"][0]["enabled"] = True
        S.set_project_settings(self.c, self.pid, ps)
        d2 = SV.create_draft(self.c, self.pid, "situation")
        pl = json.loads(S.get_document(self.c, d2)["payload_json"])
        self.assertEqual(pl["rows"]["01"]["prev"], "15")                  # السابق جُلب تلقائيًا من الصادرة
        for code, price, q in ITEMS:
            pl["rows"][code]["period"] = "1"
        S.update_draft_payload(self.c, d2, pl)
        self.assertEqual(SV.preview(self.c, d2)["results"]["deductions"][0]["amount"],
                         Dm(str(sum(D(p) for _, p, _ in ITEMS) * Dm("0.05"))).quantize(Dm("0.01")))

    def test_hawsala_shows_only_executed_and_no_assumed_zero(self):
        d = SV.create_draft(self.c, self.pid, "hawsala")
        pl = json.loads(S.get_document(self.c, d)["payload_json"])
        pl["rows"]["01"].update({"prev": "0", "period": "15"})
        S.update_draft_payload(self.c, d, pl)
        r = SV.preview(self.c, d)["results"]
        self.assertEqual([x["code"] for x in r["rows"]], ["01"])
        self.assertEqual(len(r["items_without_data"]), 9)

    def test_conflict_blocks_issue_until_decided(self):
        i3 = [i for i in S.list_items(self.c, self.pid) if i["code"] == "03"][0]["id"]
        S.add_measure_line(self.c, i3, "length", dict(n=15, L=43))
        S.add_measure_line(self.c, i3, "length", dict(n=6, L=32))     # بيان: 837
        h = SV.create_draft(self.c, self.pid, "hawsala")
        pl = json.loads(S.get_document(self.c, h)["payload_json"])
        pl["rows"]["03"].update({"prev": "0", "cum": "645"})
        S.update_draft_payload(self.c, h, pl)
        b = SV.create_draft(self.c, self.pid, "bayan")
        codes = {a.code for a in SV.preview(self.c, b)["alerts"]}
        self.assertIn("QTY_CONFLICT_UNRESOLVED", codes)
        with self.assertRaises(S.IssueBlocked):
            SV.issue(self.c, b, explicit_approval=True)
        choices = SV.quantity_conflicts(self.c, self.pid)
        item_choice = next(x for x in choices if x["code"] == "03")
        self.assertEqual(item_choice["values"]["بيان الأشغال"], Dm("837.000"))
        S.approve_quantity(self.c, i3, 645, "وضعية الأشغال", "القياس الميداني")
        approved = S.get_quantity(self.c, i3)
        self.assertEqual(approved.final, Dm("645"))
        self.assertTrue(approved.approved)
        self.assertEqual(approved.approved_source, "وضعية الأشغال")
        self.assertNotIn("QTY_CONFLICT_UNRESOLVED", {a.code for a in SV.preview(self.c, b)["alerts"]})
        self.assertEqual(SV.issue(self.c, b, explicit_approval=True), 1)

    def test_payload_change_invalidates_old_quantity_approval(self):
        item_id = next(i["id"] for i in S.list_items(self.c, self.pid) if i["code"] == "01")
        S.set_direct_quantity(self.c, item_id, 15)
        h = SV.create_draft(self.c, self.pid, "hawsala")
        pl = json.loads(S.get_document(self.c, h)["payload_json"])
        pl["rows"]["01"].update({"prev": "0", "cum": "15"})
        S.update_draft_payload(self.c, h, pl)
        S.approve_quantity(self.c, item_id, 15, "حوصلة الأشغال", "مقارنة مع المصدر")
        self.assertTrue(S.get_quantity(self.c, item_id).approved)
        pl["rows"]["01"]["cum"] = "16"
        S.update_draft_payload(self.c, h, pl)
        self.assertFalse(S.get_quantity(self.c, item_id).approved)
        self.assertEqual(S.get_quantity(self.c, item_id).final, Dm("15"))
        self.assertIn("أُلغي القرار السابق", self.c.execute(
            "SELECT reason FROM audit_log WHERE entity='item_quantity' AND field='approved_qty' ORDER BY id DESC LIMIT 1").fetchone()[0])

    def test_empty_statement_cannot_be_issued(self):
        d = SV.create_draft(self.c, self.pid, "bayan")
        preview = SV.preview(self.c, d)
        alert = next(a for a in preview["alerts"] if a.code == "DOCUMENT_EMPTY")
        self.assertEqual(alert.severity, A.BLOCKING)
        S.set_setting(self.c, "alert_severity", {"DOCUMENT_EMPTY": "info"})
        with self.assertRaises(S.IssueBlocked):
            SV.issue(self.c, d, explicit_approval=True)

    def test_issued_preview_uses_frozen_snapshot(self):
        d = SV.create_draft(self.c, self.pid, "situation")
        self.fill(d)
        before = SV.preview(self.c, d)["results"]["net"]
        SV.issue(self.c, d, explicit_approval=True)
        item_id = next(i["id"] for i in S.list_items(self.c, self.pid) if i["code"] == "01")
        S.update_item_price(self.c, item_id, 1, "تعديل لاحق بعد الإصدار")
        preview = SV.preview(self.c, d)
        self.assertEqual(D(preview["results"]["net"]), before)
        self.assertEqual(preview["snapshot"]["state"]["items"][0]["unit_price"], "28000")
        self.assertEqual(preview["view"][1][0][2], "28 000.00")

    def test_inventory_view_and_overview(self):
        d = SV.create_draft(self.c, self.pid, "inventory")
        pl = json.loads(S.get_document(self.c, d)["payload_json"])
        pl["rows"]["01"].update({"decrease": "2", "increase": "1", "increase_status": "pending"})
        S.update_draft_payload(self.c, d, pl)
        c = SV.preview(self.c, d)
        self.assertIn("INCREASE_PENDING", {a.code for a in c["alerts"]})
        self.assertEqual(SV.documents_overview(self.c, self.pid)["inventory"]["docs"][0]["status"], "draft")


from worksapp.money import normalize_number


class ItemsEntry(unittest.TestCase):
    def setUp(self):
        self.c = S.connect(os.path.join(tempfile.mkdtemp(), "i.db")); self.pid = S.create_project(self.c, "م")

    def tearDown(self):
        try: self.c.close()
        except Exception: pass

    def test_number_parsing(self):
        for raw, want in (("28 000", "28000"), ("28\u00a0000,50", "28000.50"), ("١٥٫٥", "15.5"), ("1,234,567", "1234567"),
                          ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("0,60", "0.60"), ("١٢", "12")):
            self.assertEqual(D(raw), Dm(want), raw)
        with self.assertRaises(ValueError):
            D("abc")

    def test_paste_parse_and_bulk(self):
        txt = "رقم\tوصف\tوحدة\tسعر\tكمية\tفصل\n1.01\tحفر\tم3\t1 500,00\t12,5\tالأشغال\n1.02\tردم\tم3\t900\t8\n"
        rows, errs = SV.parse_items_text(self.c, self.pid, txt)
        self.assertEqual(errs, []); self.assertEqual(len(rows), 2)        # سطر العناوين تُجوهل
        self.assertEqual(rows[0]["price"], Dm("1500.00")); self.assertEqual(rows[0]["qty"], Dm("12.5"))
        S.add_items_bulk(self.c, self.pid, rows)
        self.assertEqual([i["code"] for i in S.list_items(self.c, self.pid)], ["1.01", "1.02"])

    def test_paste_errors_name_line_and_field_and_write_nothing(self):
        rows, errs = SV.parse_items_text(self.c, self.pid, "1\tأ\tو\t10\t5\n1\tب\tو\tx\t5\n3\tج\tو\t10\t-2")
        self.assertEqual(len(errs), 3)
        self.assertIn("السطر 2", errs[0]); self.assertTrue(any("سعر الوحدة" in e for e in errs)); self.assertTrue(any("سالب" in e or "الكمية" in e for e in errs))

    def test_inline_edit_delete_and_duplicate(self):
        a = S.add_item(self.c, self.pid, "01", "أ", "و", 10, 5); S.add_item(self.c, self.pid, "02", "ب", "و", 10, 5)
        S.update_item_field(self.c, a, "unit_price", "١٢٫٥"); self.assertEqual(S.list_items(self.c, self.pid)[0]["unit_price"], "12.5")
        with self.assertRaises(ValueError) as cm:
            S.update_item_field(self.c, a, "code", "02")
        self.assertIn("مستعمل", str(cm.exception))
        with self.assertRaises(ValueError):
            S.update_item_field(self.c, a, "contract_qty", "-1")
        with self.assertRaises(ValueError):
            S.update_item_field(self.c, a, "code", " ")
        S.delete_item(self.c, a); self.assertEqual([i["code"] for i in S.list_items(self.c, self.pid)], ["02"])

    def test_next_code(self):
        self.assertEqual(SV.next_item_code(self.c, self.pid), "01")
        S.add_item(self.c, self.pid, "01", "", None, None, None); S.add_item(self.c, self.pid, "07", "", None, None, None)
        self.assertEqual(SV.next_item_code(self.c, self.pid), "08")


class Migration(unittest.TestCase):
    def test_old_db_without_section_column_is_migrated(self):
        d = tempfile.mkdtemp(); path = os.path.join(d, "old.db")
        conn = S.connect(path)
        pid = S.create_project(conn, "قديم"); S.add_item(conn, pid, "01", "بند", "و", 100, 2)
        conn.commit()
        conn.execute("ALTER TABLE items DROP COLUMN section")      # يحاكي قاعدة أنشأتها نسخة أقدم
        conn.commit(); conn.close()
        conn = S.connect(path)                                      # الفتح يرحّل تلقائيًا
        S.add_item(conn, pid, "02", "", None, None, None)           # كان يفشل: no column named section
        S.add_item(conn, pid, "03", "x", "و", 1, 1, section="قسم")
        items = {i["code"]: i for i in S.list_items(conn, pid)}
        self.assertEqual(items["01"]["unit_price"], "100"); self.assertIsNone(items["01"]["section"])
        self.assertEqual(items["03"]["section"], "قسم")
        self.assertTrue(os.path.exists(path + ".before_migrate"))   # نسخة احتياطية قبل الترحيل
        self.assertEqual(S.migrate(conn, path), [])                 # idempotent

    def test_new_db_needs_no_migration(self):
        conn = S.connect(os.path.join(tempfile.mkdtemp(), "n.db"))
        self.assertEqual(S.migrate(conn), [])


class Deletion(unittest.TestCase):
    def setUp(self):
        self.c = S.connect(os.path.join(tempfile.mkdtemp(), "d.db"))
        self.pid = S.create_project(self.c, "م", contract_no="1")
        for code, price, q in (("01", 10, 2), ("02", 5, 4)):
            S.add_item(self.c, self.pid, code, "b", "و", price, q)
        self.d = SV.create_draft(self.c, self.pid, "hawsala")

    def test_delete_project_without_issued_removes_everything(self):
        self.assertEqual(S.delete_project(self.c, self.pid), (2, 1))
        for tbl in ("projects", "items", "documents", "doc_counters"):
            self.assertEqual(self.c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0], 0, tbl)

    def test_project_with_issued_document_cannot_be_deleted_but_can_be_archived(self):
        pl = json.loads(S.get_document(self.c, self.d)["payload_json"])
        for code in ("01", "02"):
            pl["rows"][code].update({"prev": "0", "period": "1"})
        S.update_draft_payload(self.c, self.d, pl)
        SV.issue(self.c, self.d, explicit_approval=True)
        with self.assertRaises(ValueError):
            S.delete_project(self.c, self.pid)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)      # لم يُحذف شيء
        S.archive_project(self.c, self.pid)
        self.assertEqual(self.c.execute("SELECT archived FROM projects WHERE id=?", (self.pid,)).fetchone()[0], 1)
        with self.assertRaises(ValueError):
            S.delete_draft(self.c, self.d)                                                      # الصادرة لا تُحذف

    def test_delete_draft(self):
        S.delete_draft(self.c, self.d)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)

    def test_old_db_gets_archived_column(self):
        path = os.path.join(tempfile.mkdtemp(), "o.db"); conn = S.connect(path)
        conn.execute("ALTER TABLE projects DROP COLUMN archived"); conn.commit(); conn.close()
        conn = S.connect(path)
        pid = S.create_project(conn, "x"); S.archive_project(conn, pid)
