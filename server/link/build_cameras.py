"""제한속도·단속 표지(11-15): fetch_speed_cameras.py 가 받은 공식 단속카메라(speed_cameras.csv)를 시연 경로(경부고속도로 하행) 위 같은 방향 것만 골라
경로 파일(gyeongbu_route.json)의 cameras = [{s, kind, limit, place, lat, lon, ref}] 로 쓴다(s 오름차순, 경로 위 거리 m).

고르는 규칙(지어낸 카메라를 넣지 말 것 — 원본 행 그대로, 버린 까닭을 센다):
  - 경로 선에서 MAX_OFF m 안(하행 본선 위). 고속도로 상·하행 본선은 20~40 m 떨어져 있어 거리만으로는 가르기 어렵다 →
  - 도로노선방향(roadRouteDrc)이 하행·부산방향·천안방향 같은 '하행'이면 넣고, 상행·서울방향이면 뺀다. 방향 글이 비어 있으면
    경로 진행 방향의 오른쪽(하행 본선 쪽)에 있는지로 가른다(한국은 오른쪽 통행 — 하행 차로는 진행 방향 오른쪽 카메라가 찍는다).
  - 제한속도(lmttVe)가 숫자가 아니면 limit = None(표지는 단속 종류만).
단속구분(regltSe)은 원본 글 그대로 kind 에 둔다(과속·신호·주정차·구간단속 등 — 지도가 그림을 고른다).

사용: python -X utf8 build_cameras.py   (경로 파일을 고쳐 쓴다 — 바꾸기 전에 git diff 로 확인)
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_F = HERE / "gyeongbu_route.json"
SRC = HERE / "speed_cameras.csv"
MAX_OFF = 45.0
# 도로노선방향(roadRouteDrc)은 코드: 1 = 상행(서울방향), 2 = 하행(부산방향), 3·03 = 양방향 — 11-15 받은 자료에서 설치장소 글("서울방향"·"부산방향")과 맞춰 확인
DRC_UP, DRC_DOWN, DRC_BOTH = {"1", "01"}, {"2", "02"}, {"3", "03"}


def xy(lat, lon, lat0):
    return (lon * 111320.0 * math.cos(math.radians(lat0)), lat * 110540.0)


def project(route_xy, cum, p):
    """경로 선 위 가장 가까운 점: (s, 거리, 오른쪽이면 +)"""
    best = (None, 1e18, 0.0)
    for i in range(1, len(route_xy)):
        (ax, ay), (bx, by) = route_xy[i - 1], route_xy[i]
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1.0
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
        qx, qy = ax + t * dx, ay + t * dy
        d = math.hypot(p[0] - qx, p[1] - qy)
        if d < best[1]:
            side = dx * (p[1] - ay) - dy * (p[0] - ax)   # 왼쪽 + (반시계)
            best = (cum[i - 1] + t * math.sqrt(L2), d, -1.0 if side > 0 else 1.0)
    return best


def main():
    route_file = json.loads(ROUTE_F.read_text(encoding="utf-8"))
    route = route_file["route"]; lat0 = sum(p[0] for p in route) / len(route)
    rxy = [xy(p[0], p[1], lat0) for p in route]
    cum = [0.0]
    for i in range(1, len(rxy)): cum.append(cum[-1] + math.hypot(rxy[i][0] - rxy[i - 1][0], rxy[i][1] - rxy[i - 1][1]))
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    out, why = [], {"멀다": 0, "상행": 0, "왼쪽(방향 글 없음)": 0, "좌표 없음": 0, "같은 자리 중복": 0, "고속도로 아님": 0}
    seen = set()
    for r in rows:
        try: lat, lon = float(r.get("latitude") or ""), float(r.get("longitude") or "")
        except ValueError: why["좌표 없음"] += 1; continue
        if (r.get("roadKnd") or "").strip() != "고속국도" and "경부" not in (r.get("roadRouteNm") or ""):
            why["고속도로 아님"] += 1; continue   # 고속도로 위를 지나는 시내 도로(교차로·어린이보호구역) 카메라가 선 가까이 잡혔다(11-15)
        s, d, side = project(rxy, cum, xy(lat, lon, lat0))
        if d > MAX_OFF: why["멀다"] += 1; continue
        drc = (r.get("roadRouteDrc") or "").strip()
        place = (r.get("itlpc") or "")
        if drc in DRC_UP or "서울방향" in place or "부산→서울" in place: why["상행"] += 1; continue
        if drc not in DRC_DOWN and drc not in DRC_BOTH and side < 0: why["왼쪽(방향 글 없음)"] += 1; continue
        key = (round(s / 50), (r.get("regltSe") or "").strip())   # 같은 자리(50 m 안) 차로별 행(1,2차로·3,4차로·5차로)은 하나로
        if key in seen: why["같은 자리 중복"] += 1; continue
        seen.add(key)
        lim = (r.get("lmttVe") or "").strip()
        # role: 구간단속 시작·끝(설치장소 글의 '시점'·'종점'), 그 밖은 None(고정식 — 단속구분 코드 1 은 과속, 고속도로 구간단속 행은 99 로 실려 있다)
        role = "start" if "시점" in place else "end" if "종점" in place else None
        out.append({"s": round(s), "kind": (r.get("regltSe") or "").strip(), "role": role, "limit": int(lim) if lim.isdigit() and int(lim) > 0 else None,
                    "place": (r.get("itlpc") or "").strip(), "lat": round(lat, 6), "lon": round(lon, 6),
                    "ref": (r.get("mnlssRegltCameraManageNo") or "").strip(), "drc": drc, "off": round(d)})
    out.sort(key=lambda c: c["s"])
    route_file["cameras"] = [{k: v for k, v in c.items() if k != "off"} for c in out]
    src = "무인 교통단속카메라: 경찰청_전국무인교통단속카메라표준데이터(공공데이터포털 표준데이터, 저작자표시), fetch_speed_cameras.py 2026-11-15"
    if not any("무인교통단속카메라" in x for x in route_file["sources"]): route_file["sources"].append(src)
    ROUTE_F.write_text(json.dumps(route_file, ensure_ascii=False, indent=1), encoding="utf-8")   # 다른 build_* 와 같은 꼴(들여쓰기 1)
    print(f"원본 {len(rows)}건 → 하행 본선 {len(out)}건 · 뺀 까닭 {why}")
    for c in out: print(f"  s={c['s']:>6} {c['kind']:<8} {c['limit']} km/h  {c['place'][:30]}  방향='{c['drc']}' 선에서 {c['off']} m")


if __name__ == "__main__":
    sys.exit(main())
