"""시연 경로(gyeongbu_route.json) 휴게소의 전기차 충전소 좌표를 공공데이터로 받아 경로 위 위치(s)에 맞춰 넣는다.

출처: 한국환경공단_전기자동차 충전소 정보(공공데이터포털 15076352, getChargerInfo) — 공공누리 제1유형(출처표시).
키: pleos-meeos/local.properties 의 DATA_GO_KR_KEY(공공데이터포털 일반 인증키). 값은 출력하지 않는다.
결과: gyeongbu_route.json 의 "evStations"(휴게소 s 별 충전소 목록). build_highway_route.py 로 경로를 다시 만들면 이 스크립트도 다시 돌린다
(build_zones.py 와 같은 방식). 두 허브 엔진(link_server.py · LinkHub.kt)은 이 목록으로 '충전소 반경'을 판정한다(docs/dev/40-algorithms.md A-15).

사용: python fetch_ev_stations.py            # 받아서 넣기(지역 11 서울·41 경기·44 충남, 페이지당 9999건)
      python fetch_ev_stations.py --dry-run  # 넣지 않고 요약만
"""
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_PATH = HERE / "gyeongbu_route.json"
PROPS = HERE.parent.parent / "local.properties"
URL = "https://apis.data.go.kr/B552584/EvCharger/getChargerInfo"
ZCODES = ("11", "41", "44")        # 시연 경로(서울 → 천안)가 지나는 시도
REST_RADIUS = 800.0                # 휴게소 좌표에서 이 안(m)의 충전소만(휴게소 부지는 수백 m)
OPPOSITE = ("서울방향", "서울 방향", "(서울)", "상행")   # 반대 방향(상행) 휴게소 충전소는 뺀다 — 시연 경로는 하행(부산 방향)


def key():
    for line in PROPS.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATA_GO_KR_KEY"):
            v = line.split("=", 1)[1].strip()
            if v:
                return v
    sys.exit("local.properties 에 DATA_GO_KR_KEY 가 없다")


def fetch(k, zcode, page, rows=9999, extra=None):
    q = {"pageNo": page, "numOfRows": rows, "zcode": zcode, "dataType": "XML", **(extra or {})}
    # 일반 인증키(Decoding)는 그대로 인코딩해 보내고, 이미 인코딩된 키(Encoding, % 포함)는 그대로 붙인다
    sk = k if "%" in k else urllib.parse.quote(k, safe="")
    url = f"{URL}?serviceKey={sk}&" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(url, timeout=120).read()
            break
        except Exception as e:                       # 키 값이 섞인 URL 은 찍지 않는다
            if attempt == 2:
                raise SystemExit(f"요청 실패(zcode {zcode}, page {page}): {type(e).__name__}")
            time.sleep(3)
    root = ET.fromstring(raw)
    code = root.findtext(".//resultCode")
    if code not in (None, "00"):
        raise SystemExit(f"API 오류 {code}: {root.findtext('.//resultMsg')}")
    total = int(root.findtext(".//totalCount") or 0)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return total, items


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main(dry):
    sys.path.insert(0, str(HERE))
    import link_server as L                         # 경로 투영(project_d)·휴게소 목록을 허브와 같은 코드로
    route = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
    rests = [r for r in L.REST if r["kind"] == "services"]
    k = key()
    rows = []
    for z in ZCODES:
        page, seen, total = 1, 0, None
        while total is None or seen < total:
            total, items = fetch(k, z, page)
            seen += len(items)
            for it in items:
                try:
                    lat, lon = float(it.get("lat") or 0), float(it.get("lng") or 0)
                except ValueError:
                    continue
                if lat and lon and any(hav(lat, lon, r["lat"], r["lon"]) <= REST_RADIUS for r in rests):
                    rows.append(it)
            print(f"zcode {z} page {page}: {seen}/{total}, 휴게소 근처 누적 {len(rows)}", flush=True)
            if not items:
                break
            page += 1
    stations = {}
    for it in rows:
        if it.get("delYn") == "Y":
            continue
        st = stations.setdefault(it["statId"], {"statId": it["statId"], "name": it.get("statNm", ""), "lat": float(it["lat"]), "lon": float(it["lng"]),
                                                "addr": it.get("addr", ""), "chargers": []})
        st["chargers"].append({"id": it.get("chgerId", ""), "type": it.get("chgerType", ""), "kw": it.get("output", "")})
    out = []
    for st in stations.values():
        if any(o in st["name"] for o in OPPOSITE):
            print(f"  반대 방향 제외: {st['name']}")
            continue
        r = min(rests, key=lambda r: hav(st["lat"], st["lon"], r["lat"], r["lon"]))
        # 휴게소 안 충전소만: 이름에 '휴게소'와 그 휴게소 이름(예: 기흥·안성·망향·서울만남)이 함께 있어야 한다 — 800 m 안의 아파트·마트·주유소 충전소는 뺀다
        stem = re.sub(r"(의광장)?\s*휴게소.*", "", r["name"]).strip().replace(" ", "")
        nm = st["name"].replace(" ", "")
        if "휴게소" not in nm or stem not in nm:
            continue
        s, d = L.project_d(L.xy(st["lat"], st["lon"]))
        out.append({"rest": r["s"], "restName": r["name"], "statId": st["statId"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                    "s": round(s), "offset": round(d), "fromRest": round(hav(st["lat"], st["lon"], r["lat"], r["lon"])),
                    "chargers": sorted(st["chargers"], key=lambda c: c["id"])})
    out.sort(key=lambda x: (x["rest"], x["s"]))
    for o in out:
        print(f"  {o['restName']}: {o['name']} s {o['s']} (휴게소 s {o['rest']}, 차 {o['s'] - o['rest']:+d} m, 경로에서 {o['offset']} m) 충전기 {len(o['chargers'])}대")
    if dry:
        return
    route["evStations"] = out
    src = route.setdefault("sources", [])
    note = "전기차 충전소 좌표: 한국환경공단_전기자동차 충전소 정보(공공데이터포털 15076352, 공공누리 제1유형 출처표시), fetch_ev_stations.py " + time.strftime("%Y-%m-%d")
    route["sources"] = [x for x in src if not (isinstance(x, str) and x.startswith("전기차 충전소 좌표:"))] + [note]
    ROUTE_PATH.write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")   # 원래 파일과 같은 꼴(build_zones.py 와 같다)
    print(f"evStations {len(out)}곳 → {ROUTE_PATH.name}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
