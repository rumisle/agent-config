---
name: flights-cn
description: China domestic flight search — schedules, live fares with exact taxes, fare classes, baggage, seats left, refund/change fee tiers, a 2-month price calendar, and cheapest destinations from an airport. Backed by the ly.com (Tongcheng) web API, no key needed. Domestic routes only.
---

# flights-cn

`{baseDir}/flights.py` queries ly.com's flight endpoints. Prices are live CNY with
an exact tax breakdown, so nothing has to be estimated.

## Commands

```bash
flights.py search PEK SHA 2026-11-20                      # one date
flights.py search PEK SHA 2026-11-20 2026-11-21           # several dates
flights.py search PEK SHA 2026-11-20 --days 5             # 5 consecutive days
flights.py search PEK SHA 2026-11-20 --direct --max-price 900 --sort depart
flights.py calendar CAN CTU --start 2026-11-20 --days 60  # cheapest per date, ONE call
flights.py cabins PEK SHA 2026-11-20 CA1501               # fare classes + baggage
flights.py rules  PEK SHA 2026-11-20 CA1501 --fare 1      # refund / change fees
flights.py extras PEK SHA 2026-11-20 CA1501               # optional add-ons
flights.py deals  CAN                                     # cheapest destinations
flights.py resolve 昆山                                    # does a place have an airport
flights.py airports chengdu                               # IATA lookup (also pinyin)
```

`--json` works on every command. `--fare N` on `rules`/`extras` is the index printed
by `cabins` (default 0, the cheapest). Inventory opens roughly 5 months out; dates
beyond that return an empty list rather than an error.

## Taxes

`search` prints `total (fare + tax)`. Tax is read from the response, not guessed:

- `pt` — 民航发展基金, 50 CNY, flat for domestic adults
- `ot` — 燃油附加费, 40 CNY under 800 km / 70 CNY over, revised monthly by the CAAC

## Prefer `calendar` for date hunting

One request covers up to two months and returns only dates that actually have
service. Regional routes are often not daily (three departures a week is common at
small airports), so a single empty `search` never means "no route".

## Implementation notes

- The client GETs a search page first to obtain `__ftrace`/`__ftoken` cookies.
  Without them every endpoint returns HTTP 200 with an empty payload.
- Required headers: `Origin`, `Referer` (matching oneway page), `tcplat: 1`.
- Two response envelopes: `/getflightlist`-style uses `resCode`/`body`,
  `/book/*` uses `ErrorCode`(100 = ok)/`Data`.
- List fields: `lcp` lowest economy fare, `lcd` discount label, `lbcp` business,
  `lcn` seats left or cabin code, `stopNum`/`son`/`ssc`/`sd` stop details,
  `spantime` duration, `fRate` on-time rate.
- Fare classes need `flightno` + `newCabinDeal:1` in the same `/getflightlist`
  call. Identical fares repeat once per reselling agent, so they are deduped.
- `rules` and `extras` are keyed by a cabin's opaque `stag` token, which is why
  they re-fetch the flight first.
- Refund rules come back per passenger type (1 adult, 2 child, 3 infant);
  `--passenger` selects, default adult.

## Endpoint map

| Endpoint | Command |
|---|---|
| `/getflightlist` | `search`, and with `flightno` → `cabins` |
| `/getpricecalendar` | `calendar` |
| `/book/queryrefundrulewithflightinfo` | `rules` |
| `/book/saleproducts/cabins` | `extras` |
| `/query/getstartportlowestprice` | `deals` |
| `/home/queryflightnearbylist` | `resolve` |
| `/query/getallcityandairports` | `airports` |
| `/flightstopinfo` | not used — always returns `[]`; stop data is already in the flight list |

## Sources that do not work

Ctrip (`whaleguard block`), Ctrip mobile restapi (needs signing), Qunar touch API,
flightsfrom.com (Cloudflare). Google Flights has patchy China coverage and no
domestic fares.
