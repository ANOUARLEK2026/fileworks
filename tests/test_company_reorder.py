import json, os, sqlite3, tempfile, unittest

from worksapp import storage as S, services as SV
from worksapp.money import D, fmt_ui, bidi_safe


def new_db():
    return S.connect(os.path.join(tempfile.mkdtemp(), "t.db"))


class CompanySeparation(unittest.TestCase):
    def setUp(self):
        self.c = new_db()

    def test_company_is_entered_once_and_shared_by_projects(self):
        cid = S.save_company(self.c, None, "مؤسسة الأفضل", manager="أحمد", place="الوادي", nif="123")
        p1 = S.create_project(self.c, "مشروع 1")
        p2 = S.create_project(self.c, "مشروع 2")
        self.assertEqual(S.company_for_project(self.c, p1)["id"], cid)
        self.assertEqual(S.company_for_project(self.c, p2)["manager"], "أحمد")
        S.save_company(self.c, cid, "مؤسسة الأفضل", manager="خالد", place="الوادي", nif="123")
        self.assertEqual(S.company_for_project(self.c, p2)["manager"], "خالد")   # تعديل واحد يصل كل المشاريع

    def test_project_alert_when_no_company(self):
        pid = S.create_project(self.c, "م")
        self.assertIn("الشركة المتعاقدة", " ".join(a.detail for a in SV.project_alerts(self.c, pid)))
        S.save_company(self.c, None, "ش")
        S.set_project_company(self.c, pid, S.default_company(self.c)["id"])
        self.assertNotIn("الشركة المتعاقدة", " ".join(a.detail for a in SV.project_alerts(self.c, pid)))

    def test_company_name_is_required_and_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            S.save_company(self.c, None, "  ")
        with self.assertRaises(ValueError):
            S.save_company(self.c, None, "ش", bogus="x")

    def test_issued_document_keeps_company_snapshot(self):
        cid = S.save_company(self.c, None, "الأفضل", manager="أحمد")
        pid = S.create_project(self.c, "م", contract_no="1", contract_date="2026-01-01", owner="ب")
        S.add_item(self.c, pid, "01", "بند", "و", 10, 2)
        d = SV.create_draft(self.c, pid, "hawsala")
        pl = json.loads(S.get_document(self.c, d)["payload_json"])
        pl["rows"]["01"].update({"prev": "0", "period": "1"})
        S.update_draft_payload(self.c, d, pl)
        SV.issue(self.c, d, explicit_approval=True)
        S.save_company(self.c, cid, "الأفضل", manager="خالد")
        snap = json.loads(S.get_document(self.c, d)["snapshot_json"])
        self.assertEqual(snap["state"]["company"]["manager"], "أحمد")

    def test_legacy_contractor_text_is_migrated_to_a_company(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        conn = S.connect(path)
        pid = S.create_project(conn, "قديم")
        conn.execute("UPDATE projects SET contractor=?, extra_json=?, company_id=NULL WHERE id=?",
                     ("مقاولة القديمة", json.dumps({"manager": "سعيد", "rc_no": "55", "owner_rep": "ممثل"}, ensure_ascii=False), pid))
        conn.execute("DELETE FROM companies"); conn.commit(); conn.close()
        conn = S.connect(path)
        co = S.company_for_project(conn, pid)
        self.assertEqual((co["name"], co["manager"], co["rc_no"]), ("مقاولة القديمة", "سعيد", "55"))
        self.assertTrue(co["is_default"])
        self.assertEqual(json.loads(conn.execute("SELECT extra_json FROM projects WHERE id=?", (pid,)).fetchone()[0])["owner_rep"], "ممثل")
        self.assertEqual(S.migrate(conn, path), [])   # قابل للتكرار

    def test_old_v1_backup_is_accepted_by_restore(self):
        src = os.path.join(tempfile.mkdtemp(), "v1.db")
        conn = S.connect(src)
        conn.execute("UPDATE schema_info SET value='1' WHERE key='version'"); conn.commit(); conn.close()
        dst = os.path.join(tempfile.mkdtemp(), "cur.db")
        S.connect(dst).close()
        S.restore(src, dst)
        conn = S.connect(dst)
        self.assertEqual(conn.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0], S.SCHEMA_VERSION)


