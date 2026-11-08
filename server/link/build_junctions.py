"""도로 링크 나들목: 경부고속도로 하행(양재 → 천안) 경로 위의 IC 진출 지점을 gyeongbu_route.json 의 junctions 에 넣는다.

사용: python -X utf8 build_junctions.py
- 자료: sim/data/osm_motorway_junctions.json(OSM highway=motorway_junction 노드, ODbL — 시뮬레이션과 같은 파일)
- 경로 위치 s 는 build_zones.project 와 같은 계산(link_server.project_d 와 같다). 우리 차로에서 ONROUTE(40 m) 안의 노드만,
  같은 이름이면 경로에 가장 가까운 노드 하나(build_zones.anchors 와 같은 규칙 — 우리 차로에 붙은 진출 노드)
- 나들목(IC)만 남긴다: 분기점(JC, 고속도로끼리)·휴게소 노드는 뺀다. 이름은 공식 표기(build_zones.NAME_KO/EN, 없으면 아래 표)
- 최소 우회 안내(link_server._detour · LinkHub.detour)가 '다음 나들목'을 여기서 고른다
"""
import json
from pathlib import Path

import build_zones as bz

HERE = Path(__file__).parent
SRC = HERE / "sim" / "data" / "osm_motorway_junctions.json"
# build_zones 표에 없는 IC 의 공식 표기(한국도로공사 나들목 이름)
EXTRA_KO = {"양재IC": "양재IC", "대왕판교": "대왕판교IC", "판교": "판교IC", "기흥": "기흥IC", "남사진위": "남사진위IC"}
EXTRA_EN = {"양재IC": "Yangjae IC", "대왕판교": "Daewangpangyo IC", "판교": "Pangyo IC", "기흥": "Giheung IC", "남사진위": "Namsa-Jinwi IC"}
SKIP = ("분기점", "휴게소", "JC")
ALIAS = {"양재": "양재IC"}   # 같은 IC 의 다른 노드 이름


def main():
    nodes = json.loads(SRC.read_text(encoding="utf-8"))["nodes"]
    best = {}
    for n in nodes:
        name = n.get("name")
        if not name or any(k in name for k in SKIP):
            continue
        name = ALIAS.get(name, name)
        s, d = bz.project(n["lat"], n["lon"])
        if d <= bz.ONROUTE and (name not in best or d < best[name][1]):
            best[name] = (s, d, n)
    out = []
    for name, (s, d, n) in sorted(best.items(), key=lambda kv: kv[1][0]):
        ko = bz.NAME_KO.get(name) or EXTRA_KO.get(name)
        en = bz.NAME_EN.get(name) or EXTRA_EN.get(name)
        assert ko and en, f"이름 표에 없는 나들목: {name}"
        out.append({"name": ko, "nameEn": en, "ref": n.get("ref"), "osm": n["id"], "lat": round(n["lat"], 6), "lon": round(n["lon"], 6),
                    "s": round(s), "offset": round(d)})
    for i, j in enumerate(out, 1):
        j["id"] = f"ic{i}"
    rf = bz.route_file
    rf["junctions"] = [{"id": j["id"], **{k: v for k, v in j.items() if k != "id"}} for j in out]
    bz.ROUTE_PATH.write_text(json.dumps(rf, ensure_ascii=False, indent=1), encoding="utf-8")   # build_zones 와 같은 꼴
    for j in out:
        print(f"{j['id']:5} s {j['s']:6}  {j['name']} ({j['nameEn']}) ref {j['ref']} 거리 {j['offset']} m")


if __name__ == "__main__":
    main()
