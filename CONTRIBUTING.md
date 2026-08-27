# Contributing

Thanks for considering a contribution. This is a small, personal-scale
project (a family flight tracker), so the bar is "clear and tested," not
"enterprise process."

## Setting up

```bash
git clone <this repo>
cd "flight tracker"
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in a real `TELEGRAM_BOT_TOKEN` and
`AVIATIONSTACK_API_KEY` only if you intend to actually run the bot — the
test suite never needs either (every test that would otherwise touch the
network stubs it out; a `no_network` fixture makes an unstubbed
`requests.get` call fail loudly instead of silently succeeding).

## Running the checks

```bash
pytest                 # full test suite
ruff check .            # lint
ruff format .           # formatting (matches CI)
mypy --strict .          # type checking
```

All four run in CI on every pull request (`.github/workflows/ci.yml`), along
with a Docker build. Please run them locally before opening a PR — it's
faster for everyone than a CI round-trip.

## Ground rules (see `CLAUDE.md` for the full detail)

- **No bare `except:`, no `print()`** — use the `logging` module.
- **Business logic never imports from `telegram/`-shaped modules.** Command
  handlers in `bot.py` should stay thin; put logic in a plain module
  (`change_detection.py`, `scheduler.py`, `storage/`, ...) so it's testable
  without a fake Telegram `Update`.
- **`chat_id` is the tenant boundary.** No new code path should be able to
  read or write another chat's data.
- **Never alert twice, never alert on missing data.** If you're touching
  `change_detection.py` or `bot.py`'s `check_all_flights`, re-read
  `ARCHITECTURE.md`'s "Exact conditions under which an alert fires" section
  first — this is the part of the codebase most likely to have a subtle,
  hard-to-notice regression.
- **Don't invent a provider's response shape.** If you're adding or
  changing a `providers/` module, work from that provider's real
  documentation or a recorded fixture, not a guess.
- **Write a test in the same commit as the code it covers.** A `FakeProvider`
  (`providers/fake.py`) exists specifically so provider-facing tests don't
  need real network access.

## Reporting a bug

Please include: what you expected, what happened instead, and (if it's
alert-related) the relevant lines from the bot's JSON logs — they're
structured with a `correlation_id` per poll cycle, so one cycle's worth of
lines usually tells the whole story. Never paste your `TELEGRAM_BOT_TOKEN`
or `AVIATIONSTACK_API_KEY` into an issue; the logger redacts them
automatically, but copy-pasting your `.env` directly would bypass that.

## Project history

This codebase went through a structured hardening pass (`HARDENING_PLAN.md`,
`PROGRESS.md`, `FINDINGS.md`, `ARCHITECTURE.md`) before its first public
release. If you're trying to understand *why* something works the way it
does, those files are usually a faster answer than `git blame`.
