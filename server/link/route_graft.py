# -*- coding: utf-8 -*-
"""실제 경로로 경로 파일 만들기(2026-11-14, 백로그 B-107) — 앱 `engine/RouteGraft.kt` 와 같은 규칙·같은 결과.

허브(link_server.py · 앱 LinkHub)는 경로 파일 하나(route·restAreas·zones·junctions·erExits·evStations)로 만들어진다.
길 찾기(TMAP)로 받은 실제 경로 좌표로 같은 형식의 파일을 만들면 함께 가기·위험 공유·일행·시연 각본이 그 경로 위에서 돈다.
경로에 딸린 자료는 **지어내지 않는다**: 기준 파일(경부고속도로 하행)의 휴게소·구역·나들목·응급실 출구·충전소 가운데
새 경로 위에 있고(가로 거리 한계 안) 진행 방향이 같은 것만 새 자리(s)로 옮겨 싣는다. 없으면 빈 목록이다.

  python -X utf8 route_graft.py <좌표 파일(json: {"pts": [[위도, 경도], …]})> <목적지 이름> <출력 파일>
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ON_ROUTE_M = 60.0        # 구역 끝·응급실 출구·나들목: 새 경로에서 이 안에 있어야 '경로 위'
REST_EXTRA_M = 120.0     # 휴게소·충전소: 기준 경로에서 떨어진 거리(offset) + 이만큼 안
SAME_DIR_COS = 0.5       # 진행 방향이 같다 = 두 방향의 사이각 60° 안
CLASS_MIN_M = 300.0      # 도로 구분: 이보다 짧은 토막(고가·램프가 기준 경로를 스친 것)은 앞 토막의 구분을 따른다
ZONE_LEN_TOL = 0.25      # 구역 길이가 기준과 이 비율 넘게 다르면 싣지 않는다(경로가 구역 중간에서 갈라진 것)
MIN_PTS = 2


class Geo:
    """허브와 같은 평면 근사(위도 평균으로 경도 축척)와 같은 투영."""

    def __init__(self, pts):
        self.lat0 = sum(p[0] for p in pts) / len(pts)
        self.kx = 111320.0 * math.cos(math.radians(self.lat0))
        self.ky = 110540.0
        self.xy = [(p[1] * self.kx, p[0] * self.ky) for p in pts]
        self.cum = [0.0]
        for a, b in zip(self.xy, self.xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.cum[-1]

    def to_xy(self, lat, lon):
        return lon * self.kx, lat * self.ky

    def project(self, lat, lon):
        """(경로 위 거리 s, 경로까지 거리 d, 그 구간 번호)"""
        px, py = self.to_xy(lat, lon)
        best, bs, bi = float("inf"), 0.0, 0
        for i in range(len(self.xy) - 1):
            ax, ay = self.xy[i]
            bx, by = self.xy[i + 1]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d < best:
                best, bs, bi = d, self.cum[i] + t * math.sqrt(l2), i
        return bs, best, bi

    def seg_at(self, s):
        s = max(0.0, min(self.length, s))
        for i in range(len(self.cum) - 1):
            if self.cum[i + 1] >= s:
                return i
        return len(self.cum) - 2

    def point_at(self, s):
        s = max(0.0, min(self.length, s))
        i = self.seg_at(s)
        seg = (self.cum[i + 1] - self.cum[i]) or 1e-9
        t = (s - self.cum[i]) / seg
        ax, ay = self.xy[i]
        bx, by = self.xy[i + 1]
        return (ay + t * (by - ay)) / self.ky, (ax + t * (bx - ax)) / self.kx

    def dir_of(self, i):
        """구간 i 의 진행 방향(북쪽·동쪽 m 단위 벡터) — 두 경로의 축척이 달라도 견줄 수 있게 m 로"""
        ax, ay = self.xy[i]
        bx, by = self.xy[i + 1]
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy) or 1e-9
        return dx / n, dy / n


def r1(x):
    return math.floor(x * 10 + 0.5) / 10


def graft(base, pts, name, name_en):
    """기준 경로 파일 base + 새 좌표 pts([[위도, 경도], …]) → 새 경로 파일(dict). 좌표가 MIN_PTS 미만이면 ValueError"""
    if len(pts) < MIN_PTS:
        raise ValueError("좌표가 모자란다")
    old, new = Geo(base["route"]), Geo(pts)

    def same_dir(old_s, new_i):
        ox, oy = old.dir_of(old.seg_at(old_s))
        nx, ny = new.dir_of(new_i)
        return ox * nx + oy * ny >= SAME_DIR_COS

    def move_point(lat, lon, old_s, limit):
        s, d, i = new.project(lat, lon)
        return (s, d) if d <= limit and same_dir(old_s, i) else None

    rests, rest_map = [], {}
    for r in base.get("restAreas", []):
        m = move_point(r["lat"], r["lon"], r["s"], r.get("offset", 0) + REST_EXTRA_M)
        if m is None:
            continue
        rests.append({**r, "s": r1(m[0]), "offset": r1(m[1])})
        rest_map[r["s"]] = r1(m[0])
    rests.sort(key=lambda r: r["s"])

    zones = []
    for z in base.get("zones", []):
        a = move_point(*old.point_at(z["s0"]), z["s0"], ON_ROUTE_M)
        b = move_point(*old.point_at(z["s1"]), z["s1"], ON_ROUTE_M)
        if a is None or b is None or b[0] <= a[0]:
            continue
        was = z["s1"] - z["s0"]
        if was > 0 and abs((b[0] - a[0]) - was) > ZONE_LEN_TOL * was:
            continue
        zones.append({**z, "s0": r1(a[0]), "s1": r1(b[0])})
    zones.sort(key=lambda z: z["s0"])

    juncs = []
    for j in base.get("junctions", []):
        m = move_point(j["lat"], j["lon"], j["s"], ON_ROUTE_M + j.get("offset", 0))
        if m is not None:
            juncs.append({**j, "s": r1(m[0]), "offset": r1(m[1])})
    juncs.sort(key=lambda j: j["s"])
    junc_ids = {j["id"] for j in juncs}

    exits = []
    for e in base.get("erExits", []):
        if "junction" in e and e["junction"] not in junc_ids:
            continue
        m = move_point(*old.point_at(e["s"]), e["s"], ON_ROUTE_M)
        if m is not None:
            exits.append({**e, "s": r1(m[0])})
    exits.sort(key=lambda e: e["s"])

    evs = []
    for e in base.get("evStations", []):
        if e["rest"] not in rest_map:
            continue
        m = move_point(e["lat"], e["lon"], e["s"], e.get("offset", 0) + REST_EXTRA_M)
        if m is not None:
            evs.append({**e, "rest": rest_map[e["rest"]], "s": r1(m[0]), "offset": r1(m[1])})
    evs.sort(key=lambda e: e["s"])

    # 도로 구분(방향 구분이 쓴다 — 고속도로는 맞은편 위험을 빼고 일반 도로는 낮은 단계로): 구간 가운데 점이 기준 경로(고속도로) 위·같은 방향이면
    # motorway, 아니면 road. 이어진 같은 구분은 한 줄로 묶는다. 길 찾기 응답의 도로 종류 값은 쓰지 않는다(값이 오는지 확인 전 — 어림)
    runs = []
    for i in range(len(new.xy) - 1):
        m = new.point_at((new.cum[i] + new.cum[i + 1]) / 2)
        _, od, oi = old.project(m[0], m[1])
        o, n = old.dir_of(oi), new.dir_of(i)
        cls = "motorway" if od <= ON_ROUTE_M and o[0] * n[0] + o[1] * n[1] >= SAME_DIR_COS else "road"
        if runs and runs[-1][2] == cls:
            runs[-1][1] = new.cum[i + 1]
        else:
            runs.append([new.cum[i], new.cum[i + 1], cls])
    while True:                                            # 짧은 토막을 앞 토막(맨 앞이면 뒤 토막)에 붙인다 — 앞에서부터 하나씩
        k = next((j for j, r in enumerate(runs) if r[1] - r[0] < CLASS_MIN_M), -1)
        if k < 0 or len(runs) < 2:
            break
        runs[k][2] = runs[k - 1][2] if k > 0 else runs[k + 1][2]
        merged = []
        for r in runs:
            if merged and merged[-1][2] == r[2]:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        runs = merged
    classes = [{"s0": r1(r[0]), "s1": r1(r[1]), "cls": r[2]} for r in runs]

    # 단속카메라(11-15): 새 경로 위·같은 방향만. 구간단속(kind 99)은 시작·끝 짝이 모두 옮겨졌을 때만 남긴다(앱 RouteGraft 와 같은 규칙)
    cams_all = []
    for c in base.get("cameras", []):
        if "lat" not in c or "lon" not in c:
            continue
        m = move_point(c["lat"], c["lon"], c["s"], ON_ROUTE_M)
        if m is not None:
            cams_all.append({**c, "s": r1(m[0])})
    cams_all.sort(key=lambda c: c["s"])
    cams, opened = [], None
    for c in cams_all:
        role = c.get("role") if c.get("kind") == "99" else ""
        if role == "start":
            opened = c
        elif role == "end":
            if opened is not None:
                cams += [opened, c]
            opened = None
        else:
            cams.append(c)
    cams.sort(key=lambda c: c["s"])

    return {
        "name": name, "nameEn": name_en,
        "route": [[p[0], p[1]] for p in pts],
        "length": int(math.floor(new.length + 0.5)),
        "restAreas": rests, "zones": zones, "junctions": juncs, "erExits": exits, "evStations": evs, "cameras": cams, "classes": classes,
        "sources": list(base.get("sources", [])) + ["경로 좌표: TMAP 자동차 경로 안내 API(SK 텔레콤) — 실제 위치에서 목적지까지"],
        "graft": {"from": base.get("name", ""), "rule": "기준 경로 자료 가운데 새 경로 위·같은 방향인 것만 옮김"},
    }


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = json.loads((HERE / "gyeongbu_route.json").read_text(encoding="utf-8"))
    dest = sys.argv[2]
    out = graft(base, src["pts"], "현재 위치 → %s" % dest, "Current location → %s" % dest)
    Path(sys.argv[3]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("경로 %.1f km · 점 %d · 휴게소 %d · 구역 %d · 나들목 %d · 응급실 출구 %d · 충전소 %d" % (
        out["length"] / 1000, len(out["route"]), len(out["restAreas"]), len(out["zones"]), len(out["junctions"]), len(out["erExits"]), len(out["evStations"])))
    for k in ("restAreas", "zones", "junctions", "erExits"):
        for x in out[k]:
            print("  %s %s s=%s" % (k, x.get("name"), x.get("s", x.get("s0"))))


if __name__ == "__main__":
    main()
