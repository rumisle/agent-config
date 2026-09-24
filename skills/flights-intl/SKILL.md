---
name: flights-intl
description: International flight search — itineraries with real prices in any currency, multi-airline connections, baggage allowance, round trips, cabin classes, and a price calendar. Backed by Kiwi.com's public GraphQL API, no key needed. Use for any route flights-cn cannot serve (that one is China-domestic only).
---

# flights-intl

`{baseDir}/flights.py` queries Kiwi.com's `umbrella/v2` GraphQL endpoint. No API
key, no request signing, and introspection is open, so the schema can be explored
directly when a new field is needed.

## Commands

```bash
flights.py search LON NYC 2026-09-15                     # one date
flights.py search LON NYC 2026-09-15 --days 5            # 5 consecutive days
flights.py search LON NYC 2026-09-15 --back 2026-09-22   # round trip
flights.py search LON NYC 2026-09-15 --max-stops 0 --max-price 4000 --sort duration
flights.py calendar LON NYC --start 2026-09-01 --days 30 # cheapest per date
flights.py places Bangkok                                # resolve to a Kiwi id
```

Global flags: `--json`, `--currency cny|usd|eur|...`, `--locale`, `--adults N`,
`--cabin economy|premium|business|first`, `--exact`.

## Place resolution

Terms are resolved through Kiwi's `places` query and accept IATA codes, English
names, or Chinese names. **An IATA code expands to its whole city by default**, so
`PVG` searches all Shanghai airports; pass `--exact` to pin one airport. The
resolved ids are printed in the header of every result.

## Notes

- **Prices are the total for the whole party, taxes included** — not per passenger.
  With `--adults 3` the header shows `CNY 3497 (1166 x3)`. Same for `calendar`.
- Baggage counts come back for the party too; the renderer divides them, so
  `bags 1cabin+0checked` is per person. Low-cost carriers usually show `0checked`.
- `--max-stops 0` matters: unrestricted searches happily return 2-stop, 20-hour
  itineraries that undercut a nonstop by a little.
- Kiwi mixes carriers into self-transfer itineraries that airlines will not
  through-check. Treat multi-carrier connections as needing separate check-in.
- `sortBy` accepts PRICE, DURATION, QUALITY (exposed as `--sort`); the schema also
  has POPULARITY and per-leg takeoff/landing sorts.

## Schema pointers

Explore further with introspection, e.g.
`{__type(name:"ItinerariesFilterInput"){inputFields{name}}}`.

- Queries: `onewayItineraries`, `returnItineraries`, `multicityItineraries`,
  `nomadItineraries`, `itineraryPricesCalendar`, `itineraryPriceGraph`,
  `itineraryPricesMap`, `places`, `seatInfo`.
- `onewayItineraries(search, filter, options)` returns the union
  `Itineraries | AppError`; always select `__typename` and `... on AppError{message}`.
- `options.partner` is required — `skypicker` works.
- Dates are `DateTime`, not `Date`: `2026-09-15T00:00:00`, and a single day is
  expressed as a start/end range. Dates more than 3 years out are rejected.
- No rate limiting observed: 12 sequential and 8 parallel searches all succeeded.

## Why not the alternatives

Ctrip and Qunar block outright. Tongcheng's international stack is separate from
its domestic one (`/miflightapi/ts/list`) and is signature-protected — it answers
`{"code":444,"message":"非法链接"}` without a token from its anti-bot SDK.
Skyscanner serves a captcha, Travelpayouts needs a key, and Google Flights has no
prices for most Chinese carriers.
