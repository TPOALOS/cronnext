# Changelog

## 1.1.0

- Fix: day ranges ending in Sunday (`mon-sun`, `1-0`) were rejected as reversed
- `--crontab FILE` validates and explains every job (`--system` for /etc/cron.d files)
- `--tz` and `--show-in` with DST-gap detection
- `--summary` (shortest and longest gap, runs per day) and `--json`
- Installable with pip (`cronnext` command), CI on Linux and macOS

## 1.0.0

Initial release.
