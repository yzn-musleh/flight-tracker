## What does this change?


## Why?


## Testing

- [ ] Added/updated tests in the same commit as the code they cover
- [ ] `pytest` passes locally
- [ ] `ruff check .` and `ruff format --check .` pass locally
- [ ] `mypy --strict .` passes locally
- [ ] If this touches `providers/`: verified against the real provider's
      docs or a recorded fixture (not invented)
- [ ] If this touches alert logic (`change_detection.py`, `check_all_flights`):
      re-read `ARCHITECTURE.md`'s "Exact conditions under which an alert
      fires" and confirmed dedupe/null-guard/tenant-isolation still hold

## Anything reviewers should look at closely?
