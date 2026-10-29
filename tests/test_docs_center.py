"""مركز الوثائق: أرشفة/استرجاع، نسخ، سجل، بحث شامل، لوحة الملخص، النسخ الاحتياطي والاستعادة، وفتح قاعدة قديمة (إصدار 2)."""
import hashlib, json, os, shutil, sqlite3, tempfile, unittest
from worksapp import storage as S, services as SV
from tests.test_core import ITEMS

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def make_project(c, name="ساحة الشباب", contract="2026/09"):
    pid = S.create_project(c, name, contract_no=contract, contract_date="2026-02-23", contractor="الأفضل", extra={"manager": "بكاري"})
    for code, price, q in ITEMS:
        S.add_item(c, pid, code, f"بند {code}", "و", price, q, section="الأشغال")
    S.set_project_settings(c, pid, {"tva_rate": "0.19", "situation_mode": "period", "increase_statuses": ["approved"],
                                    "deductions": [{"code": "g", "label": "Retenue de garantie", "method": "none"}]})
    return pid


def issued_situation(c, pid):
    d = SV.create_draft(c, pid, "situation")
    pl = json.loads(S.get_document(c, d)["payload_json"])
    for code, price, q in ITEMS:
        pl["rows"][code].update({"prev": "0", "period": str(q)})
    pl.setdefault("config", {})["date"] = "2026-03-31"
    S.update_draft_payload(c, d, pl)
    SV.issue(c, d, True)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.db")
        self.c = S.connect(self.path)
        self.pid = make_project(self.c)

    def tearDown(self):
        try: self.c.close()
        except Exception: pass
        shutil.rmtree(self.dir, ignore_errors=True)


class ArchiveAndCopy(Base):
    def test_archive_hides_restores_and_never_alters_the_document(self):
        d = issued_situation(self.c, self.pid)
        before = S.get_document(self.c, d)
        S.archive_document(self.c, d, "انتهى المشروع")
        after = S.get_document(self.c, d)
        self.assertEqual(before, after)                                    # لا تغيير في الوثيقة نفسها
        self.assertEqual(SV.search_documents(self.c), [])
        hit = SV.search_documents(self.c, only_archived=True)
        self.assertEqual([x["id"] for x in hit], [d]); self.assertEqual(hit[0]["display"], "archived")
        S.restore_document(self.c, d)
        self.assertEqual([x["id"] for x in SV.search_documents(self.c)], [d])
        with self.assertRaises(sqlite3.DatabaseError):                     # الثبات ما زال محميًا بالمشغّل
            self.c.execute("UPDATE documents SET number=99 WHERE id=?", (d,))

    def test_draft_cannot_be_archived_and_double_archive_refused(self):
        dr = SV.create_draft(self.c, self.pid, "bayan")
        with self.assertRaises(ValueError): S.archive_document(self.c, dr)
        d = issued_situation(self.c, self.pid); S.archive_document(self.c, d)
        with self.assertRaises(ValueError): S.archive_document(self.c, d)
        with self.assertRaises(ValueError): S.restore_document(self.c, SV.create_draft(self.c, self.pid, "hawsala"))

    def test_archived_document_cannot_be_deleted_with_its_project(self):
        d = issued_situation(self.c, self.pid); S.archive_document(self.c, d)
        with self.assertRaises(ValueError): S.delete_project(self.c, self.pid)
        self.assertEqual(S.get_document(self.c, d)["status"], "issued")

    def test_duplicate_copies_inputs_without_touching_original_or_date(self):
        d = issued_situation(self.c, self.pid)
        orig = S.get_document(self.c, d)
        n = S.duplicate_document(self.c, d)
        new = S.get_document(self.c, n)
        self.assertEqual(new["status"], "draft"); self.assertEqual(new["revision"], 0)
        self.assertIsNone(new["number"]); self.assertEqual(S.get_document(self.c, d), orig)
        p_old, p_new = json.loads(orig["payload_json"]), json.loads(new["payload_json"])
        self.assertEqual(p_old["rows"], p_new["rows"]); self.assertNotIn("date", p_new.get("config", {}))
        self.assertEqual(json.loads(orig["payload_json"]).get("config", {}).get("date"), "2026-03-31")

    def test_duplicate_gets_new_number_when_numbering_on_draft(self):
        S.set_setting(self.c, "numbering_mode", "draft")
        a = SV.create_draft(self.c, self.pid, "bayan"); b = S.duplicate_document(self.c, a)
        self.assertNotEqual(S.get_document(self.c, a)["number"], S.get_document(self.c, b)["number"])

    def test_correction_keeps_original_and_history_tells_the_story(self):
        d = issued_situation(self.c, self.pid)
        snap = S.get_document(self.c, d)["snapshot_json"]
        k = S.create_correction(self.c, d, "خطأ في كمية البند 03")
        S.archive_document(self.c, d, "حلّت محلها التصحيحية")
        self.assertEqual(S.get_document(self.c, d)["snapshot_json"], snap)
        self.assertEqual(S.get_document(self.c, k)["parent_id"], d)
        kinds = [e[1] for e in S.document_history(self.c, d)]
        for want in ("إنشاء", "تعديل", "إصدار", "تصحيح", "أرشفة"):
            self.assertIn(want, kinds)
        self.assertEqual([e[0] for e in S.document_history(self.c, d)], sorted(e[0] for e in S.document_history(self.c, d)))
        self.assertIn("نسخة تصحيحية", S.document_history(self.c, k)[0][2])


