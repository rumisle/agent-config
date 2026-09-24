#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""China domestic flight search via the ly.com (Tongcheng) web API."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import httpx

BASE = "https://www.ly.com/flights/api"
PAGE = "https://www.ly.com/flights/itinerary/oneway/{dep}-{arr}?date={date}"
HOME = "https://www.ly.com/flights/home"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

AIRPORT_FEE_KEY = "pt"  # 民航发展基金, 50 CNY flat for domestic adults
FUEL_FEE_KEY = "ot"     # 燃油附加费, 40 short-haul / 70 long-haul, revised monthly


class ApiError(RuntimeError):
    pass


# -- client ----------------------------------------------------------------

class Client:
    """Thin wrapper over the ly.com flight endpoints.

    Every endpoint returns HTTP 200 with an empty payload until the session has
    picked up the __ftrace/__ftoken cookies handed out by a search page, so the
    first call transparently primes them.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True
        )
        self._primed = False

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, payload: dict, referer: str = HOME) -> dict:
        if not self._primed:
            self._http.get(PAGE.format(dep="PEK", arr="SHA", date="2030-01-01"))
            self._primed = True
        r = self._http.post(
            BASE + path,
            json=payload,
            headers={"Origin": "https://www.ly.com", "Referer": referer,
                     "tcplat": "1"},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("resCode") not in (0, None):
            raise ApiError(f"{path}: {data.get('resDesc')}")
        # /book/* endpoints answer with a flat ErrorCode/Data envelope instead
        if "Data" in data or "ErrorCode" in data:
            if data.get("ErrorCode") not in (100, 0, None):
                raise ApiError(f"{path}: {data.get('ErrorMsg')}")
            return data.get("Data") or {}
        return data.get("body") or {}

    def flight_list(self, dep: str, arr: str, day: str, flight_no: str = "") -> dict:
        """Flights for a date; pass flight_no to expand that flight's fare classes."""
        day = check_date(day)
        payload = {
            "Departure": dep, "Arrival": arr, "DepartureDate": day,
            "GetType": "1", "QueryType": "1", "IsBaby": 0,
            "fromairport": "", "toairport": "",
            "DepartureName": "", "ArrivalName": "",
            "DepartureFilter": "", "ArrivalFilter": "",
            "paging": {"dataflag": "all", "cid": ""},
        }
        if flight_no:
            payload |= {"flightno": flight_no, "newCabinDeal": "1", "IsBook15": "1"}
        return self._post("/getflightlist", payload,
                          PAGE.format(dep=dep, arr=arr, date=day))

    def price_calendar(self, dep: str, arr: str, start: str, end: str) -> list[dict]:
        """Cheapest fare per date over a range, one request, service days only."""
        body = self._post(
            "/getpricecalendar",
            {"StartPort": dep, "EndPort": arr, "QueryBegDate": check_date(start),
             "QueryEndDate": check_date(end), "QueryType": 1, "travelTypes": [1]},
            PAGE.format(dep=dep, arr=arr, date=start),
        )
        return body.get("fzpriceinfos") or []

    def fare_rules(self, stag: str) -> dict:
        """Refund and change fee tiers for one fare, keyed by its cabin `stag`."""
        return self._post("/book/queryrefundrulewithflightinfo",
                          {"GSGuid": stag, "IsDispExtConfig": 1, "plat": 1})

    def ancillaries(self, stag: str) -> dict:
        """Optional add-ons (insurance, lounge, ...) sold with a fare."""
        try:
            return self._post("/book/saleproducts/cabins", {"type": 3, "tag": stag})
        except ApiError:
            return {}

    def cheapest_from(self, airport: str) -> list[dict]:
        """Cheapest destinations out of an airport."""
        body = self._post("/query/getstartportlowestprice", {"StartPort": airport})
        if not body.get("Success"):
            raise ApiError(body.get("Message") or "no data")
        return body.get("LowestPrices") or []

    def resolve(self, keyword: str) -> list[dict]:
        """Server-side place lookup: does this place have an airport, which one."""
        body = self._post("/home/queryflightnearbylist",
                          {"keyword": keyword, "lon": 1, "lat": 1,
                           "loccounty": "中国", "rescitytp": 1, "calltype": ""})
        return body.get("rl") or []

    def airports(self) -> list[dict]:
        """Full city/airport directory (625 entries)."""
        body = self._post("/query/getallcityandairports", {})
        return [c for group in body.values() for c in group]


# -- models ----------------------------------------------------------------

