import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest
from unittest import mock

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


class RangeFixTests(unittest.TestCase):
    def test_mon_to_sun_range(self):
        values, _ = cn.parse_field("mon-sun", cn.FIELDS[4])
        self.assertEqual(values, {0, 1, 2, 3, 4, 5, 6})

    def test_numeric_one_to_zero_means_through_sunday(self):
        values, _ = cn.parse_field("1-0", cn.FIELDS[4])
        self.assertEqual(values, {0, 1, 2, 3, 4, 5, 6})

    def test_fri_to_sun(self):
        values, _ = cn.parse_field("fri-sun", cn.FIELDS[4])
        self.assertEqual(values, {5, 6, 0})

    def test_sun_alone_and_sun_to_sat_unchanged(self):
        self.assertEqual(cn.parse_field("sun", cn.FIELDS[4])[0], {0})
        self.assertEqual(cn.parse_field("sun-sat", cn.FIELDS[4])[0], {0, 1, 2, 3, 4, 5, 6})

    def test_genuinely_reversed_ranges_still_rejected(self):
        for bad in ("sat-mon", "5-2", "wed-tue"):
            with self.assertRaises(cn.CronError):
                cn.parse_field(bad, cn.FIELDS[4])

    def test_other_fields_unaffected(self):
        with self.assertRaises(cn.CronError):
            cn.parse_field("5-0", cn.FIELDS[0])

    def test_next_runs_with_mon_sun(self):
        self.assertEqual(runs("0 9 * * mon-sun", D(2030, 1, 4, 10, 0), 2), ["2030-01-05 09:00", "2030-01-06 09:00"])


class StatsTests(unittest.TestCase):
    def test_gap_stats(self):
        r = cn.next_runs("*/15 * * * *", D(2030, 1, 1, 0, 0), 100)
        s = cn.gap_stats(r)
        self.assertEqual((s["shortest_gap_minutes"], s["longest_gap_minutes"]), (15, 15))
        self.assertEqual(s["average_runs_per_day"], 96.0)

    def test_uneven_gaps(self):
        s = cn.gap_stats(cn.next_runs("0 9,17 * * mon-fri", D(2030, 1, 1), 40))
        self.assertEqual(s["shortest_gap_minutes"], 8 * 60)
        self.assertEqual(s["longest_gap_minutes"], 64 * 60)  # Friday 17:00 -> Monday 09:00
        self.assertGreater(s["longest_gap_minutes"], 24 * 60)  # over the weekend

    def test_too_few_runs(self):
        self.assertIsNone(cn.gap_stats([D(2030, 1, 1)]))

    def test_fmt_minutes(self):
        self.assertEqual(cn.fmt_minutes(5), "5 min")
        self.assertEqual(cn.fmt_minutes(180), "3.0 h")
        self.assertEqual(cn.fmt_minutes(4320), "3.0 days")


class ZoneTests(unittest.TestCase):
    def test_utc_to_other_zone(self):
        z_utc, z_ist = cn.get_zone("UTC"), cn.get_zone("Europe/Istanbul")
        local, gap = cn.to_zoned(D(2030, 1, 4, 9, 0), z_utc, z_ist)
        self.assertEqual((local.strftime("%Y-%m-%d %H:%M %z"), gap), ("2030-01-04 12:00 +0300", False))

    def test_dst_gap_is_detected(self):
        z = cn.get_zone("America/New_York")
        _, gap = cn.to_zoned(D(2030, 3, 10, 2, 30), z, z)      # clocks jump 02:00 -> 03:00
        self.assertTrue(gap)
        _, ok = cn.to_zoned(D(2030, 3, 10, 3, 30), z, z)
        self.assertFalse(ok)

    def test_dst_offsets_follow_the_calendar(self):
        z = cn.get_zone("Europe/Berlin")
        winter, _ = cn.to_zoned(D(2030, 1, 15, 12, 0), z, z)
        summer, _ = cn.to_zoned(D(2030, 7, 15, 12, 0), z, z)
        self.assertEqual((winter.strftime("%z"), summer.strftime("%z")), ("+0100", "+0200"))

    def test_unknown_zone_is_a_clear_error(self):
        with self.assertRaises(cn.CronError) as ctx:
            cn.get_zone("Mars/Olympus")
        self.assertIn("unknown time zone", str(ctx.exception))

    def test_malformed_zone_name(self):
        with self.assertRaises(cn.CronError):
            cn.get_zone("../../etc/passwd")


CRONTAB = """# my jobs
MAILTO=me@example.com
PATH=/usr/bin:/bin

*/15 9-17 * * mon-fri /usr/local/bin/sync.sh --quiet
@daily  /usr/local/bin/backup.sh
@reboot /usr/local/bin/start.sh
0 0 31 2 * /bin/never
60 * * * * /bin/bad
5 4 * *
@weekly
"""


