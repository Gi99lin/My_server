"""Offline tests for hub-stale-tasks: python3 -I -m unittest test_hub_stale_tasks (run from this directory)."""
import importlib.machinery, importlib.util, os, unittest
from datetime import datetime, timezone

_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub-stale-tasks")
_loader = importlib.machinery.SourceFileLoader("hub_stale_tasks", _path)
_spec = importlib.util.spec_from_loader("hub_stale_tasks", _loader)
hst = importlib.util.module_from_spec(_spec)
_loader.exec_module(hst)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

def vtodo(*lines):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n" + "\r\n".join(lines) + "\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"

class ParseTodo(unittest.TestCase):
    def test_reads_uid_summary_and_last_modified(self):
        t = hst.parse_todo(vtodo("UID:a1", "SUMMARY:Renew domain", "LAST-MODIFIED:20261020T080000Z", "STATUS:NEEDS-ACTION"))
        self.assertEqual(t["uid"], "a1")
        self.assertEqual(t["summary"], "Renew domain")
        self.assertEqual(t["last_modified"], datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc))
        self.assertTrue(t["open"])

    def test_unfolds_long_summary_lines(self):
        t = hst.parse_todo(vtodo("UID:a2", "SUMMARY:Very long", " title here", "LAST-MODIFIED:20261020T080000Z"))
        self.assertEqual(t["summary"], "Very longtitle here")

    def test_completed_is_not_open(self):
        t = hst.parse_todo(vtodo("UID:a3", "SUMMARY:x", "STATUS:COMPLETED", "LAST-MODIFIED:20261001T000000Z"))
        self.assertFalse(t["open"])

    def test_cancelled_is_not_open(self):
        t = hst.parse_todo(vtodo("UID:a4", "SUMMARY:x", "STATUS:CANCELLED", "LAST-MODIFIED:20261001T000000Z"))
        self.assertFalse(t["open"])

    def test_falls_back_to_dtstamp_when_no_last_modified(self):
        t = hst.parse_todo(vtodo("UID:a5", "SUMMARY:x", "DTSTAMP:20261001T000000Z"))
        self.assertEqual(t["last_modified"], datetime(2026, 10, 1, tzinfo=timezone.utc))

    def test_unescapes_commas_in_summary(self):
        t = hst.parse_todo(vtodo("UID:a6", r"SUMMARY:Milk\, bread", "LAST-MODIFIED:20261001T000000Z"))
        self.assertEqual(t["summary"], "Milk, bread")

class IsStale(unittest.TestCase):
    def todo(self, lm, open_=True):
        return {"uid": "u", "summary": "s", "last_modified": lm, "open": open_}

    def test_22_days_old_is_stale(self):
        self.assertTrue(hst.is_stale(self.todo(datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc)), NOW, 21))

    def test_exactly_21_days_is_not_stale(self):
        self.assertFalse(hst.is_stale(self.todo(datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)), NOW, 21))

    def test_completed_never_stale(self):
        self.assertFalse(hst.is_stale(self.todo(datetime(2026, 1, 1, tzinfo=timezone.utc), open_=False), NOW, 21))

    def test_unknown_date_is_stale(self):
        self.assertTrue(hst.is_stale(self.todo(None), NOW, 21))

class HubListFilter(unittest.TestCase):
    def test_hub_list_is_kept(self):
        self.assertTrue(hst.is_hub_list("/remote.php/dav/calendars/admin/tanks/"))

    def test_routine_is_kept(self):
        self.assertTrue(hst.is_hub_list("/remote.php/dav/calendars/admin/routine/"))

    def test_inbox_is_kept(self):
        self.assertTrue(hst.is_hub_list("/remote.php/dav/calendars/admin/hub-inbox/"))

    def test_shared_list_is_skipped(self):
        self.assertFalse(hst.is_hub_list("/remote.php/dav/calendars/admin/personal_shared_by_dmitriy/"))

    def test_default_personal_calendar_is_skipped(self):
        self.assertFalse(hst.is_hub_list("/remote.php/dav/calendars/admin/personal/"))

    def test_percent_encoded_href_does_not_crash(self):
        self.assertFalse(hst.is_hub_list("/remote.php/dav/calendars/admin/%D0%A1%D0%BF%D0%B8%D1%81%D0%BE%D0%BA/"))

if __name__ == "__main__":
    unittest.main()
