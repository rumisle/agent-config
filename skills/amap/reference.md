# AMap Web Service — reference

Base: `https://restapi.amap.com` · every request takes `key=$AMAP_WEB_SERVICE_KEY`
(and `output=json`, the default). Coords `lng,lat`, GCJ-02.
Official docs hub: <https://lbs.amap.com/api/webservice/summary> (Chinese, thorough,
with a runnable in-browser debugger per endpoint).

All examples below were verified live.

---

## Endpoint map

| Purpose | Endpoint | Success flag | Duration field |
|---|---|---|---|
| Geocode | `/v3/geocode/geo` | `status:"1"` | — |
| Reverse geocode | `/v3/geocode/regeo` | `status:"1"` | — |
| POI by name | `/v5/place/text` | `status:"1"` | — |
| POI nearby | `/v5/place/around` | `status:"1"` | — |
| Transit | `/v5/direction/transit/integrated` | `status:"1"` | `route.transits[].cost.duration` |
| Driving | `/v5/direction/driving` | `status:"1"` | `route.paths[].cost.duration` |
| Walking | `/v5/direction/walking` | `status:"1"` | `route.paths[].cost.duration` |
| Cycling | `/v4/direction/bicycling` | **`errcode:0`** | `data.paths[].duration` |
| E-bike 电动车 | `/v5/direction/electrobike` | `status:"1"` | `route.paths[].duration` |
| District/boundary | `/v3/config/district` | `status:"1"` | — |
| Coordinate convert | `/v3/assistant/coordinate/convert` | `status:"1"` | — |
| Static map PNG | `/v3/staticmap` | *(binary)* | — |

v3 direction endpoints (`/v3/direction/transit/integrated`, `/v3/direction/driving`)
still work and are flatter — `route.transits[0].duration`, `route.paths[0].duration`,
no `show_fields` needed. Mixing v3 and v5 is fine.

---

## Geocoding

```bash
# address → coords
curl -s "https://restapi.amap.com/v3/geocode/geo?address=上海市人民广场&city=上海&key=$K"
# → geocodes[0]: .location .level .formatted_address .adcode .district .citycode

# coords → address
curl -s "https://restapi.amap.com/v3/geocode/regeo?location=121.499718,31.239703&key=$K"
# → .regeocode.formatted_address, .regeocode.addressComponent.{province,district,township,...}
# optional: &extensions=all&radius=1000 for surrounding POIs/roads
```

`level` tells you the precision (`门址`, `兴趣点`, `道路`, `区县`…). A result at
`level:"区县"` means the address failed to resolve properly — treat as a miss.
Docs: <https://lbs.amap.com/api/webservice/guide/api/georegeo>

---

## POI search

Docs: <https://lbs.amap.com/api/webservice/guide/api/newpoisearch>

```bash
# text search — resolve a named place
curl -s "https://restapi.amap.com/v5/place/text?keywords=上海博物馆&region=上海&city_limit=true&page_size=25&page_num=1&show_fields=business&key=$K"

# around search — everything of a category within N metres
curl -s "https://restapi.amap.com/v5/place/around?location=121.499718,31.239703&radius=3000&types=050000&sortrule=distance&page_size=25&key=$K"
```

| Param | Notes |
|---|---|
| `keywords` | free text; combinable with `types` |
| `types` | comma-separated typecodes |
| `region` / `city_limit` | text search only; `city_limit=true` prevents leaking to other cities |
| `radius` | around search, metres, ≤ 50000 |
| `sortrule` | `distance` (default for around) or `weight` |
| `page_size` / `page_num` | ≤ 25 per page; page through for full counts |
| `show_fields` | `business` (rating, hours, tel), `children`, `photos`, `indoor` |

POI fields: `id name type typecode address location adname citycode`, plus
**`distance`** (metres) in *around* responses only.

### Type codes

| Facility | `types` | | Facility | `types` |
|---|---|---|---|---|
| Metro station 地铁站 | `150500` | | Bus stop 公交站 | `150700` |
| Restaurants 餐饮 | `050000` | | Cafe 咖啡 | `050500` |
| Shopping mall 商场 | `060100` | | Supermarket 超市 | `060400` |
| Convenience store | `060200` | | Cinema 电影院 | `080601` |
| Park 公园 | `110101` | | Attraction 景点 | `110200` |
| Gym 健身 | `080100` | | Bar 酒吧 | `080306` |
| Hospital 医院 | `090100` | | Pharmacy 药店 | `090601` |
| School 学校 | `141200` | | Bank/ATM | `160100` |
| Parking 停车场 | `150900` | | Gas station 加油站 | `010100` |

Niche interests resolve better via `keywords`: `攀岩` (climbing), `游泳馆` (pool),
`livehouse`, `菜市场`, `宠物医院`. Full typecode spreadsheet ("POI 分类编码"):
<https://lbs.amap.com/api/webservice/download>

---

## Routing

Docs: <https://lbs.amap.com/api/webservice/guide/api/newroute>

