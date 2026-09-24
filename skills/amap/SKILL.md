---
name: amap
description: AMap (高德地图) web-service REST API — geocoding, POI search ("what's nearby"), and routing (transit/driving/cycling/walking/e-bike) anywhere in China. Use for commute times, address→coords, neighborhood facilities, and static map images. Best China coverage; no Google offset problems.
---

# AMap (高德) Web Service

Plain HTTP GET → JSON. Requires `AMAP_WEB_SERVICE_KEY` env var (a **Web服务** key
from <https://console.amap.com>; a JS-API key will **not** work here).

```bash
K=$AMAP_WEB_SERVICE_KEY   # or: set -a; source .env; set +a
```

All examples below are verified live and use these two points:

```bash
A=121.499718,31.239703   # 东方明珠
B=121.475233,31.228818   # 人民广场
```

## Three rules that cause 90% of the bugs

1. **Coordinates are `lng,lat`** — longitude first, 6 decimals. `121.499718,31.239703`.
2. **Datum is GCJ-02** ("Mars"). Never mix in raw GPS/WGS-84 or Baidu bd09ll
   without converting (§coordinate convert in reference.md) — you get a ~500 m offset.
3. **Success is `"status":"1"`** (a *string*), with `"infocode":"10000"`.
   `v4/direction/bicycling` is the odd one out: `"errcode":0`.

Shanghai citycode `021`, adcode `310000`. Throttle to **~3 QPS** or you get
`CUQPS_HAS_EXCEEDED_THE_LIMIT` (transient — back off and retry).

## The 80% — five calls


```bash
# 1. Geocode: address → coords
curl -s "https://restapi.amap.com/v3/geocode/geo?address=上海市人民广场&city=上海&key=$K" \
  | jq -r '.geocodes[0].location'          # 121.477401,31.240093

# 2. Find a *named* place (office, mall, 小区) — better than geocode for names
curl -s "https://restapi.amap.com/v5/place/text?keywords=上海博物馆&region=上海&city_limit=true&key=$K" \
  | jq -r '.pois[] | "\(.name) | \(.address) | \(.location)"'

# 3. What's nearby (the neighborhood-scoring workhorse; carries per-POI distance)
curl -s "https://restapi.amap.com/v5/place/around?location=$A&radius=2000&types=150500&sortrule=distance&key=$K" \
  | jq -r '.pois[] | "\(.distance)m \(.name)"' | head -5   # 198m 陆家嘴地铁站1号口

# 4. Commute by metro/bus — seconds + fare, several plans
curl -s "https://restapi.amap.com/v5/direction/transit/integrated?origin=$A&destination=$B&city1=021&city2=021&show_fields=cost&key=$K" \
  | jq -r '[.route.transits[] | {min:(.cost.duration|tonumber/60|round), fee:.cost.transit_fee}]'

# 5. Commute by car / bike
curl -s "https://restapi.amap.com/v5/direction/driving?origin=$A&destination=$B&show_fields=cost&key=$K" \
  | jq -r '{min:(.route.paths[0].cost.duration|tonumber/60|round), km:(.route.paths[0].distance|tonumber/1000)}'
curl -s "https://restapi.amap.com/v4/direction/bicycling?origin=$A&destination=$B&key=$K" \
  | jq -r '{min:(.data.paths[0].duration/60|round), km:(.data.paths[0].distance/1000)}'
```

## POI type codes worth memorizing

`150500` metro station · `050000` restaurants · `060100` mall · `080601` cinema
· `110101` park · `080100` gym · `090100` hospital · `141200` school

For niche things (`攀岩`, `游泳馆`, `livehouse`, `咖啡`) free-text `keywords=`
beats category codes. Full table + everything else in
[reference.md](reference.md) — read it for: reverse geocode, walking/e-bike
routing and its **~100/day quota trap**, static map PNGs, district boundaries,
coordinate conversion, `show_fields`, paging, error codes, and quota limits.
