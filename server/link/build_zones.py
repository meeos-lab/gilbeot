"""도로 링크 구역 데이터: 경부고속도로 하행(양재 → 천안) 경로 위의 사고 다발 구간·터널·교량을 gyeongbu_route.json 의 zones 에 넣는다.

사용: python -X utf8 build_zones.py <사고상세.csv> [<osm_bridge_tunnel.json> <osm_junctions.json>]
- 사고: 한국도로공사_고속도로 교통사고 상세현황(공공데이터포털 15145192, 2023~2025, CSV cp949; 사고발생이정·방향·사망·원인).
  data.go.kr 파일 페이지에서 받는다(로그인 불필요). 경부선·"부산" 방향(하행)만 쓴다
- 이정 → 경로 위치 s: OSM motorway_junction(우리 차로에 붙은 진출 노드)의 s 와 IC 공식 이정(위키백과 "경부고속도로" 나들목 표,
  부산 구서 기점 누적거리)을 기준점으로 선형 보간한다. 진출 노드가 IC 중심보다 0.3~1 km 앞이라 오차는 ±0.5 km 안
- 다발 구간: 1 km 창(100 m 간격)에 3년 5건 이상. 이 경로 평균 1.38건/km 에서 포아송 P(N>=5) = 약 1.3 % → 겹치는 창은 하나로,
  구간은 그 안 사고의 처음~끝(최소 300 m). 이름은 가까운 IC·터널
- 터널·교량: OSM 본선(ref 1) way 의 tunnel/bridge 태그. 우리 차로에서 40 m 안인 way 만, 같은 종류 50 m 안은 잇는다.
  교량은 100 m 이상만 남긴다(결빙 안내용 — 짧은 육교는 뺀다)
- OSM json 이 없으면 Overpass 에서 받는다(키 불필요, ODbL)
"""
import collections
import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROUTE_PATH = HERE / "gyeongbu_route.json"
BBOX = "36.78,127.00,37.48,127.25"
# IC 공식 이정(km, 부산 구서 기점) — ko.wikipedia.org/wiki/경부고속도로 나들목 표(2026-11-02 확인)
KM = {"양재": 416.05, "판교분기점": 408.04, "신갈분기점": 394.96, "수원신갈": 392.28, "기흥(동탄)": 386.49, "동탄분기점": 382.10,
      "오산": 378.21, "안성분기점": 364.94, "안성": 360.11, "북천안": 348.50}
NAME_KO = {"양재": "양재IC", "판교분기점": "판교JC", "신갈분기점": "신갈JC", "수원신갈": "수원신갈IC", "기흥(동탄)": "기흥동탄IC", "동탄분기점": "동탄JC",
           "오산": "오산IC", "안성분기점": "안성JC", "안성": "안성IC", "북천안": "북천안IC"}
NAME_EN = {"양재": "Yangjae IC", "판교분기점": "Pangyo JC", "신갈분기점": "Singal JC", "수원신갈": "Suwon-Singal IC", "기흥(동탄)": "Giheung-Dongtan IC",
           "동탄분기점": "Dongtan JC", "오산": "Osan IC", "안성분기점": "Anseong JC", "안성": "Anseong IC", "북천안": "Bukcheonan IC"}
# 이름만 쓰는 IC(진출 노드가 경로 끝 너머라 기준점은 못 된다): 마지막 기준점에서 기울기 1 로 이어 위치를 짐작한다
NAME_ONLY = {"천안": (340.14, "천안IC", "Cheonan IC")}
WIN, STEP, HOT_MIN, ZONE_MIN = 1000, 100, 5, 300
ONROUTE, JOIN, BRIDGE_MIN = 40.0, 50.0, 100.0

route_file = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
RAW = route_file["route"]
LAT0 = sum(p[0] for p in RAW) / len(RAW)
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 110540.0
R = [(p[1] * KX, p[0] * KY) for p in RAW]
CUM = [0.0]
for _a, _b in zip(R, R[1:]):
    CUM.append(CUM[-1] + math.hypot(_b[0] - _a[0], _b[1] - _a[1]))
