---
name: Bug report
about: Something isn't working the way it should
title: ""
labels: bug
---

**What happened**


**What you expected instead**


**Steps to reproduce**
1.
2.
3.

**Environment**
- Running via: Docker / systemd / `python bot.py` directly
- Provider (`FLIGHT_PROVIDER`): aviationstack / other
- Long polling or `WEBHOOK_MODE=true`?

**Relevant log lines**
The bot logs structured JSON with a `correlation_id` per poll cycle — please
paste the full cycle around when this happened, not just one line.

```
(paste here)
```

**Never paste your `.env`, `TELEGRAM_BOT_TOKEN`, or `AVIATIONSTACK_API_KEY`.**
The logger redacts secrets automatically in its own output, but a raw `.env`
paste would bypass that.
