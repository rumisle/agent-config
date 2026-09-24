#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""International flight search via Kiwi.com's public GraphQL API."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import httpx

ENDPOINT = "https://api.skypicker.com/umbrella/v2/graphql"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

SEGMENT = """
  segment {
    code duration cabinClass
    carrier { code name }
    operatingCarrier { code name }
    source { localTime station { code name } }
    destination { localTime station { code name } }
  }
"""

ITINERARY = f"""
  id duration
  price {{ amount }}
  bagsInfo {{ includedHandBags includedCheckedBags includedPersonalItem }}
"""

Q_ONEWAY = f"""
query ($search: SearchOnewayInput, $filter: ItinerariesFilterInput,
       $options: ItinerariesOptionsInput) {{
  onewayItineraries(search: $search, filter: $filter, options: $options) {{
    __typename
    ... on AppError {{ message }}
    ... on Itineraries {{
      itineraries {{
        {ITINERARY}
        ... on ItineraryOneWay {{ sector {{ sectorSegments {{ {SEGMENT} }} }} }}
      }}
    }}
  }}
}}"""

Q_RETURN = f"""
query ($search: SearchReturnInput, $filter: ItinerariesFilterInput,
       $options: ItinerariesOptionsInput) {{
  returnItineraries(search: $search, filter: $filter, options: $options) {{
    __typename
    ... on AppError {{ message }}
    ... on Itineraries {{
      itineraries {{
        {ITINERARY}
        ... on ItineraryReturn {{
          outbound {{ sectorSegments {{ {SEGMENT} }} }}
          inbound {{ sectorSegments {{ {SEGMENT} }} }}
        }}
      }}
    }}
  }}
}}"""

Q_CALENDAR = """
query ($search: SearchPricesCalendarInput, $options: ItinerariesOptionsInput) {
  itineraryPricesCalendar(search: $search, options: $options) {
    __typename
    ... on AppError { message }
    ... on ItineraryPricesCalendar {
      calendar { date ratedPrice { price { amount } rating } }
    }
  }
}"""

Q_PLACES = """
query ($term: String!, $locale: Locale) {
  places(search: {term: $term}, filter: {onlyTypes: [AIRPORT, CITY]},
         options: {locale: $locale}, first: 8) {
    ... on PlaceConnection {
      edges { node {
        __typename id
        ... on City { name country { name } }
        ... on Station { name code city { id name country { name } } }
      } }
    }
  }
}"""

CABINS = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY",
          "business": "BUSINESS", "first": "FIRST_CLASS"}


class ApiError(RuntimeError):
    pass


class Client:
    """Kiwi.com umbrella GraphQL. No key, no signing, introspection is open."""

    def __init__(self, currency: str = "cny", locale: str = "en",
                 exact: bool = False, timeout: float = 60.0) -> None:
        self.currency = currency
        self.locale = locale
        self.exact = exact
        self._http = httpx.Client(
            headers={"User-Agent": UA, "Origin": "https://www.kiwi.com",
                     "Referer": "https://www.kiwi.com/"},
            timeout=timeout,
        )
        self._places: dict[str, dict] = {}

    def close(self) -> None:
        self._http.close()

    def query(self, doc: str, variables: dict) -> dict:
        r = self._http.post(ENDPOINT, json={"query": doc, "variables": variables})
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise ApiError(payload["errors"][0]["message"])
        return payload["data"]

    @property
    def options(self) -> dict:
        return {"partner": "skypicker", "currency": self.currency,
                "locale": self.locale}

    def places(self, term: str) -> list[dict]:
        if not term.strip():
            raise ApiError("empty place term")
        data = self.query(Q_PLACES, {"term": term, "locale": self.locale})
        return [e["node"] for e in data["places"]["edges"]]

    def resolve(self, term: str) -> dict:
        """Turn 'PVG', 'Tokyo' or '东京' into a Kiwi place node.

        Defaults to the whole city so a metro area's airports are all searched:
        'PVG' becomes Shanghai unless --exact pins it to Pudong.
        """
        if term in self._places:
            return self._places[term]
        hits = self.places(term)
        if not hits:
            raise ApiError(f"no place matches {term!r}")
        station = next((h for h in hits if h.get("code") == term.upper()), None)
        if station and (self.exact or not (station.get("city") or {}).get("id")):
            node = station
        elif station:
            city = station["city"]
            node = {"__typename": "City", "id": city["id"], "name": city["name"]}
        else:
            cities = [h for h in hits if h["__typename"] == "City"]
            node = (cities or hits)[0]
        self._places[term] = node
        return node

    def search(self, src: dict, dst: dict, day: str, back: str | None,
               adults: int, cabin: str, limit: int, max_stops: int | None,
               sort: str) -> list[dict]:
        itinerary = {
            "source": {"ids": [src["id"]]},
            "destination": {"ids": [dst["id"]]},
            "outboundDepartureDate": day_range(day),
        }
        if back:
            itinerary["inboundDepartureDate"] = day_range(back)
        search = {
            "itinerary": itinerary,
            "passengers": {"adults": adults},
            "cabinClass": {"cabinClass": CABINS[cabin]},
        }
        filt: dict = {"limit": limit}
        if max_stops is not None:
            filt["maxStopsCount"] = max_stops
        options = self.options | {"sortBy": sort.upper()}
        doc, root = (Q_RETURN, "returnItineraries") if back else (
            Q_ONEWAY, "onewayItineraries")
        res = self.query(doc, {"search": search, "filter": filt,
                               "options": options})[root]
        if res["__typename"] == "AppError":
            raise ApiError(res.get("message") or "search failed")
        return res["itineraries"] or []

    def calendar(self, src: dict, dst: dict, start: str, end: str,
                 adults: int, cabin: str) -> list[dict]:
        search = {
            "source": {"ids": [src["id"]]},
            "destination": {"ids": [dst["id"]]},
            "dates": {"start": f"{check_date(start)}T00:00:00",
                      "end": f"{check_date(end)}T23:59:59"},
            "passengers": {"adults": adults},
            "cabinClass": {"cabinClass": CABINS[cabin]},
        }
        res = self.query(Q_CALENDAR, {"search": search,
                                      "options": self.options})["itineraryPricesCalendar"]
        if res["__typename"] == "AppError":
            raise ApiError(res.get("message") or "calendar failed")
        return res["calendar"] or []


