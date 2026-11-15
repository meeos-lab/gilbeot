"""긴급차량 예상 경로(새 기능 I): 시연 경로 나들목 주변 응급의료기관을 공식 자료에서 받아 CSV 로 고정한다.

출처: 국립중앙의료원 「전국 응급의료기관 정보 조회 서비스」(공공데이터포털 OpenAPI, B552657/ErmctInfoInqireService)
  - getEgytLcinfoInqire(위치 기준 가까운 응급의료기관): 나들목 좌표마다 가까운 기관 목록(기관 id·이름·주소·좌표·거리)
  - getEgytListInfoInqire(목록): 기관 이름으로 응급의료기관 분류명(dutyEmclsName — 권역·지역응급의료센터·지역응급의료기관)
키: 환경변수 DATA_GO_KR_KEY → pleos-meeos/local.properties 의 DATA_GO_KR_KEY. 값은 출력·기록하지 않는다(응답 오류 문구에 키가 섞이지 않게 URL 도 출력하지 않는다).
결과: er_facilities.csv(name, kind, lat, lon, hpid, addr) — build_er_exits.py 의 입력. 기준일은 실행한 날(DATA_SOURCES.md 에 적는다).

사용: python -X utf8 fetch_er_facilities.py [--probe]   (--probe: 한 나들목만 불러 응답 항목 이름만 보여 준다)
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPS = HERE.parent.parent / "local.properties"
BASE = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
OUT = HERE / "er_facilities.csv"
PER_EXIT = 10


def key():
    v = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if v:
        return v
    if PROPS.is_file():
        for line in PROPS.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATA_GO_KR_KEY"):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    sys.exit("DATA_GO_KR_KEY 가 없다(환경변수 또는 local.properties)")


def call(k, op, params):
    sk = k if "%" in k else urllib.parse.quote(k, safe="")
    url = f"{BASE}/{op}?serviceKey={sk}&" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/xml"}), timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None, "XML 아님(" + body[:60].replace(k, "…") + ")"
    code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
    msg = (root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip()
    if code not in ("00", "0000", ""):
        return None, f"결과 코드 {code} {msg}"
    return [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")], None


def main(argv):
    k = key()
    route = json.loads((HERE / "gyeongbu_route.json").read_text(encoding="utf-8"))
    juncs = route["junctions"][:1] if "--probe" in argv else route["junctions"]
    found = {}
    for j in juncs:
        items, err = call(k, "getEgytLcinfoInqire", {"WGS84_LON": j["lon"], "WGS84_LAT": j["lat"], "pageNo": 1, "numOfRows": PER_EXIT})
        if err:
            sys.exit(f"{j['name']}: {err}")
        if "--probe" in argv:
            print("항목 이름:", sorted({t for it in items for t in it}))
            for it in items[:3]:
                print({t: it.get(t) for t in ("dutyName", "dutyAddr", "latitude", "longitude", "distance", "hpid")})
            return
        for it in items:
            if it.get("hpid") and it["hpid"] not in found:
                found[it["hpid"]] = it
        time.sleep(0.3)
    rows = []
    for hpid, it in found.items():
        kind = ""
        li, err = call(k, "getEgytListInfoInqire", {"QN": it.get("dutyName", ""), "pageNo": 1, "numOfRows": 10})
        if not err:
            m = next((x for x in li if x.get("hpid") == hpid), None)
            kind = (m or {}).get("dutyEmclsName", "")
        time.sleep(0.3)
        rows.append({"name": it.get("dutyName", ""), "kind": kind, "lat": it.get("latitude", ""), "lon": it.get("longitude", ""), "hpid": hpid, "addr": it.get("dutyAddr", "")})
    rows.sort(key=lambda r: r["name"])
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "kind", "lat", "lon", "hpid", "addr"])
        w.writeheader(); w.writerows(rows)
    print(f"썼다: {OUT.name} {len(rows)}곳 (나들목 {len(juncs)}곳 × 가까운 {PER_EXIT}곳, 중복 제외)")


if __name__ == "__main__":
    main(sys.argv[1:])
