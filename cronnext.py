#!/usr/bin/env python3
"""cronnext - validate a cron expression, explain it, and list its next run times.

Standard library only (no croniter). Times are naive local time.
Exit code 0 = valid, 2 = invalid expression.

    python3 cronnext.py "*/15 9-17 * * mon-fri" -n 5
"""
import argparse
import calendar
import datetime
import json
import re
import sys

__version__ = "1.1.0"

MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
FIELDS = [  # name, min, max, names
    ("minute", 0, 59, None), ("hour", 0, 23, None), ("day-of-month", 1, 31, None),
    ("month", 1, 12, MONTHS), ("day-of-week", 0, 7, DAYS),
]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class CronError(ValueError):
    pass


def _num(tok, lo, hi, names, field):
    t = tok.lower()
    if names and t in names:
        return names.index(t) + (1 if field == "month" else 0)
    if not t.isdigit():
        raise CronError("%s: invalid value %r" % (field, tok))
    n = int(t)
    if not lo <= n <= hi:
        raise CronError("%s: %d is outside %d-%d" % (field, n, lo, hi))
    return n


def parse_field(text, spec):
    """Return (set_of_values, is_star_prefixed) for one cron field."""
    field, lo, hi, names = spec
    values = set()
    for part in text.split(","):
        if not part:
            raise CronError("%s: empty list item" % field)
        rng, _, step_s = part.partition("/")
        step = 1
        if "/" in part:
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError("%s: invalid step %r" % (field, step_s))
            step = int(step_s)
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            x, y = rng.split("-", 1)
            a, b = _num(x, lo, hi, names, field), _num(y, lo, hi, names, field)
            if field == "day-of-week" and b == 0 and a > 0 and y.lower() in ("sun", "0"):
                b = 7  # "mon-sun" or "1-0" means through Sunday, which cron also writes as 7
            if a > b:
                raise CronError("%s: range %s is reversed" % (field, rng))
        else:
            a = _num(rng, lo, hi, names, field)
            b = hi if "/" in part else a
        values.update(range(a, b + 1, step))
    if field == "day-of-week" and 7 in values:
        values.discard(7)
        values.add(0)
    return values, text.startswith("*")


def parse(expr):
    expr = expr.strip()
    expr = MACROS.get(expr.lower(), expr)
    if expr.lower().startswith("@"):
        raise CronError("unsupported macro %r" % expr)
    parts = expr.split()
    if len(parts) != 5:
        raise CronError("expected 5 fields (minute hour day-of-month month day-of-week), got %d" % len(parts))
    parsed = [parse_field(p, s) for p, s in zip(parts, FIELDS)]
    return parts, parsed


def _day_matches(parsed, dt):
    dom, dom_star = parsed[2]
    dow, dow_star = parsed[4]
    dom_ok = dt.day in dom
    dow_ok = (dt.isoweekday() % 7) in dow
    return (dom_ok and dow_ok) if (dom_star or dow_star) else (dom_ok or dow_ok)


def next_runs(expr, start, count=5):
    """Return the next `count` datetimes (strictly after `start`) matching expr."""
    _, parsed = parse(expr)
    minutes, hours, months = parsed[0][0], parsed[1][0], parsed[3][0]
    dt = start.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    limit = start.year + 9
    out = []
    while len(out) < count:
        if dt.year > limit:
            raise CronError("expression never matches a real date (e.g. Feb 30)")
        if dt.month not in months:
            year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
            dt = datetime.datetime(year, month, 1)
        elif not _day_matches(parsed, dt):
            dt = datetime.datetime(dt.year, dt.month, dt.day) + datetime.timedelta(days=1)
        elif dt.hour not in hours:
            dt = dt.replace(minute=0) + datetime.timedelta(hours=1)
        elif dt.minute not in minutes:
            dt += datetime.timedelta(minutes=1)
        else:
            out.append(dt)
            dt += datetime.timedelta(minutes=1)
    return out


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _phrase(raw, vals, label, namer=None):
    if raw == "*":
        return None
    if raw.startswith("*/") and raw[2:].isdigit():
        return "every %s %ss" % (raw[2:], label)
    shown = [namer(v) if namer else str(v) for v in sorted(vals)]
    if len(shown) > 2 and sorted(vals) == list(range(min(vals), max(vals) + 1)):
        return "%s through %s" % (shown[0], shown[-1])
    return _join(shown)