LENGTH = CUM[-1]


def project(lat, lon):
    """점 → (경로 위 s, 경로까지 거리) — link_server.project_d 와 같은 계산"""
    p = (lon * KX, lat * KY)
    best, bs = math.inf, 0.0
    for i, (a, b) in enumerate(zip(R, R[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        d = math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
        if d < best:
            best, bs = d, CUM[i] + t * math.sqrt(L2)
    return bs, best


def overpass(q):
    body = urllib.parse.urlencode({"data": q}).encode()
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "Meeos-Tago-contest/1.0"})
            return json.loads(urllib.request.urlopen(req, timeout=240).read())
        except Exception as e:  # noqa: BLE001
            print(f"{url} 실패: {e}")
    raise SystemExit("Overpass 실패")


def load_osm(path, q):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else overpass(q)


def anchors(junctions):
    """IC 이름 → 우리 차로 위 진출 노드의 s (경로에서 40 m 안, 가장 가까운 것)"""
    best = {}
    for x in junctions["elements"]:
        n = x.get("tags", {}).get("name")
        if n in KM:
            s, d = project(x["lat"], x["lon"])
            if d <= ONROUTE and (n not in best or d < best[n][1]):
                best[n] = (s, d)
    pts = sorted(((KM[n], s, n) for n, (s, _) in best.items()), reverse=True)   # 이정 큰 것(서울)부터 = s 작은 것부터
    for (_, s0, _), (_, s1, n1) in zip(pts, pts[1:]):
        assert s1 > s0, f"기준점 순서가 맞지 않다: {n1}"
    return pts


def s_of(km, pts):
    if km > pts[0][0]:
        return None
    for (k0, s0, _), (k1, s1, _) in zip(pts, pts[1:]):
        if k1 <= km <= k0:
            return s0 + (k0 - km) / (k0 - k1) * (s1 - s0)
    k0, s0, _ = pts[-1]
    s = s0 + (k0 - km) * 1000.0                              # 마지막 기준점 뒤는 기울기 1
    return s if s <= LENGTH else None


def hotspots(csv_path, pts, tunnels):
    rows = list(csv.DictReader(open(csv_path, encoding="cp949", errors="replace")))
    acc = []
    for r in rows:
        if r.get("노선명") != "경부선" or r.get("방향") != "부산" or not r.get("사고발생이정"):
            continue
        s = s_of(float(r["사고발생이정"]), pts)
        if s is not None:
            acc.append((s, r))
    acc.sort(key=lambda x: x[0])
    years = sorted({r["사고년도"][:4] for _, r in acc})
    hot = [s0 for s0 in range(0, int(LENGTH) - WIN + 1, STEP) if sum(1 for s, _ in acc if s0 <= s < s0 + WIN) >= HOT_MIN]
    spans = []
    for s0 in hot:                                          # 겹치는 창은 하나로
        if spans and s0 <= spans[-1][1]:
            spans[-1][1] = s0 + WIN
        else:
            spans.append([s0, s0 + WIN])
    zones = []
    for a, b in spans:
        inside = [(s, r) for s, r in acc if a <= s < b]
        lo, hi = inside[0][0], inside[-1][0]
        if hi - lo < ZONE_MIN:
            mid = (lo + hi) / 2
            lo, hi = mid - ZONE_MIN / 2, mid + ZONE_MIN / 2
        mid = (lo + hi) / 2
        tun = next((t for t in tunnels if t["s0"] - 300 <= mid <= t["s1"] + 300), None)
        if tun:
            name, en = tun["name"], tun["nameEn"]
        else:
            k_last, s_last, _ = pts[-1]
            cands = [(s, NAME_KO[n], NAME_EN[n]) for _, s, n in pts] + [(s_last + (k_last - k) * 1000.0, ko, en) for k, ko, en in NAME_ONLY.values()]
            _, ko, en_ = min(cands, key=lambda c: abs(c[0] - mid))
            name, en = f"{ko} 부근", f"near {en_}"
        causes = collections.Counter(r["원인"] for _, r in inside).most_common(2)
        zones.append({"kind": "accident", "s0": round(lo), "s1": round(hi), "name": name, "nameEn": en, "count": len(inside),
                      "deaths": sum(int(r["사망"] or 0) for _, r in inside), "causes": [c for c, _ in causes],
                      "years": f"{years[0]}-{years[-1]}", "source": "ex"})
    return zones, len(acc)


def structures(osm):
    spans = []
    for w in osm["elements"]:
        t = w.get("tags", {})
        kind = "tunnel" if t.get("tunnel") not in (None, "no") else "bridge" if t.get("bridge") not in (None, "no") else None
        g = w.get("geometry", [])
        if not kind or not g:
            continue
        ps = [project(q["lat"], q["lon"]) for q in g]
        if max(d for _, d in ps) > ONROUTE:
            continue                                        # 반대 차로·램프
        name = t.get("tunnel:name") or t.get("bridge:name") or ""
        en = t.get("tunnel:name:en") or t.get("bridge:name:en") or ""
        spans.append([kind, min(s for s, _ in ps), max(s for s, _ in ps), name, en])
    spans.sort(key=lambda x: x[1])
    out = []
    for k, a, b, n, en in spans:
        if out and out[-1][0] == k and a - out[-1][2] <= JOIN:
            out[-1][2] = max(out[-1][2], b)
            out[-1][3] = out[-1][3] or n
            out[-1][4] = out[-1][4] or en
        else:
            out.append([k, a, b, n, en])
    res = []
    for k, a, b, n, en in out:
        if k == "bridge" and b - a < BRIDGE_MIN:
            continue
        ko = n or ("교량" if k == "bridge" else "터널")
        res.append({"kind": k, "s0": round(a), "s1": round(b), "name": ko, "nameEn": en or ("bridge" if k == "bridge" else "tunnel"), "source": "osm"})
    return res


def main(csv_path, bt_path=None, jn_path=None):
    bt = load_osm(bt_path, f"""[out:json][timeout:180];
(
  way["highway"="motorway"]["ref"~"(^|;)1(;|$)"]["bridge"]({BBOX});
  way["highway"="motorway"]["ref"~"(^|;)1(;|$)"]["tunnel"]({BBOX});
);
out body geom;""")
    jn = load_osm(jn_path, f"""[out:json][timeout:180];
node["highway"="motorway_junction"]({BBOX});
out body;""")
    pts = anchors(jn)
    print("이정 기준점:", ", ".join(f"{n} {k}km→s {s:.0f}" for k, s, n in pts))
    st = structures(bt)
    zones, n = hotspots(csv_path, pts, [z for z in st if z["kind"] == "tunnel"])
    allz = sorted(st + zones, key=lambda z: (z["s0"], z["kind"]))
    for i, z in enumerate(allz, 1):
        z["id"] = f"z{i}"
    route_file["zones"] = allz
    src = [x for x in route_file["sources"] if not x.startswith(("한국도로공사", "위키백과"))]
    route_file["sources"] = src + [f"한국도로공사_고속도로 교통사고 상세현황(공공데이터포털 15145192, 2023~2025) — 경부선 하행 이 경로 {n}건",
                                   "위키백과 '경부고속도로' 나들목 이정(이정 → 경로 위치 기준점)"]
    ROUTE_PATH.write_text(json.dumps(route_file, ensure_ascii=False, indent=1), encoding="utf-8")   # 원래 파일과 같은 꼴(들여쓰기 1, 끝 줄바꿈 없음)
    for z in allz:
        extra = f" {z['count']}건 사망 {z['deaths']} {'/'.join(z['causes'])}" if z["kind"] == "accident" else ""
        print(f"{z['id']:4} {z['kind']:8} {z['s0']:6}~{z['s1']:6} {z['name']}{extra}")


if __name__ == "__main__":
    main(*sys.argv[1:])
