import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from store import Store


class TestStore(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            s = Store(p)
            self.assertEqual(s.data["settings"]["preferred_quant"], "Q4")
            s.data["settings"]["destination"] = "/Volumes/SSD"
            s.remember_destination("/Volumes/SSD")
            s.save()
            s2 = Store(p)
            self.assertEqual(s2.data["settings"]["destination"], "/Volumes/SSD")
            self.assertEqual(s2.data["settings"]["recent_destinations"], ["/Volumes/SSD"])

    def test_recents_dedupe_cap(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "s.json"))
            for i in range(8):
                s.remember_destination("/V/%d" % i)
            s.remember_destination("/V/3")
            r = s.data["settings"]["recent_destinations"]
            self.assertEqual(r[0], "/V/3")
            self.assertLessEqual(len(r), 6)

    def test_corrupt_file_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            open(p, "w").write("{broken")
            s = Store(p)
            self.assertIn("settings", s.data)


if __name__ == "__main__":
    unittest.main()
