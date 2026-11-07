import datetime
import unittest

import cronnext as cn

D = datetime.datetime


def runs(expr, start, n=3):
    return [d.strftime("%Y-%m-%d %H:%M") for d in cn.next_runs(expr, start, n)]


class ParseTests(unittest.TestCase):
    def test_fields(self):
        v, star = cn.parse_field("*/15", cn.FIELDS[0])
        self.assertEqual(v, {0, 15, 30, 45})
        self.assertTrue(star)
        self.assertEqual(cn.parse_field("1-5", cn.FIELDS[4])[0], {1, 2, 3, 4, 5})
        self.assertEqual(cn.parse_field("mon,fri", cn.FIELDS[4])[0], {1, 5})
        self.assertEqual(cn.parse_field("jan-mar", cn.FIELDS[3])[0], {1, 2, 3})
        self.assertEqual(cn.parse_field("10-20/5", cn.FIELDS[0])[0], {10, 15, 20})
        self.assertEqual(cn.parse_field("5/20", cn.FIELDS[0])[0], {5, 25, 45})

    def test_sunday_seven(self):
        self.assertEqual(cn.parse_field("7", cn.FIELDS[4])[0], {0})

    def test_invalid(self):
        for bad in ("60 * * * *", "* * *", "*/0 * * * *", "@reboot", "5-1 * * * *",
                    "a * * * *", "* 24 * * *", "* * 0 * *", "*,, * * * *", "1/x * * * *"):
            with self.assertRaises(cn.CronError, msg=bad):
                cn.parse(bad)


class NextRunTests(unittest.TestCase):
    def test_every_15_minutes(self):
        self.assertEqual(runs("*/15 * * * *", D(2030, 1, 1, 10, 7), 4),
                         ["2030-01-01 10:15", "2030-01-01 10:30", "2030-01-01 10:45", "2030-01-01 11:00"])

    def test_strictly_after_start(self):
        self.assertEqual(runs("0 9 * * *", D(2030, 1, 1, 9, 0), 1), ["2030-01-02 09:00"])

    def test_weekdays(self):
        # 2030-01-04 is a Friday
        self.assertEqual(runs("0 9 * * 1-5", D(2030, 1, 4, 10, 0), 2),
                         ["2030-01-07 09:00", "2030-01-08 09:00"])

    def test_leap_day(self):
        self.assertEqual(runs("30 2 29 2 *", D(2030, 1, 1), 1), ["2032-02-29 02:30"])

    def test_dom_or_dow(self):
        self.assertEqual(runs("0 0 13 * 5", D(2030, 1, 1), 4),
                         ["2030-01-04 00:00", "2030-01-11 00:00", "2030-01-13 00:00", "2030-01-18 00:00"])

    def test_macros(self):
        self.assertEqual(runs("@daily", D(2030, 3, 5, 12, 0), 1), ["2030-03-06 00:00"])
        self.assertEqual(runs("@hourly", D(2030, 3, 5, 12, 30), 1), ["2030-03-05 13:00"])
        self.assertEqual(runs("@yearly", D(2030, 3, 5), 1), ["2031-01-01 00:00"])
        self.assertEqual(runs("@weekly", D(2030, 1, 1), 1), ["2030-01-06 00:00"])  # Sunday

    def test_year_rollover(self):
        self.assertEqual(runs("0 0 1 1 *", D(2030, 12, 31, 23, 59), 1), ["2031-01-01 00:00"])

    def test_impossible_date(self):
        with self.assertRaises(cn.CronError):
            cn.next_runs("0 0 31 2 *", D(2030, 1, 1), 1)


class ExplainTests(unittest.TestCase):
    def test_explain(self):
        self.assertEqual(cn.explain("* * * * *"), "Every minute")
        self.assertEqual(cn.explain("*/5 * * * *"), "Every 5 minutes")
        self.assertEqual(cn.explain("0 9 * * mon-fri"), "At minute 0, past hour 9, on Monday through Friday")
        self.assertIn("in January", cn.explain("0 0 1 jan *"))
        self.assertIn("either", cn.explain("0 0 13 * 5"))


class CliTests(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(cn.main(["*/5 * * * *", "--from", "2030-01-01 00:00", "-n", "2"]), 0)
        self.assertEqual(cn.main(["99 * * * *"]), 2)
        self.assertEqual(cn.main(["* * * * *", "--from", "not a date"]), 2)


if __name__ == "__main__":
    unittest.main()