class CrontabTests(unittest.TestCase):
    def test_parse_skips_comments_and_environment(self):
        lines = [(no, sched) for no, sched, _, _, err in cn.parse_crontab(CRONTAB) if err is None]
        self.assertEqual([no for no, _ in lines], [5, 6, 7, 8, 9, 11])

    def test_short_lines_reported(self):
        errs = [(no, err) for no, _, _, _, err in cn.parse_crontab(CRONTAB) if err]
        self.assertEqual([no for no, _ in errs], [10])

    def test_report(self):
        results, bad = cn.crontab_report(CRONTAB, D(2030, 1, 4, 16, 50), False, 2)
        self.assertTrue(bad)
        by_line = {r["line"]: r for r in results}
        self.assertTrue(by_line[5]["valid"])
        self.assertEqual(by_line[5]["next_runs"], ["2030-01-04 17:00", "2030-01-04 17:15"])
        self.assertEqual(by_line[5]["command"], "/usr/local/bin/sync.sh --quiet")
        self.assertEqual(by_line[7]["explanation"], "At system start (no schedule to compute)")
        self.assertFalse(by_line[8]["valid"])       # Feb 31
        self.assertIn("never matches", by_line[8]["error"])
        self.assertFalse(by_line[9]["valid"])       # minute 60
        self.assertIn("outside 0-59", by_line[9]["error"])
        self.assertFalse(by_line[10]["valid"])
        self.assertTrue(by_line[11]["valid"])       # "@weekly" alone is a valid schedule with an empty command

    def test_system_crontab_user_column(self):
        text = "*/5 * * * * root /usr/bin/check\n@hourly www-data /usr/bin/x\n0 0 * * * onlyuser\n"
        rows = list(cn.parse_crontab(text, system=True))
        self.assertEqual([(r[3], r[2]) for r in rows[:2]], [("root", "/usr/bin/check"), ("www-data", "/usr/bin/x")])
        self.assertIsNone(rows[2][4])  # user without a command is still reported by the caller as an empty command

    def test_system_line_without_user_and_command(self):
        rows = list(cn.parse_crontab("@daily\n", system=True))
        self.assertIsNotNone(rows[0][4])

    def test_clean_crontab(self):
        results, bad = cn.crontab_report("0 3 * * * /bin/job\n", D(2030, 1, 1), False, 3)
        self.assertFalse(bad)
        self.assertEqual(len(results[0]["next_runs"]), 3)


def run_main(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin)):
        code = cn.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class NewCliTests(unittest.TestCase):
    FROM = ["--from", "2030-01-04 16:50"]

    def test_json(self):
        code, out, _ = run_main("*/15 9-17 * * mon-fri", "-n", "2", "--json", *self.FROM)
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual([r["time"] for r in data["runs"]], ["2030-01-04 17:00", "2030-01-04 17:15"])
        self.assertTrue(data["explanation"].startswith("Every 15 minutes"))
        self.assertNotIn("summary", data)

    def test_json_summary(self):
        _, out, _ = run_main("*/10 * * * *", "-n", "1", "--summary", "--json", *self.FROM)
        s = json.loads(out)["summary"]
        self.assertEqual((s["shortest_gap_minutes"], s["runs_examined"]), (10, 500))

    def test_text_summary_line(self):
        _, out, _ = run_main("0 * * * *", "-n", "1", "--summary", *self.FROM)
        self.assertIn("shortest gap 60 min", out)

    def test_tz_and_show_in(self):
        code, out, _ = run_main("0 9 * * *", "-n", "1", "--tz", "UTC", "--show-in", "Europe/Istanbul", *self.FROM)
        self.assertEqual(code, 0)
        self.assertIn("2030-01-05 12:00 +0300", out)

    def test_tz_only_shows_offset(self):
        _, out, _ = run_main("0 9 * * *", "-n", "1", "--tz", "Europe/Berlin", *self.FROM)
        self.assertIn("2030-01-05 09:00 +0100", out)

    def test_dst_gap_marked(self):
        code, out, _ = run_main("30 2 * * *", "-n", "1", "--tz", "America/New_York", "--from", "2030-03-09 12:00")
        self.assertIn("DST gap", out)

    def test_bad_zone(self):
        code, _, err = run_main("0 9 * * *", "--tz", "Nowhere/Land")
        self.assertEqual(code, 2)
        self.assertIn("unknown time zone", err)

    def test_plain_output_unchanged(self):
        code, out, _ = run_main("*/15 9-17 * * mon-fri", "-n", "2", *self.FROM)
        self.assertEqual(out.splitlines(), ["Every 15 minutes, past hour 9 through 17, on Monday through Friday",
                                            "  2030-01-04 17:00 Fri", "  2030-01-04 17:15 Fri"])

    def test_crontab_file_text_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "crontab")
            with open(p, "w") as fh:
                fh.write(CRONTAB)
            code, out, err = run_main("--crontab", p, "-n", "1", *self.FROM)
        self.assertEqual(code, 2)
        self.assertIn("line 5: */15 9-17 * * mon-fri  ->  /usr/local/bin/sync.sh --quiet", out)
        self.assertIn("next 2030-01-04 17:00", out)
        self.assertIn("INVALID: minute: 60 is outside 0-59", out)
        self.assertIn("invalid", err)

    def test_crontab_stdin_json_clean(self):
        code, out, _ = run_main("--crontab", "-", "--json", "-n", "1", *self.FROM, stdin="0 3 * * * /bin/job\n")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual((data[0]["valid"], data[0]["command"]), (True, "/bin/job"))

    def test_crontab_missing_file(self):
        self.assertEqual(run_main("--crontab", "/nonexistent/crontab")[0], 2)

    def test_crontab_system_flag(self):
        code, out, _ = run_main("--crontab", "-", "--system", "--json", "-n", "1", *self.FROM,
                                stdin="*/5 * * * * root /usr/bin/check\n")
        self.assertEqual(json.loads(out)[0]["user"], "root")

    def test_no_expression_is_usage_error(self):
        self.assertEqual(run_main()[0], 2)

    def test_invalid_expression_still_exit_2(self):
        code, _, err = run_main("60 * * * *")
        self.assertEqual(code, 2)
        self.assertIn("outside 0-59", err)


if __name__ == "__main__":
    unittest.main()