class Search(Base):
    def setUp(self):
        super().setUp()
        self.d = issued_situation(self.c, self.pid)
        self.draft = SV.create_draft(self.c, self.pid, "bayan")
        self.pid2 = make_project(self.c, "مدرسة النصر", "2025/11")
        self.d2 = issued_situation(self.c, self.pid2)

    def ids(self, **kw): return sorted(x["id"] for x in SV.search_documents(self.c, **kw))

    def test_by_contract_project_number_type_status(self):
        self.assertEqual(self.ids(text="2025/11"), [self.d2])
        self.assertEqual(self.ids(text="النصر"), [self.d2])
        self.assertEqual(self.ids(text="01"), sorted([self.d, self.d2]))
        self.assertEqual(self.ids(doc_type="bayan"), [self.draft])
        self.assertEqual(self.ids(status="draft"), [self.draft])
        self.assertEqual(self.ids(status="issued", project_id=self.pid), [self.d])

    def test_issued_documents_are_found_by_the_name_at_issue_time(self):
        S.update_project(self.c, self.pid, name="اسم جديد تمامًا")
        self.assertIn(self.d, self.ids(text="ساحة الشباب"))                # الاسم التاريخي
        hit = [x for x in SV.search_documents(self.c, text="اسم جديد") if x["id"] == self.d]
        self.assertEqual(len(hit), 1)

    def test_amount_and_date_filters(self):
        self.assertEqual(self.ids(amount_min="9000000", amount_max="9400000", doc_type="situation"), sorted([self.d, self.d2]))
        self.assertEqual(self.ids(amount_min="9400000"), [])
        self.assertEqual(self.ids(date_from="2999-01-01"), [])
        self.assertEqual(len(self.ids(date_from="2000-01-01", date_to="2999-01-01")), 3)
        self.assertEqual(self.ids(text="9333403.84"), sorted([self.d, self.d2]))      # المبلغ نصًا كما يُخزَّن
        self.assertEqual(self.ids(text="9 333 403.84"), sorted([self.d, self.d2]))   # وكما يُعرض بفاصل الآلاف

    def test_corrections_and_archive_statuses(self):
        k = S.create_correction(self.c, self.d, "x")
        self.assertEqual(self.ids(status="draft_correction"), [k])
        S.archive_document(self.c, self.d2)
        self.assertNotIn(self.d2, self.ids())
        self.assertIn(self.d2, self.ids(include_archived=True))

    def test_dashboard_counts_latest_revision_only_and_keeps_money_unchanged(self):
        st = SV.dashboard_stats(self.c)
        self.assertEqual(str(st["total_net"]), "18666807.68")              # 2 × 9 333 403.84 كما في الحسابات المعتمدة
        self.assertEqual((st["projects"], st["drafts"], st["issued"]), (2, 1, 2))
        k = S.create_correction(self.c, self.d, "تصحيح")
        pl = json.loads(S.get_document(self.c, k)["payload_json"]); pl["rows"]["01"]["period"] = "10"
        S.update_draft_payload(self.c, k, pl); SV.issue(self.c, k, True)
        st2 = SV.dashboard_stats(self.c)
        self.assertNotEqual(st2["total_net"], st["total_net"])
        self.assertEqual(st2["corrections"], 1)
        orig_net = json.loads(S.get_document(self.c, self.d)["snapshot_json"])["results"]["net"]
        self.assertEqual(orig_net, "9333403.84")                           # الأصل لم يتغير