def explain(expr):
    parts, parsed = parse(expr)
    mi, ho, dm, mo, dw = parts
    pieces = []
    m = _phrase(mi, parsed[0][0], "minute")
    h = _phrase(ho, parsed[1][0], "hour")
    if m is None:
        pieces.append("every minute")
    elif m.startswith("every"):
        pieces.append(m)
    else:
        pieces.append("at minute " + m)
    if h:
        pieces.append(h if h.startswith("every") else "past hour " + h)
    d = _phrase(dm, parsed[2][0], "day")
    if d:
        pieces.append("on day-of-month " + d)
    mon = _phrase(mo, parsed[3][0], "month", lambda v: MONTH_NAMES[v - 1])
    if mon:
        pieces.append("in " + mon)
    wd = _phrase(dw, parsed[4][0], "day", lambda v: DAY_NAMES[v])
    if wd:
        pieces.append("on " + wd)
    text = ", ".join(pieces)
    if d and wd and not (dm.startswith("*") or dw.startswith("*")):
        text += " (runs when either the day-of-month or the day-of-week matches)"
    return text[0].upper() + text[1:]


def get_zone(name):
    """zoneinfo.ZoneInfo for ``name`` with a clear error when the zone or the tz database is missing."""
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(name)
    except ImportError:
        raise CronError("time zones need Python 3.9+ (zoneinfo)")
    except Exception:  # ZoneInfoNotFoundError, ValueError for malformed keys
        raise CronError("unknown time zone %r (on Windows, `pip install tzdata`)" % name)


def to_zoned(naive, run_zone, show_zone):
    """(aware datetime in show_zone, dst_gap) for a wall-clock run time in run_zone."""
    aware = naive.replace(tzinfo=run_zone)
    utc = aware.astimezone(datetime.timezone.utc)
    gap = utc.astimezone(run_zone).replace(tzinfo=None) != naive  # that wall-clock time does not exist
    return utc.astimezone(show_zone), gap


def gap_stats(runs):
    """Shortest/longest gap (minutes) and average runs per day over a list of datetimes."""
    if len(runs) < 2:
        return None
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(runs, runs[1:])]
    span_days = (runs[-1] - runs[0]).total_seconds() / 86400
    return {"runs_examined": len(runs), "shortest_gap_minutes": min(gaps), "longest_gap_minutes": max(gaps),
            "average_runs_per_day": round((len(runs) - 1) / span_days, 2) if span_days else None}


def fmt_minutes(m):
    m = int(round(m))
    if m < 120:
        return "%d min" % m
    if m < 2880:
        return "%.1f h" % (m / 60)
    return "%.1f days" % (m / 1440)


def parse_crontab(text, system=False):
    """Yield (lineno, schedule, command, user_or_None, error_or_None) for each job line."""
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            continue
        toks = line.split()
        if toks[0].startswith("@"):
            schedule, rest = toks[0], toks[1:]
        else:
            if len(toks) < 6:
                yield no, line, "", None, "expected 5 schedule fields and a command"
                continue
            schedule, rest = " ".join(toks[:5]), toks[5:]
        user = None
        if system:
            if not rest:
                yield no, schedule, "", None, "system crontab line needs a user and a command"
                continue
            user, rest = rest[0], rest[1:]
        yield no, schedule, " ".join(rest), user, None


