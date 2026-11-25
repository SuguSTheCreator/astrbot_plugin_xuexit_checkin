import tempfile
import unittest
from pathlib import Path

import audit as audit_module
from audit import AuditLog


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "audit.jsonl"
        self.log = AuditLog(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_write_and_tail(self):
        self.assertTrue(self.log.write("consent", actor="webui", detail="勾选同意"))
        self.assertTrue(self.log.write("checkin", actor="scheduler", ok=True))
        rows = self.log.tail(10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["action"], "checkin")
        self.assertEqual(rows[1]["actor"], "webui")
        self.assertEqual(self.log.count(), 2)

    def test_tail_limit(self):
        for i in range(30):
            self.log.write("evt", detail=str(i))
        self.assertEqual(len(self.log.tail(5)), 5)

    def test_bad_lines_skipped(self):
        self.log.write("ok1")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("{not json}\n")
        self.assertEqual(len(self.log.tail(10)), 1)

    def test_no_file(self):
        missing = AuditLog(Path(self.dir.name) / "nope.jsonl")
        self.assertEqual(missing.tail(3), [])
        self.assertEqual(missing.count(), 0)

    def test_never_raises(self):
        broken = AuditLog(Path(self.dir.name))
        self.assertFalse(broken.write("x"))

    def test_rotation(self):
        old = audit_module.MAX_BYTES
        audit_module.MAX_BYTES = 200
        try:
            for i in range(20):
                self.log.write("evt", detail="x" * 40)
            self.assertTrue(Path(str(self.path) + ".1").exists())
        finally:
            audit_module.MAX_BYTES = old


if __name__ == "__main__":
    unittest.main()