@dataclass
class Flight:
    date: str
    flight: str
    airline: str
    dep_airport: str
    dep_time: str
    arr_airport: str
    arr_time: str
    arrives_next_day: bool
    duration: str
    stops: int
    stop_city: str
    stop_codes: list[str]
    stop_duration: str
    plane: str
    on_time_rate: str
    seats: str
    meal: str
    fare: int
    airport_fee: int
    fuel_fee: int
    total: int
    discount: str
    business_fare: int | None
    cabins: list[dict] = field(default_factory=list)

    @property
    def tax(self) -> int:
        return self.airport_fee + self.fuel_fee


def parse_flight(raw: dict, day: str) -> Flight:
    fare = int(raw.get("lcp") or 0)
    apt = int(raw.get(AIRPORT_FEE_KEY) or 0)
    fuel = int(raw.get(FUEL_FEE_KEY) or 0)
    biz = raw.get("lbcp")
    return Flight(
        date=day,
        flight=raw.get("flightNo", ""),
        airline=raw.get("airCompanyName", ""),
        dep_airport=raw.get("oapname", ""),
        dep_time=raw.get("flyOffOnlyTime", ""),
        arr_airport=raw.get("aapname", ""),
        arr_time=raw.get("arrivalOnlyTime", ""),
        arrives_next_day=str(raw.get("arrivalTime", ""))[:10] != day,
        duration=raw.get("spantime", ""),
        stops=int(raw.get("stopNum") or 0),
        stop_city=raw.get("son") or "",
        stop_codes=raw.get("ssc") or [],
        stop_duration=raw.get("sd") or "",
        plane=raw.get("equipmentName", ""),
        on_time_rate=raw.get("fRate", ""),
        seats=str(raw.get("lcn") or "?"),
        meal=raw.get("mfgd") or raw.get("mfg") or "",
        fare=fare,
        airport_fee=apt,
        fuel_fee=fuel,
        total=fare + apt + fuel,
        discount=raw.get("lcd", ""),
        business_fare=int(biz) if biz and str(biz) != "0" else None,
        cabins=dedupe(parse_cabin(c) for c in (raw.get("cabins") or [])),
    )


def parse_cabin(raw: dict) -> dict:
    return {
        "name": raw.get("roomDes", ""),
        "fare": float(raw.get("SellPrice") or 0),
        "seats": raw.get("ticketsNum", ""),
        "checked_baggage_kg": raw.get("baggage", ""),
        "hand_baggage_kg": raw.get("handBaggage", ""),
        "meal": raw.get("ml", ""),
        "stag": raw.get("stag", ""),
    }


def dedupe(cabins) -> list[dict]:
    """Collapse identical fares resold by different agents."""
    seen, out = set(), []
    for c in cabins:
        key = tuple(v for k, v in c.items() if k != "stag")
        if key not in seen:
            seen.add(key)
            out.append(c)
    return sorted(out, key=lambda c: c["fare"])


PASSENGERS = {1: "adult", 2: "child", 3: "infant"}


def parse_rules(data: dict, passenger: str = "adult") -> list[dict]:
    """Flatten refund/change fee tiers into {rule, when, fee, percent} rows."""
    rows = []
    for group in data.get("RefundRuleList") or []:
        for entry in group.get("DataList") or []:
            who = PASSENGERS.get(entry.get("passengerType"), "?")
            if passenger != "all" and who != passenger:
                continue
            for item in entry.get("ruleItems") or []:
                for p in item.get("periods") or []:
                    rows.append({
                        "passenger": who,
                        "rule": item.get("itemName", ""),
                        "when": p.get("timeRange", ""),
                        "fee": p.get("fee"),
                        "fee_desc": p.get("feeDesc", ""),
                        "percent": p.get("percent"),
                        "current": bool(p.get("selected")),
                    })
    return rows


# -- rendering -------------------------------------------------------------

def render(f: Flight) -> str:
    if f.stops:
        stops = f"via {f.stop_city}({f.stop_duration})"
    else:
        stops = "nonstop"
    seats = f"{f.seats} left" if f.seats.isdigit() else f"class {f.seats}"
    plus = "+1" if f.arrives_next_day else "  "
    biz = f"  biz {f.business_fare}" if f.business_fare else ""
    return (
        f"  {f.total:>5}  ({f.fare} + {f.tax} tax)"
        f"  {f.flight:<8} {f.dep_time}-{f.arr_time}{plus}"
        f"  {f.duration:<12} {stops:<18} {seats:<10}"
        f"  {f.on_time_rate}% on-time  {f.airline} {f.plane}{biz}"
    )


SORTS = {
    "price": lambda f: f.total,
    "depart": lambda f: f.dep_time,
    "duration": lambda f: (f.stops, f.dep_time),
}


