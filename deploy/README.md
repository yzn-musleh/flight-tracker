# Running without Docker (systemd)

An alternative to `docker-compose.yml` for a plain Linux host (a Raspberry
Pi, an old PC, or a VPS).

1. Create a dedicated, unprivileged user and install location:
   ```bash
   sudo useradd --system --create-home --home-dir /opt/flight-tracker --shell /usr/sbin/nologin flighttracker
   sudo -u flighttracker git clone <this repo> /opt/flight-tracker
   ```
2. Set up the virtualenv and dependencies as that user:
   ```bash
   sudo -u flighttracker python3 -m venv /opt/flight-tracker/.venv
   sudo -u flighttracker /opt/flight-tracker/.venv/bin/pip install -r /opt/flight-tracker/requirements.txt
   ```
3. Copy `.env.example` to `.env` in `/opt/flight-tracker` and fill it in
   (owned by `flighttracker`, not world-readable — it holds your bot token
   and API key):
   ```bash
   sudo -u flighttracker cp /opt/flight-tracker/.env.example /opt/flight-tracker/.env
   sudo chmod 600 /opt/flight-tracker/.env
   ```
4. Install and enable the unit:
   ```bash
   sudo cp flight-tracker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now flight-tracker
   ```
5. Check it's running and read logs (structured JSON, one line per event —
   see `logging_config.py`):
   ```bash
   sudo systemctl status flight-tracker
   sudo journalctl -u flight-tracker -f
   ```

`flight-tracker.service` assumes `/opt/flight-tracker` for both the install
and the systemd `User`/`WorkingDirectory` — edit the unit file if you use a
different path or username. `DB_PATH`/`LOCK_PATH` default to `flights.db`/
`bot.lock` inside `WorkingDirectory` when not set in `.env`, so no extra
directories need creating beyond the clone itself.