```bash
A=121.499718,31.239703; B=121.475233,31.228818   # 东方明珠 → 人民广场

# transit — multiple plans; show_fields=cost gives duration + fare
curl -s "https://restapi.amap.com/v5/direction/transit/integrated?origin=$A&destination=$B&city1=021&city2=021&show_fields=cost&key=$K"
# .route.transits[] → .cost.duration (s), .cost.transit_fee (¥), .walking_distance (m)
# city1/city2 accept citycode (021) or adcode (310000). Same-city → pass both.

# driving — traffic-aware; show_fields=cost adds duration/tolls
curl -s "https://restapi.amap.com/v5/direction/driving?origin=$A&destination=$B&show_fields=cost&key=$K"
# .route.paths[0]: .distance (m), .cost.duration (s), .cost.tolls (¥), .cost.traffic_lights
# &strategy=32 → 默认(躲避拥堵) ; 0 = 速度优先, no traffic

# walking
curl -s "https://restapi.amap.com/v5/direction/walking?origin=$A&destination=$B&key=$K"

# cycling — NOTE errcode:0 and a different JSON shape
curl -s "https://restapi.amap.com/v4/direction/bicycling?origin=$A&destination=$B&key=$K"
# .data.paths[0].duration (s, int), .data.paths[0].distance (m, int)

# e-bike 电动车
curl -s "https://restapi.amap.com/v5/direction/electrobike?origin=$A&destination=$B&key=$K"
```

### Gotchas that matter for commute estimates

- **⚠ `electrobike` is quota-capped at ~100 calls/day** on the free tier, while
  `v4/direction/bicycling` is not. Measured side by side over many points they
  differ by **<2 min / ~5%** — use cycling as a drop-in proxy for batch jobs and
  spend the electrobike quota only on finalists.
- Both bike models assume a conservative **~15 km/h door-to-door** (国标-capped,
  lights and turns eaten). Real-world clean runs ≈ **0.7–0.8×** the returned minutes.
  Gating on **distance (km)** is more robust than on minutes.
- Transit has **no departure-time parameter** — every number is an off-peak-ish
  estimate and drifts a few minutes between days. Don't treat it as exact.
- Transit routing can be wildly circuitous for short hops (two nearby points on
  different lines → 40–50 min). Always cross-check short distances with cycling
  before rejecting a location.
- **Motorcycle routing is a paid/gated logistics product** — a normal key returns
  `INSUFFICIENT_PRIVILEGES`. Baidu (`api.map.baidu.com/direction/v2/motorcycle`)
  opens it to individuals but requires a 工单 to enable.

---

## Other endpoints

```bash
# district / boundary lookup — adcode, centre, optional polyline
curl -s "https://restapi.amap.com/v3/config/district?keywords=浦东新区&subdistrict=1&key=$K"
# add &extensions=all for .districts[0].polyline (boundary, huge)

# coordinate convert → GCJ-02 (coordsys: gps | baidu | mapbar; ≤40 points, ';'-separated)
curl -s "https://restapi.amap.com/v3/assistant/coordinate/convert?locations=121.499718,31.239703&coordsys=gps&key=$K"

# static map PNG — quick thumbnail, no JS needed
curl -s -o map.png "https://restapi.amap.com/v3/staticmap?location=121.499718,31.239703&zoom=15&size=400*300&markers=mid,,A:121.499718,31.239703&key=$K"
# size ≤ 1024*1024; markers=size,color,label:lng,lat|lng,lat ; also paths= for polylines
```

**Interactive browser map** is a different product and needs a separate **Web端 (JS API)**
key + security secret, loaded as
`https://webapi.amap.com/maps?v=2.0&key=$AMAP_JS_KEY`. JS keys with no domain
whitelist work from `localhost`/`file://`.

---

## Errors, quota, throttling

Error-code list: <https://lbs.amap.com/api/webservice/guide/tools/info>

| infocode | info | meaning |
|---|---|---|
| `10000` | OK | success |
| `10001` | INVALID_USER_KEY | wrong key, or a JS key used on the REST API |
| `10003` | CUQPS_HAS_EXCEEDED_THE_LIMIT | **QPS exceeded — transient, back off and retry** |
| `10004` | DAILY_QUERY_OVER_LIMIT | daily quota gone |
| `10009` | USERKEY_PLAT_NOMATCH | key type ≠ platform (JS key vs Web服务) |
| `10012` | INSUFFICIENT_PRIVILEGES | gated/paid product (e.g. motorcycle routing) |
| `20000` | INVALID_PARAMS | bad params — check coord order! |
| `20003` | ENGINE_RESPONSE_DATA_ERROR | no route/result found |

- Free personal tier: tens of thousands/day for geocode, POI and routing;
  electrobike is the notable exception at ~100/day.
- Enforce a client-side **3 QPS** gate (monotonic-clock min-interval) in any batch job.
- **Cache aggressively on disk**: key on sha256(endpoint + sorted params minus `key`).
  Geocode and POI results need no TTL (addresses don't move); give routing a TTL
  only if you want fresh traffic. This is the single biggest quota saver when
  re-running a pipeline over a growing dataset.
- Never log the key.

---

## Cross-provider note (Baidu)

If you also hit Baidu (`api.map.baidu.com`), the conventions **invert**:

| | AMap | Baidu |
|---|---|---|
| Coord order | `lng,lat` | **`lat,lng`** |
| Default datum | GCJ-02 | **bd09ll** |
| Feed GCJ coords | native | `coord_type=gcj02` (place search: `coord_type=3`) |
| Key param | `key=` | `ak=` |
| Success | `status:"1"` (string) | `status:0` (int) |