class Reordering(unittest.TestCase):
    def setUp(self):
        self.c = new_db()
        self.pid = S.create_project(self.c, "م")
        self.ids = [S.add_item(self.c, self.pid, code, f"بند {code}", "و", 1, 1) for code in ("01", "02", "03", "04")]

    def codes(self):
        return [i["code"] for i in S.list_items(self.c, self.pid)]

    def test_move_up_down_top_bottom_and_position(self):
        S.move_item(self.c, self.ids[3], "up"); self.assertEqual(self.codes(), ["01", "02", "04", "03"])
        S.move_item(self.c, self.ids[0], "down"); self.assertEqual(self.codes(), ["02", "01", "04", "03"])
        S.move_item(self.c, self.ids[2], "top"); self.assertEqual(self.codes(), ["03", "02", "01", "04"])
        S.move_item(self.c, self.ids[2], "bottom"); self.assertEqual(self.codes(), ["02", "01", "04", "03"])
        self.assertEqual(S.move_item(self.c, self.ids[1], 3), 3)
        self.assertEqual([i["ordinal"] for i in S.list_items(self.c, self.pid)], [1, 2, 3, 4])   # ترقيم متصل

    def test_move_edges_are_noops_and_bad_position_rejected(self):
        S.move_item(self.c, self.ids[0], "up"); self.assertEqual(self.codes(), ["01", "02", "03", "04"])
        with self.assertRaises(ValueError):
            S.move_item(self.c, self.ids[0], 9)
        with self.assertRaises(ValueError):
            S.move_item(self.c, self.ids[0], "abc")

    def test_reorder_is_audited_and_does_not_change_codes_or_quantities(self):
        S.set_direct_quantity(self.c, self.ids[0], 5)
        S.reorder_items(self.c, self.pid, [self.ids[3], self.ids[2], self.ids[1], self.ids[0]])
        self.assertEqual(self.codes(), ["04", "03", "02", "01"])
        self.assertEqual(S.get_quantity(self.c, self.ids[0]).final, D(5))
        self.assertGreater(self.c.execute("SELECT COUNT(*) FROM audit_log WHERE field='ordinal'").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            S.reorder_items(self.c, self.pid, self.ids[:2])          # قائمة ناقصة

    def test_documents_follow_the_new_order(self):
        S.move_item(self.c, self.ids[3], "top")
        d = SV.create_draft(self.c, self.pid, "hawsala")
        self.assertEqual(list(json.loads(S.get_document(self.c, d)["payload_json"])["rows"])[0], "04")
        self.assertEqual([r["code"] for r in SV._merged_rows(self.c, self.pid, {})][0], "04")

    def test_insert_after_duplicate_and_natural_sort(self):
        new = S.insert_item_after(self.c, self.pid, self.ids[0], "01-bis", "نسخة")
        self.assertEqual(self.codes(), ["01", "01-bis", "02", "03", "04"])
        dup = S.duplicate_item(self.c, self.ids[1], "10")
        self.assertEqual(self.codes()[:3], ["01", "01-bis", "02"]); self.assertEqual(self.codes()[3], "10")
        S.sort_items_by_code(self.c, self.pid)
        self.assertEqual(self.codes(), ["01", "01-bis", "02", "03", "04", "10"])
        self.assertNotEqual(new, dup)


class AmountDisplay(unittest.TestCase):
    def test_bidi_safe_wraps_every_space_and_roundtrips(self):
        t = fmt_ui("9333403.84")
        self.assertEqual(t.replace("\u200e", ""), "9 333 403.84")
        self.assertEqual(D(t), D("9333403.84"))                      # يُقرأ ثانية بعد التحرير/النسخ
        self.assertEqual(t.count("\u200e"), 2 + 2 * 2)               # طرفان + علامتان حول كل مسافة

    def test_none_is_dash_and_empty_stays_empty(self):
        self.assertEqual(fmt_ui(None).replace("\u200e", ""), "—")
        self.assertEqual(bidi_safe(""), "")


if __name__ == "__main__":
    unittest.main()


class ExportFolders(unittest.TestCase):
    def setUp(self):
        self.c = new_db(); self.root = tempfile.mkdtemp()
        self.pid = S.create_project(self.c, "م"); S.add_item(self.c, self.pid, "01", "b", "و", 1, 1)
        self.doc = SV.create_draft(self.c, self.pid, "situation")

    def set_ps(self, **kw):
        ps = S.project_settings(self.c, self.pid); ps.update(kw); S.set_project_settings(self.c, self.pid, ps)

    def test_no_folder_means_plain_name(self):
        self.assertIsNone(SV.export_dir(self.c, self.pid, "situation"))
        self.assertEqual(SV.suggested_export_path(self.c, self.doc, "docx"), "وضعية الأشغال.docx")

    def test_project_folder_with_type_subfolder_is_created(self):
        self.set_ps(export_dir=self.root)
        p = SV.suggested_export_path(self.c, self.doc, "pdf")
        self.assertEqual(os.path.dirname(p), os.path.join(self.root, "وضعية الأشغال"))
        self.assertTrue(os.path.isdir(os.path.dirname(p)))

    def test_subfolders_can_be_disabled_and_per_type_wins(self):
        self.set_ps(export_dir=self.root, export_subfolders=False)
        self.assertEqual(SV.export_dir(self.c, self.pid, "inventory"), self.root)
        other = os.path.join(self.root, "خاص")
        self.set_ps(export_dirs={"situation": other})
        self.assertEqual(SV.export_dir(self.c, self.pid, "situation"), other)
        self.assertEqual(SV.export_dir(self.c, self.pid, "hawsala"), self.root)

    def test_validation_rejects_relative_paths(self):
        with self.assertRaises(ValueError):
            SV.validate_export_dirs("docs", {})
        base, per = SV.validate_export_dirs(self.root, {"bayan": "", "situation": None})
        self.assertEqual(base, self.root); self.assertIsNone(per["bayan"])

    def test_unusable_folder_falls_back_to_plain_name(self):
        f = os.path.join(self.root, "file.txt"); open(f, "w").close()
        self.set_ps(export_dir=f)                 # مسار يشير إلى ملف لا مجلد
        self.assertEqual(SV.suggested_export_path(self.c, self.doc, "docx"), "وضعية الأشغال.docx")