def day_range(day: str) -> dict:
    return {"start": f"{check_date(day)}T00:00:00", "end": f"{day}T23:59:59"}


def check_date(day: str) -> str:
    """Fail loudly on a bad date instead of letting the API 400."""
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        raise ApiError(f"invalid date {day!r}, expected YYYY-MM-DD") from None


# -- models ----------------------------------------------------------------

@dataclass
class Leg:
    flight: str
    carrier: str
    operated_by: str | None
    from_code: str
    from_time: str
    to_code: str
    to_time: str
    duration_min: int
    cabin: str


@dataclass
class Sector:
    legs: list[Leg]
    depart: str
    arrive: str
    stops: int
    via: list[str]


@dataclass
class Itinerary:
    price: float          # total for the whole party, taxes included
    price_each: float
    passengers: int
    currency: str
    duration_min: int
    hand_bags: int | None
    checked_bags: int | None
    sectors: list[Sector] = field(default_factory=list)


def parse_leg(raw: dict) -> Leg:
    s = raw["segment"]
    op = (s.get("operatingCarrier") or {}).get("code")
    return Leg(
        flight=f"{s['carrier']['code']}{s['code']}",
        carrier=s["carrier"]["name"],
        operated_by=op if op and op != s["carrier"]["code"] else None,
        from_code=s["source"]["station"]["code"],
        from_time=s["source"]["localTime"][11:16],
        to_code=s["destination"]["station"]["code"],
        to_time=s["destination"]["localTime"][11:16],
        duration_min=(s.get("duration") or 0) // 60,
        cabin=(s.get("cabinClass") or "").lower(),
    )


def parse_sector(raw: dict) -> Sector:
    legs = [parse_leg(x) for x in raw["sectorSegments"]]
    return Sector(
        legs=legs,
        depart=legs[0].from_time,
        arrive=legs[-1].to_time,
        stops=len(legs) - 1,
        via=[l.to_code for l in legs[:-1]],
    )


def parse_itinerary(raw: dict, currency: str, passengers: int = 1) -> Itinerary:
    bags = raw.get("bagsInfo") or {}
    total = float(raw["price"]["amount"])
    sectors = []
    if raw.get("sector"):
        sectors.append(parse_sector(raw["sector"]))
    for key in ("outbound", "inbound"):
        if raw.get(key):
            sectors.append(parse_sector(raw[key]))
    return Itinerary(
        price=total,
        price_each=round(total / max(passengers, 1), 2),
        passengers=passengers,
        currency=currency.upper(),
        duration_min=(raw.get("duration") or 0) // 60,
        hand_bags=bags.get("includedHandBags"),
        checked_bags=bags.get("includedCheckedBags"),
        sectors=sectors,
    )


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def render(it: Itinerary) -> list[str]:
    # bag counts come back for the whole party, like the price
    n = max(it.passengers, 1)
    bags = f"{(it.hand_bags or 0) // n}cabin+{(it.checked_bags or 0) // n}checked"
    each = f" ({it.price_each:.0f} x{it.passengers})" if it.passengers > 1 else ""
    head = (f"  {it.currency} {it.price:>8.0f}{each}  {hm(it.duration_min):>7}"
            f"  bags {bags}")
    lines = [head]
    for sec in it.sectors:
        stops = "nonstop" if not sec.stops else f"{sec.stops} stop via {','.join(sec.via)}"
        legs = "  ".join(
            f"{l.flight} {l.from_code}{l.from_time}-{l.to_code}{l.to_time}"
            + (f"(op {l.operated_by})" if l.operated_by else "")
            for l in sec.legs
        )
        lines.append(f"      {stops:<24} {legs}")
    return lines