def crontab_report(text, start, system, count):
    results, bad = [], False
    for no, schedule, command, user, err in parse_crontab(text, system):
        entry = {"line": no, "schedule": schedule, "command": command, "user": user, "valid": err is None}
        if err is None and schedule.lower() == "@reboot":
            entry.update(explanation="At system start (no schedule to compute)", next_runs=[])
        elif err is None:
            try:
                entry["explanation"] = explain(schedule)
                entry["next_runs"] = [dt.strftime("%Y-%m-%d %H:%M") for dt in next_runs(schedule, start, count)]
            except ValueError as exc:
                err = str(exc)
        if err is not None:
            entry.update(valid=False, error=err)
            bad = True
        results.append(entry)
    return results, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="Explain a cron expression and show its next runs.")
    ap.add_argument("expression", nargs="?", help='5-field cron expression or macro, e.g. "*/5 * * * *"')
    ap.add_argument("-n", "--count", type=int, default=5, help="number of runs to show (default 5)")
    ap.add_argument("--from", dest="start", help="start time 'YYYY-MM-DD HH:MM' (default: now)")
    ap.add_argument("--tz", help="time zone the schedule runs in, e.g. UTC or Europe/Istanbul (default: naive local time)")
    ap.add_argument("--show-in", help="also show the runs in this time zone")
    ap.add_argument("--summary", action="store_true", help="shortest/longest gap and runs per day over the next 500 runs")
    ap.add_argument("--crontab", metavar="FILE", help="validate and explain every job in a crontab file (- for stdin)")
    ap.add_argument("--system", action="store_true", help="with --crontab: lines have a user column (/etc/cron.d style)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    try:
        start = datetime.datetime.strptime(args.start, "%Y-%m-%d %H:%M") if args.start \
            else datetime.datetime.now()
        count = max(1, args.count)
        if args.crontab:
            text = sys.stdin.read() if args.crontab == "-" else open(args.crontab, encoding="utf-8", errors="replace").read()
            results, bad = crontab_report(text, start, args.system, count)
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                for r in results:
                    print("line %d: %s%s" % (r["line"], r["schedule"], "  ->  " + r["command"] if r["command"] else ""))
                    if not r["valid"]:
                        print("  INVALID: %s" % r["error"])
                        continue
                    print("  %s" % r["explanation"])
                    for t in r["next_runs"][:count]:
                        print("    next %s" % t)
                print("cronnext: %d job(s), %d invalid" % (len(results), sum(1 for r in results if not r["valid"])), file=sys.stderr)
            return 2 if bad else 0
        if not args.expression:
            ap.print_usage(sys.stderr)
            return 2
        run_zone = get_zone(args.tz) if args.tz else None
        show_zone = get_zone(args.show_in) if args.show_in else run_zone
        runs = next_runs(args.expression, start, max(count, 500) if args.summary else count)
        explanation = explain(args.expression)
        shown = []
        for dt in runs[:count]:
            entry = {"time": dt.strftime("%Y-%m-%d %H:%M"), "weekday": calendar.day_abbr[dt.weekday()]}
            if run_zone is not None:
                local, gap = to_zoned(dt, run_zone, show_zone)
                entry.update(time=local.strftime("%Y-%m-%d %H:%M %z"), weekday=calendar.day_abbr[local.weekday()],
                             dst_gap=gap)
            shown.append(entry)
        stats = gap_stats(runs) if args.summary else None
        if args.json:
            out = {"expression": args.expression, "explanation": explanation, "runs": shown}
            if stats:
                out["summary"] = stats
            print(json.dumps(out, indent=2))
        else:
            print(explanation)
            for e in shown:
                print("  %s %s%s" % (e["time"], e["weekday"], "  (DST gap: this wall-clock time does not exist)" if e.get("dst_gap") else ""))
            if stats:
                print("Over the next %d runs: shortest gap %s, longest gap %s, about %s run(s) per day" % (
                    stats["runs_examined"], fmt_minutes(stats["shortest_gap_minutes"]),
                    fmt_minutes(stats["longest_gap_minutes"]), stats["average_runs_per_day"]))
    except OSError as exc:
        print("cronnext: %s" % exc, file=sys.stderr)
        return 2
    except ValueError as exc:  # includes CronError
        print("cronnext: %s" % exc, file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
