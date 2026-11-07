#!/usr/bin/env python3
"""cronnext - validate a cron expression, explain it, and list its next run times.

Standard library only (no croniter). Times are naive local time.
Exit code 0 = valid, 2 = invalid expression.

    python3 cronnext.py "*/15 9-17 * * mon-fri" -n 5
"""
import argparse
import calendar
import datetime
import sys

__version__ = "1.0.0"

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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Explain a cron expression and show its next runs.")
    ap.add_argument("expression", help='5-field cron expression or macro, e.g. "*/5 * * * *"')
    ap.add_argument("-n", "--count", type=int, default=5, help="number of runs to show (default 5)")
    ap.add_argument("--from", dest="start", help="start time 'YYYY-MM-DD HH:MM' (default: now)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    try:
        start = datetime.datetime.strptime(args.start, "%Y-%m-%d %H:%M") if args.start \
            else datetime.datetime.now()
        print(explain(args.expression))
        for dt in next_runs(args.expression, start, max(1, args.count)):
            print("  %s %s" % (dt.strftime("%Y-%m-%d %H:%M"), calendar.day_abbr[dt.weekday()]))
    except ValueError as exc:  # includes CronError
        print("cronnext: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
