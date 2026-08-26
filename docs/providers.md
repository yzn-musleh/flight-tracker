# Flight data provider comparison

Written for HARDENING_PLAN.md's Phase 2. **Aviationstack remains the default
provider in code** — this is research and a recommendation, not a migration.
Switching providers is a config change (`FLIGHT_PROVIDER` env var) plus
writing one new `providers/<name>.py` module implementing the
`FlightProvider` Protocol (`providers/base.py`); nothing else in the codebase
needs to change.

All figures below were checked against each vendor's own live pages on
**2026-08-27** (URLs cited per row). Where I could not find a number on the
vendor's own site, I say so explicitly rather than estimate — a wrong quota
number here is worse than an admitted gap, since `MONTHLY_REQUEST_CAP` and
every backoff/tier knob in `scheduler.py` exist specifically to survive
whatever the real number is.

## Current baseline: Aviationstack

- **Free tier: 100 requests/month**, confirmed today at
  https://aviationstack.com/pricing (no published rate limit or endpoint
  restriction beyond the monthly cap; "Full Aviation Data", "Real-Time
  Flights", HTTPS).
- No push/webhook alerts of any kind — polling only, which is the entire
  reason this codebase's scheduler tiering/backoff machinery exists.
- 100 requests/month is roughly 3/day for the whole system — the actual
  constraint this project has been designed around since day one (see
  `README.md`'s original framing, `HARDENING_PLAN.md`'s Phase 2 note).

## Comparison

