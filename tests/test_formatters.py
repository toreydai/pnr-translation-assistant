from datetime import date
import unittest

from src.pnr_service.formatters import format_pnr_date, format_pnr_time


class FormatterTest(unittest.TestCase):
    def test_relative_date(self):
        self.assertEqual("19jun26", format_pnr_date("大后天", date(2026, 6, 16)))

    def test_month_day_date(self):
        self.assertEqual("10oct26", format_pnr_date("10月10日", date(2026, 6, 16)))

    def test_next_month(self):
        self.assertEqual("23jul26", format_pnr_date("下个月23号", date(2026, 6, 16)))

    def test_time_period_default(self):
        self.assertEqual("1200", format_pnr_time("下午"))

    def test_time_exact(self):
        self.assertEqual("1350", format_pnr_time("13点50"))


if __name__ == "__main__":
    unittest.main()