def one_flight(c: Client, a: argparse.Namespace) -> Flight:
    body = c.flight_list(a.dep, a.arr, a.date, a.flight)
    for raw in body.get("FlightInfoSimpleList") or []:
        if raw.get("flightNo") == a.flight:
            return parse_flight(raw, a.date)
    sys.exit(f"flight {a.flight} not found on {a.date}")


def pick_cabin(f: Flight, index: int) -> dict:
    if not f.cabins:
        sys.exit(f"{f.flight} has no bookable fares")
    if index >= len(f.cabins):
        sys.exit(f"fare index {index} out of range (0..{len(f.cabins) - 1})")
    return f.cabins[index]


# -- commands --------------------------------------------------------------

def cmd_search(c: Client, a: argparse.Namespace) -> None:
    out: dict[str, list] = {}
    for day in expand_dates(a.dates, a.days):
        body = c.flight_list(a.dep, a.arr, day)
        flights = [parse_flight(r, day) for r in body.get("FlightInfoSimpleList") or []]
        if a.direct:
            flights = [f for f in flights if f.stops == 0]
        if a.max_price:
            flights = [f for f in flights if f.total <= a.max_price]
        flights.sort(key=SORTS[a.sort])
        if a.limit:
            flights = flights[: a.limit]
        out[day] = [asdict(f) for f in flights]
        if not a.json:
            print(f"{a.dep}-{a.arr} {day}  ({len(flights)} flights)  "
                  f"total = fare + airport fee + fuel surcharge, CNY")
            for f in flights:
                print(render(f))
            print()
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_calendar(c: Client, a: argparse.Namespace) -> None:
    start = check_date(a.start) if a.start else date.today().isoformat()
    end = check_date(a.end) if a.end else (
        date.fromisoformat(start) + timedelta(days=a.days)).isoformat()
    rows = c.price_calendar(a.dep, a.arr, start, end)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{a.dep}-{a.arr}  {start} .. {end}  ({len(rows)} days with service)")
    print("  date        day    fare  discount  flight   times")
    for r in rows:
        disc = f"{r['discount'] / 10:.1f} off" if r.get("discount") else ""
        print(f"  {r['flydate']}  {r['week']}  {r['price']:>5}  {disc:<8}  "
              f"{r.get('flightno', ''):<7}  "
              f"{r.get('flytime', '')[11:]}-{r.get('arrtime', '')[11:]}")


def cmd_cabins(c: Client, a: argparse.Namespace) -> None:
    f = one_flight(c, a)
    if a.json:
        print(json.dumps(asdict(f), ensure_ascii=False, indent=2))
        return
    print(f"{f.flight} {f.airline}  {f.dep_airport} {f.dep_time} -> "
          f"{f.arr_airport} {f.arr_time}  {f.duration}  {f.plane}")
    if f.stops:
        print(f"stop: {f.stop_city} {f.stop_codes} for {f.stop_duration}")
    print(f"tax: airport fee {f.airport_fee} + fuel {f.fuel_fee} = "
          f"{f.tax} CNY per adult\n")
    print("  idx     fare   total  class          seats  baggage")
    for i, cab in enumerate(f.cabins):
        print(f"  {i:<3} {cab['fare']:>8.0f} {cab['fare'] + f.tax:>7.0f}"
              f"  {cab['name']:<14} {cab['seats']:<5}"
              f"  {cab['checked_baggage_kg']}kg + {cab['hand_baggage_kg']}kg hand"
              f"  {cab['meal']}")


def cmd_rules(c: Client, a: argparse.Namespace) -> None:
    f = one_flight(c, a)
    cab = pick_cabin(f, a.fare)
    rows = parse_rules(c.fare_rules(cab["stag"]), a.passenger)
    if a.json:
        print(json.dumps({"flight": f.flight, "cabin": cab["name"], "rules": rows},
                         ensure_ascii=False, indent=2))
        return
    print(f"{f.flight} {f.date}  {cab['name']}  fare {cab['fare']:.0f} "
          f"+ {f.tax} tax = {cab['fare'] + f.tax:.0f} CNY  [{a.passenger}]\n")
    section = None
    for r in rows:
        if (r["passenger"], r["rule"]) != section:
            section = (r["passenger"], r["rule"])
            label = r["rule"] if a.passenger != "all" else f"{r['rule']} ({r['passenger']})"
            print(f"  {label}")
        mark = "*" if r["current"] else " "
        when = r["when"] or "any time"
        pct = f"({r['percent']}% of fare)" if r["percent"] else ""
        print(f"   {mark} {when:<24} {r['fee_desc'] or '-':<14} {pct}")
    print("\n  * = tier that applies right now")


