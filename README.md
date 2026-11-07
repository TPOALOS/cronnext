# cronnext

Validate a cron expression, get a plain-English explanation, and see its next run times.
One file, standard library only, **no `croniter` or other dependency**.

```bash
python3 cronnext.py "*/15 9-17 * * mon-fri" -n 3
python3 cronnext.py "@daily" --from "2030-01-04 16:50"
python3 cronnext.py "0 9 * * *" --tz UTC --show-in Europe/Istanbul     # when does a UTC job run for me?
python3 cronnext.py "*/7 * * * *" --summary                         # shortest/longest gap, runs per day
crontab -l | python3 cronnext.py --crontab -                         # validate and explain every job
python3 cronnext.py --crontab /etc/cron.d/backup --system --json     # system crontab (user column)
# or: pip install git+https://github.com/TPOALOS/cronnext && cronnext "*/5 * * * *"
```

Example output:

```
Every 15 minutes, past hour 9 through 17, on Monday through Friday
  2030-01-04 17:00 Fri
  2030-01-04 17:15 Fri
  2030-01-04 17:30 Fri
```

## Supported syntax

- Five fields: `minute hour day-of-month month day-of-week`
- `*`, lists (`1,15`), ranges (`1-5`), steps (`*/10`, `10-30/5`, `5/20`)
- Month names (`jan-mar`) and day names (`mon-fri`); day-of-week `7` means Sunday
- Macros: `@yearly`, `@annually`, `@monthly`, `@weekly`, `@daily`, `@midnight`, `@hourly`
- Classic cron rule: if both day-of-month and day-of-week are restricted, a day runs
  when **either** matches (the explanation says so)

`mon-sun` and `1-0` mean Monday through Sunday (Sunday written as 0 or 7). In a crontab file `@reboot` is accepted and
reported as "at system start".

Not supported: seconds fields and `L`/`W`/`#` extensions. Without `--tz`, times are naive local time.

Invalid expressions print a clear message (for example `minute: 60 is outside 0-59`) and
exit with code `2`. Impossible dates such as `0 0 31 2 *` are detected instead of looping.

| Option | Meaning |
|--------|---------|
| `-n, --count N` | how many runs to show (default 5) |
| `--from "YYYY-MM-DD HH:MM"` | start time (default: now); results are strictly after it |
| `--tz ZONE` | the time zone the schedule runs in (IANA name); runs are shown with their UTC offset, and wall-clock times that do not exist because of a DST jump are marked |
| `--show-in ZONE` | show the runs converted to another zone |
| `--summary` | shortest and longest gap and average runs per day over the next 500 runs |
| `--crontab FILE` | validate and explain every job of a crontab (`-` for stdin); exit `2` if any line is invalid; `--system` for `/etc/cron.d` files with a user column |
| `--json` | machine-readable output |

## Tests

```bash
python3 -m unittest -v
```

## License

MIT (c) TPOALOS