# -- commands --------------------------------------------------------------

def cmd_search(c: Client, a: argparse.Namespace) -> None:
    src, dst = c.resolve(a.dep), c.resolve(a.arr)
    out: dict[str, list] = {}
    for day in expand_dates(a.dates, a.days):
        raw = c.search(src, dst, day, a.back, a.adults, a.cabin, a.limit,
                       a.max_stops, a.sort)
        items = [parse_itinerary(r, c.currency, a.adults) for r in raw]
        if a.max_price:
            items = [i for i in items if i.price <= a.max_price]
        out[day] = [asdict(i) for i in items]
        if not a.json:
            trip = f" / back {a.back}" if a.back else ""
            print(f"{src['id']} -> {dst['id']}  {day}{trip}  "
                  f"({len(items)} results, {c.currency.upper()})")
            for i in items:
                print("\n".join(render(i)))
            print()
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_calendar(c: Client, a: argparse.Namespace) -> None:
    src, dst = c.resolve(a.dep), c.resolve(a.arr)
    start = check_date(a.start) if a.start else date.today().isoformat()
    end = check_date(a.end) if a.end else (
        date.fromisoformat(start) + timedelta(days=a.days)).isoformat()
    rows = c.calendar(src, dst, start, end, a.adults, a.cabin)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    prices = [float(r["ratedPrice"]["price"]["amount"]) for r in rows]
    cheapest = min(prices) if prices else 0
    print(f"{src['id']} -> {dst['id']}  {start} .. {end}  "
          f"({len(rows)} days, cheapest {c.currency.upper()} {cheapest:.0f})")
    for r in rows:
        p = float(r["ratedPrice"]["price"]["amount"])
        mark = " <-- cheapest" if p == cheapest else ""
        print(f"  {r['date'][:10]}  {p:>8.0f}{mark}")


def cmd_places(c: Client, a: argparse.Namespace) -> None:
    hits = c.places(a.query)
    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return
    for h in hits:
        city = (h.get("city") or {}).get("name") or h.get("name")
        country = ((h.get("country") or (h.get("city") or {}).get("country")) or {})
        print(f"  {h['id']:<28} {h.get('name', ''):<38} "
              f"{city}, {country.get('name', '')}")


def expand_dates(dates: list[str], days: int | None) -> list[str]:
    if days:
        start = date.fromisoformat(check_date(dates[0])) if dates else date.today()
        return [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return [check_date(d) for d in dates] or [date.today().isoformat()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--currency", default="cny")
    p.add_argument("--locale", default="en")
    p.add_argument("--adults", type=int, default=1)
    p.add_argument("--cabin", choices=CABINS, default="economy")
    p.add_argument("--exact", action="store_true",
                   help="treat an IATA code as that airport, not its whole city")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="itineraries for one or more dates")
    s.add_argument("dep"); s.add_argument("arr")
    s.add_argument("dates", nargs="*", metavar="DATE")
    s.add_argument("--days", type=int, help="N consecutive days from first DATE")
    s.add_argument("--back", metavar="DATE", help="return date (round trip)")
    s.add_argument("--max-stops", type=int)
    s.add_argument("--max-price", type=float)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--sort", choices=("price", "duration", "quality"),
                   default="price")
    s.set_defaults(fn=cmd_search)

    c = sub.add_parser("calendar", help="cheapest fare per date over a range")
    c.add_argument("dep"); c.add_argument("arr")
    c.add_argument("--start"); c.add_argument("--end")
    c.add_argument("--days", type=int, default=30)
    c.set_defaults(fn=cmd_calendar)

    l = sub.add_parser("places", help="resolve a city or airport to a Kiwi id")
    l.add_argument("query")
    l.set_defaults(fn=cmd_places)
    return p


def main() -> None:
    a = build_parser().parse_args()
    c = Client(currency=a.currency, locale=a.locale, exact=a.exact)
    try:
        a.fn(c, a)
    except (ApiError, httpx.HTTPError) as e:
        sys.exit(f"error: {e}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