class BackupRestore(Base):
    def test_backup_is_verified_and_leaves_no_partial_file(self):
        issued_situation(self.c, self.pid)
        dest = os.path.join(self.dir, "b.db")
        S.backup(self.c, dest)
        info = S.inspect_backup(dest)
        self.assertEqual((info["projects"], info["issued"], info["version"]), (1, 1, S.SCHEMA_VERSION))
        self.assertFalse(os.path.exists(dest + ".partial"))

    def test_restore_actually_brings_data_back(self):
        d = issued_situation(self.c, self.pid)
        snap = S.get_document(self.c, d)["snapshot_json"]
        dest = S.backup(self.c, os.path.join(self.dir, "b.db"))
        S.update_project(self.c, self.pid, name="تعديل بعد النسخة")
        SV.create_draft(self.c, self.pid, "bayan")
        self.c.close()
        info = S.restore(dest, self.path)
        self.assertEqual(info["documents"], 1)
        self.assertTrue(os.path.exists(self.path + ".before_restore"))
        c2 = S.connect(self.path)
        self.assertEqual(c2.execute("SELECT name FROM projects").fetchone()[0], "ساحة الشباب")
        self.assertEqual(c2.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)
        self.assertEqual(S.get_document(c2, d)["snapshot_json"], snap)
        c2.close(); self.c = S.connect(self.path)

    def test_corrupt_or_foreign_files_never_replace_the_database(self):
        before = sha(self.path)
        bad = os.path.join(self.dir, "bad.db")
        with open(bad, "wb") as fh: fh.write(b"not a database" * 100)
        other = os.path.join(self.dir, "other.db"); sqlite3.connect(other).executescript("CREATE TABLE x(a);")
        for src in (bad, other, os.path.join(self.dir, "missing.db")):
            with self.assertRaises(ValueError): S.restore(src, self.path)
        self.assertEqual(sha(self.path), before)
        self.assertFalse(os.path.exists(self.path + ".before_restore"))

    def test_truncated_backup_is_rejected(self):
        issued_situation(self.c, self.pid)
        dest = S.backup(self.c, os.path.join(self.dir, "b.db"))
        with open(dest, "rb") as fh: data = fh.read()
        with open(dest, "wb") as fh: fh.write(data[: len(data) // 2])
        with self.assertRaises(ValueError): S.restore(dest, self.path)


class LegacyDatabase(unittest.TestCase):
    """قاعدة إصدار 2 أُنشئت بالكود الأصلي قبل هذا التطوير (tests/fixtures/legacy_v2.db)."""
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.path = os.path.join(self.dir, "old.db")
        shutil.copy2(os.path.join(FIX, "legacy_v2.db"), self.path)
        with open(os.path.join(FIX, "legacy_v2.db.expected.json"), encoding="utf-8") as fh:
            self.exp = json.load(fh)

    def tearDown(self): shutil.rmtree(self.dir, ignore_errors=True)

    def test_old_database_opens_migrates_safely_and_keeps_every_document_and_amount(self):
        old_ver = sqlite3.connect(self.path).execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0]
        self.assertEqual(old_ver, "2")
        c = S.connect(self.path)
        self.assertTrue(os.path.exists(self.path + ".before_migrate"))                 # نسخة أمان قبل أي تغيير
        self.assertEqual(c.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0], S.SCHEMA_VERSION)
        d = S.get_document(c, self.exp["issued_id"])
        self.assertEqual(hashlib.sha256(d["snapshot_json"].encode()).hexdigest(), self.exp["snapshot_sha"])
        self.assertEqual(json.loads(d["snapshot_json"])["results"]["net"], self.exp["net"])
        self.assertEqual(S.get_document(c, self.exp["correction_id"])["parent_id"], self.exp["issued_id"])
        self.assertEqual(S.get_document(c, self.exp["draft_id"])["status"], "draft")
        res = SV.search_documents(c, text="ساحة الشباب")
        self.assertEqual(len(res), 3)
        S.archive_document(c, self.exp["issued_id"], "اختبار")                           # الميزة الجديدة تعمل على قاعدة قديمة
        c.close()

    def test_old_database_documents_still_export(self):
        from worksapp import export as E
        c = S.connect(self.path)
        out = E.export_docx(c, self.exp["issued_id"], os.path.join(self.dir, "o.docx"))
        self.assertTrue(os.path.getsize(out) > 5000)
        c.close()

    def test_old_backup_file_is_accepted_by_restore(self):
        target = os.path.join(self.dir, "live.db"); sqlite3.connect(target).close()
        info = S.restore(self.path, target)
        self.assertEqual(info["version"], "2")
        c = S.connect(target)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 3)
        c.close()


if __name__ == "__main__":
    unittest.main()
