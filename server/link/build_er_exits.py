"""긴급차량 예상 경로(새 기능 I): 응급의료기관 → 가장 가까운 나들목 표(경로 파일 gyeongbu_route.json 의 erExits)를 만든다.

입력: 공식 자료에서 받은 응급의료기관 목록 CSV(UTF-8, fetch_er_facilities.py 가 만든 er_facilities.csv). 열: name, kind, lat, lon (그 밖의 열은 무시).
권역응급의료센터·지역응급의료센터만 쓴다(KINDS). 지어낸 기관을 넣지 말 것 —
출처·기준일은 DATA_SOURCES.md 에 적는다. 이 스크립트는 좌표와 경로 파일의 나들목(junctions)만으로 계산한다(네트워크 없음).

규칙: 기관마다 직선거리로 가장 가까운 나들목을 고르고, 그 거리가 MAX_KM(기본 6 km) 안인 기관만 남긴다(나들목에서 먼 병원은 이 고속도로로 가지 않는다고 본다).
나들목마다 기관 목록을 묶어 erExits = [{junction, name, nameEn, s, hospitals:[{name, kind, lat, lon, km}]}] 로 쓴다. 허브는 name·nameEn·s 만 쓴다.

사용: python -X utf8 build_er_exits.py <기관 CSV> [--max-km 6] [--write]   (--write 가 없으면 결과만 보여 준다)
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE = HERE / "gyeongbu_route.json"


def km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


KINDS = ("권역응급의료센터", "지역응급의료센터")   # '큰 병원 응급실'만(지역응급의료기관·응급실운영신고기관은 넣지 않는다 — 구급차가 주로 가는 곳으로 좁힌다)


def build(rows, junctions, max_km, kinds=KINDS):
    by = {}
    for r in rows:
        if kinds and (r.get("kind") or "").strip() not in kinds:
            continue
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (KeyError, ValueError):
            continue
        j = min(junctions, key=lambda x: km(lat, lon, x["lat"], x["lon"]))
        d = km(lat, lon, j["lat"], j["lon"])
        if d > max_km:
            continue
        by.setdefault(j["id"], {"junction": j["id"], "name": j["name"], "nameEn": j["nameEn"], "s": j["s"], "hospitals": []})["hospitals"].append(
            {"name": r["name"].strip(), "kind": (r.get("kind") or "").strip(), "lat": lat, "lon": lon, "km": round(d, 2)})
    out = sorted(by.values(), key=lambda e: e["s"])
    for e in out:
        e["hospitals"].sort(key=lambda h: h["km"])
    return out


def main(argv):
    if not argv:
        sys.exit(__doc__)
    src = Path(argv[0])
    max_km = float(argv[argv.index("--max-km") + 1]) if "--max-km" in argv else 6.0
    route = json.loads(ROUTE.read_text(encoding="utf-8"))
    with src.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ex = build(rows, route["junctions"], max_km)
    for e in ex:
        print(f"{e['name']} s={e['s']}: " + ", ".join(f"{h['name']}({h['kind']}, {h['km']} km)" for h in e["hospitals"]))
    if "--write" in argv:
        route["erExits"] = ex
        ROUTE.write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")   # build_junctions 와 같은 꼴
        print(f"썼다: {ROUTE.name} erExits {len(ex)}곳")


if __name__ == "__main__":
    main(sys.argv[1:])