| Provider | Free tier (verified today) | Flight-status-by-number lookup | Push/webhook alerts | Notes |
|---|---|---|---|---|
| **Aviationstack** (current) | 100 requests/month | Yes (`/v1/flights?flight_iata=`) | No | Baseline above. |
| **AeroDataBox** | 600 "API units"/month, 1 req/s, via RapidAPI/API.market ([pricing](https://www.aerodatabox.com/get-started/pricing)) | Yes, a flight-by-number endpoint exists ([aerodatabox.com/api](https://aerodatabox.com/api)) | **Yes** — "Flight Alert API": you subscribe a flight/airport to a webhook URL and AeroDataBox pushes updates to it ([aerodatabox.com/flight-alert-api-2026](https://aerodatabox.com/flight-alert-api-2026/)) | Units ≠ requests: each endpoint has a per-call unit cost (Tier 1–3, i.e. 1/2/6 units), so 600 units/month is *not* 600 lookups/month. **I could not verify the flight-by-number endpoint's specific unit tier from a live, accessible doc page** (the specific endpoint-reference URL I tried returned HTTP 403); treat "600 units" as an upper bound on lookups, not the actual count. The Flight Alert API itself moved to a credit-based, pay-per-alert-sent model as of the 2026 transition described on the page above — alert *creation* is free, each alert *delivered* costs credits. |
| **FlightAware AeroAPI** (v4, current) | "Personal" tier: up to **$5 of usage-credit free per month**, no monthly minimum, capped at 10 result sets/minute ([flightaware.com/commercial/aeroapi](https://www.flightaware.com/commercial/aeroapi/)) | Yes, `/flights/{ident}` | **Yes** — named "Push Alert Delivery"/"Alert delivery callback", billed per result set delivered (found via search citing FlightAware's own pricing language; **I could not load per-query dollar pricing from a live page** — the v3 pricing page I could fetch is explicitly EOL/deprecated (superseded in 2023) and not representative of current v4 pricing, so I'm not quoting its numbers) | The "$5 free/month, no minimum" framing is fundamentally different from a fixed request count — it's usage-based, so "how many lookups is that" depends on per-query pricing I couldn't pin down from a live source. This is the biggest gap in this table; don't treat FlightAware as quantified until someone confirms current per-query cost directly (e.g. by creating a developer account, which I was not able to do here). |
| **Aviation Edge** | **None currently** — confirmed today on the vendor's own page: *"Due to abuse of our Free API keys, we have decided to no longer offer this feature."* ([aviation-edge.com/free-api-key](https://aviation-edge.com/free-api-key/)) | Yes (Flight Tracker API), but only on a paid plan | Not found on any page I could fetch | Cheapest paid entry point is a **discounted first month** ($7–$39 depending on tier), then $299–$1,499/month ongoing ([aviation-edge.com/premium-api](https://aviation-edge.com/premium-api/)). Rules this out for a free/hobby deployment entirely — there is no free tier to fall back to at all. |
| **OpenSky Network** | 400 credits/day anonymous, 4,000 credits/day for a registered (OAuth2) user, more for ADS-B feeders ([opensky-api docs](https://openskynetwork.github.io/opensky-api/rest.html)) | **No** — OpenSky has no flight-number/callsign lookup endpoint at all. It exposes raw ADS-B state vectors (position, altitude, velocity by aircraft ICAO24 address) and airport arrival/departure lists by time window, not a "flight status" record with gate/delay/terminal fields. | No | Wrong shape of data for this bot regardless of quota — there's no gate, delay, or terminal information in ADS-B state vectors, and matching a tracked `(flight_iata, date)` to an ICAO24 address and time window would be a significant, fragile reimplementation of flight-matching logic AeroDataBox/Aviationstack/FlightAware/Aviation Edge already do server-side. Included here only because the Phase 2 prompt named it explicitly. |

## Recommendation

**Move to AeroDataBox if/when a provider switch happens; keep Aviationstack
as the default until then.**

Reasoning:

1. **It has real push alerts on the same tier that has a usable free quota.**
   That's the one combination in this table that actually exists — FlightAware
   also has alerts, but I could not confirm its Personal tier's per-query cost
   is small enough to be practically free the way AeroDataBox's flat 600
   units/month is; Aviation Edge has no free tier at all; OpenSky has no
   alerts and isn't the right data shape regardless. If the alerts genuinely
   work as documented, per `HARDENING_PLAN.md`'s own framing this "deletes
   all" of the quota-survival machinery (`scheduler.py`'s tiering/backoff,
   `MONTHLY_REQUEST_CAP`, the safety-margin warning) for any flight subscribed
   through it, since the bot would be notified instead of polling.
2. **It's a strict upgrade on the polling path too**, even ignoring alerts:
   free-tier AeroDataBox is unit-based rather than a flat request count, and
   even a conservative reading (worst case, every lookup costs the most
   expensive Tier-3 rate of 6 units) gives 100 lookups/month — the same as
   Aviationstack today — with headroom above that if the actual endpoint is
   cheaper, which is likely for a single-flight-by-number lookup rather than
   a bulk/history query.
3. **What would need to happen before actually switching** (do not skip
   these — this recommendation is not yet fully verified):
   - Confirm the exact unit cost of the flight-by-number endpoint directly
     against `doc.aerodatabox.com` or a RapidAPI test call — I could not load
     the specific endpoint-reference page in this session (HTTP 403), so this
     recommendation's unit-cost claim is a bound, not a confirmed figure.
   - Get a real API key and test whether the Flight Alert API's webhook
     delivery actually requires a public HTTPS endpoint reachable from
     AeroDataBox's servers — this project's `README.md` already mentions a
     Cloudflare Tunnel setup for Telegram webhook mode (Phase 6), so the
     infrastructure need not be new, but it needs confirming for this
     specific vendor's webhook format/auth.
   - Re-read the Flight Alert API's 2026 credit-based transition details
     end-to-end (the page describes a pricing model change with a
     transition deadline) to make sure the "free creation, pay per alert
     sent" model doesn't have a floor that makes it worse than Aviationstack
     for a low-volume family-flight-count use case.

**Do not switch to Aviation Edge** (no free tier at all as of today) **or
OpenSky** (wrong data shape — no flight-status-by-number lookup, no gate/
delay/terminal fields, no alerts) for this project.

## What I could not verify, stated plainly

- AeroDataBox's exact unit cost for its flight-by-number endpoint (the
  documentation page for that specific endpoint returned HTTP 403 when
  fetched in this session).
- FlightAware AeroAPI's current per-query dollar price for `/flights/{ident}`
  under the Personal tier (the only pricing page I could fetch with concrete
  per-query numbers was the v3 pricing page, which FlightAware's own content
  says is deprecated/EOL and not representative of current v4 pricing — so I
  am deliberately not quoting it).
- Whether any of these vendors' *actual* rate limiting/quota enforcement
  matches their published numbers in practice (that would require a live API
  key and real traffic against each one, which is out of scope here — no
  signups, no paid plans, per the phase's hard stops).