def cmd_extras(c: Client, a: argparse.Namespace) -> None:
    f = one_flight(c, a)
    cab = pick_cabin(f, a.fare)
    data = c.ancillaries(cab["stag"])
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    items = (data or {}).get("RecInsList") or []
    if not items:
        print(f"{f.flight} {cab['name']}: no add-ons offered")
        return
    for it in items:
        print(f"  {it.get('Name', '')}  {it.get('Price', '')}  {it.get('Desc', '')}")


def cmd_deals(c: Client, a: argparse.Namespace) -> None:
    rows = c.cheapest_from(a.airport)
    rows.sort(key=lambda r: r.get("Price") or 0)
    if a.limit:
        rows = rows[: a.limit]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"cheapest fares out of {a.airport} (fare only, tax excluded)")
    for r in rows:
        print(f"  {r['Price']:>6}  {r['EndPortCode']:<4} {r['EndCityName']:<8} "
              f"{r['FlyDate']}")


def cmd_resolve(c: Client, a: argparse.Namespace) -> None:
    rows = c.resolve(a.query)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        has = "airport" if r.get("hasAirPort") == "1" else "NO airport"
        print(f"  {r.get('code') or '----':<4} {r.get('showName', ''):<20} {has}")


def cmd_airports(c: Client, a: argparse.Namespace) -> None:
    q = a.query.lower()
    hits = [
        x for x in c.airports()
        if x.get("isHaveAirport")
        and (q in x["cityFullName"] or q in x["cityCode"].lower()
             or q in (x.get("airportCode") or "").lower()
             or q in (x.get("cityFullPinyin") or "").lower())
    ]
    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return
    for x in hits:
        print(f"  {x['airportCode'] or x['cityCode']:<4} {x['cityFullName']:<8} "
              f"{x.get('airportName', '')}  ({x.get('provinceShortName', '')})")


def check_date(day: str) -> str:
    """Fail loudly on a bad date; the API answers 200 with an empty list."""
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        raise ApiError(f"invalid date {day!r}, expected YYYY-MM-DD") from None


def expand_dates(dates: list[str], days: int | None) -> list[str]:
    if days:
        start = date.fromisoformat(check_date(dates[0])) if dates else date.today()
        return [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return [check_date(d) for d in dates] or [date.today().isoformat()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="raw JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    def route(sp):
        sp.add_argument("dep")
        sp.add_argument("arr")
        return sp

    def flight(sp):
        route(sp)
        sp.add_argument("date")
        sp.add_argument("flight")
        sp.add_argument("--fare", type=int, default=0,
                        help="fare index from `cabins` (default cheapest)")
        return sp

    s = route(sub.add_parser("search", help="flights with full prices for given dates"))
    s.add_argument("dates", nargs="*", metavar="DATE")
    s.add_argument("--days", type=int, help="N consecutive days from first DATE")
    s.add_argument("--direct", action="store_true")
    s.add_argument("--max-price", type=int, help="cap on total price")
    s.add_argument("--sort", choices=SORTS, default="price")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_search)

    c = route(sub.add_parser("calendar", help="cheapest fare per date, one request"))
    c.add_argument("--start")
    c.add_argument("--end")
    c.add_argument("--days", type=int, default=60)
    c.set_defaults(fn=cmd_calendar)

    flight(sub.add_parser("cabins", help="fare classes, baggage, seats for one flight")
           ).set_defaults(fn=cmd_cabins)
    rr = flight(sub.add_parser("rules",
                               help="refund and change fee tiers for one fare"))
    rr.add_argument("--passenger", choices=("adult", "child", "infant", "all"),
                    default="adult")
    rr.set_defaults(fn=cmd_rules)
    flight(sub.add_parser("extras", help="optional add-ons sold with a fare")
           ).set_defaults(fn=cmd_extras)

    d = sub.add_parser("deals", help="cheapest destinations out of an airport")
    d.add_argument("airport")
    d.add_argument("--limit", type=int, default=30)
    d.set_defaults(fn=cmd_deals)

    r = sub.add_parser("resolve", help="does a place have an airport, and which")
    r.add_argument("query")
    r.set_defaults(fn=cmd_resolve)

    a = sub.add_parser("airports", help="IATA lookup by city name or pinyin")
    a.add_argument("query")
    a.set_defaults(fn=cmd_airports)
    return p


def main() -> None:
    args = build_parser().parse_args()
    for attr in ("dep", "arr", "flight", "airport"):
        if hasattr(args, attr):
            setattr(args, attr, getattr(args, attr).upper())

    client = Client()
    try:
        args.fn(client, args)
    except (ApiError, httpx.HTTPError) as e:
        sys.exit(f"error: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
