"""How the agent counts down to a deadline."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_agent

OCT_1 = dt.date(2026, 10, 1)


class DaysUntilTests(unittest.TestCase):
    def test_the_last_day_is_zero_not_already_gone(self):
        self.assertEqual(intern_agent.days_until("2026-10-01", today=OCT_1), 0)

    def test_counts_whole_calendar_days(self):
        self.assertEqual(intern_agent.days_until("2026-10-11", today=OCT_1), 10)
        self.assertEqual(intern_agent.days_until("2026-09-30", today=OCT_1), -1)

    def test_no_deadline_is_none(self):
        self.assertIsNone(intern_agent.days_until("", today=OCT_1))
        self.assertIsNone(intern_agent.days_until("rolling", today=OCT_1))


if __name__ == "__main__":
    unittest.main()
