"""함께 가기 시연 경로 만들기: 경부고속도로 하행(양재 → 천안) 본선 경로선과 그 방향 휴게소.

사용: python build_highway_route.py <gyeongbu_raw.json> <out gyeongbu_route.json>
- 본선(motorway, ref 1)은 일방 도로라 방향 그래프로 잇고, 출발점 → 도착점 최단 경로가 곧 하행 차로다
- 휴게소는 경로 오른쪽(진행 방향) 400m 안의 services/rest_area만 남긴다(반대 방향 휴게소 제외)
- 출처: © OpenStreetMap contributors (ODbL)
"""
import heapq
import json
import math
import sys

START = (37.4685, 127.0425)    # 양재IC 부근(서울 출발)
END = (36.8330, 127.1720)      # 천안IC 부근
SIMPLIFY_M = 8.0
REST_RANGE = 400.0


def xy(lat, lon, lat0=37.15):
    return (lon * 111320.0 * math.cos(math.radians(lat0)), lat * 110540.0)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def simplify(pts, eps):
    """Douglas-Peucker (점 인덱스 목록 반환)"""
    if len(pts) < 3:
        return list(range(len(pts)))
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = pts[i], pts[j]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1e-9
        best, bi = 0.0, -1
        for k in range(i + 1, j):
            d = abs(dy * (pts[k][0] - a[0]) - dx * (pts[k][1] - a[1])) / L
            if d > best:
                best, bi = d, k
        if best > eps:
            keep.add(bi)
            stack += [(i, bi), (bi, j)]
    return sorted(keep)


def main(raw_path, out_path):
    data = json.load(open(raw_path, encoding="utf-8"))
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in data["elements"] if e["type"] == "node" and "lat" in e}
    adj = {}
    for e in data["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("highway") != "motorway":
            continue
        ids = [n for n in e["nodes"] if n in nodes]
        ow = t.get("oneway", "yes")          # motorway는 기본 일방
        pairs = list(zip(ids, ids[1:]))
        if ow == "-1":
            pairs = [(b, a) for a, b in pairs]
        for a, b in pairs:
            adj.setdefault(a, []).append(b)
            if ow == "no":
                adj.setdefault(b, []).append(a)
    P = {n: xy(*c) for n, c in nodes.items()}

    def nearest(pt, k=12):
        p = xy(*pt)
        return sorted((n for n in adj), key=lambda n: dist(P[n], p))[:k]

    targets = set(nearest(END, 12))
    best = None
    for s in nearest(START, 12):              # 하행 차로 출발 노드를 찾는다(상행 노드에서는 남쪽으로 못 감)
        D, prev, h = {s: 0.0}, {}, [(0.0, s)]
        while h:
            c, u = heapq.heappop(h)
            if u in targets:
                path = [u]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                best = path[::-1] if best is None or len(path) > 0 and c < best[0] else best
                best = (c, path[::-1])
                break
            if c > D.get(u, math.inf):
                continue
            for v in adj.get(u, []):
                nc = c + dist(P[u], P[v])
                if nc < D.get(v, math.inf):
                    D[v], prev[v] = nc, u
                    heapq.heappush(h, (nc, v))
        if best:
            break
    if not best:
        raise SystemExit("하행 경로를 찾지 못함")
    length, path = best
    pts = [P[n] for n in path]
    keep = simplify(pts, SIMPLIFY_M)
    route = [[round(nodes[path[i]][0], 6), round(nodes[path[i]][1], 6)] for i in keep]
    rxy = [pts[i] for i in keep]
    cum = [0.0]
    for a, b in zip(rxy, rxy[1:]):
        cum.append(cum[-1] + dist(a, b))

    def project(p):
        bs, bo, bd = 0.0, 0.0, math.inf
        for i, (a, b) in enumerate(zip(rxy, rxy[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            q = (a[0] + t * dx, a[1] + t * dy)
            d = dist(p, q)
            if d < bd:
                side = (dx * (p[1] - a[1]) - dy * (p[0] - a[0]))   # >0 왼쪽, <0 오른쪽
                bs, bo, bd = cum[i] + t * math.sqrt(L2), (-d if side > 0 else d), d
        return bs, bo                                           # bo > 0 = 진행 방향 오른쪽

    rests = []
    for e in data["elements"]:
        t = e.get("tags", {})
        if t.get("highway") not in ("services", "rest_area"):
            continue
        c = (e["lat"], e["lon"]) if "lat" in e else (e["center"]["lat"], e["center"]["lon"]) if "center" in e else None
        if not c:
            continue
        s, off = project(xy(*c))
        if 0 < off <= REST_RANGE and 0 < s < cum[-1]:
            rests.append({"name": t.get("name:ko") or t.get("name") or "휴게소", "nameEn": t.get("name:en", ""),
                          "kind": t["highway"], "lat": round(c[0], 6), "lon": round(c[1], 6), "s": round(s), "offset": round(off)})
    rests.sort(key=lambda r: r["s"])
    out = {"name": "경부고속도로 하행 (서울 양재 → 천안)", "nameEn": "Gyeongbu Expressway southbound (Seoul → Cheonan)",
           "route": route, "length": round(cum[-1]), "restAreas": rests,
           "sources": ["© OpenStreetMap contributors (ODbL) — Overpass API, 2026-10-25"]}
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"경로 {len(path)}→{len(route)}점, {cum[-1] / 1000:.1f}km, 휴게소 {len(rests)}곳")
    for r in rests:
        print(f"  {r['s'] / 1000:6.1f}km  {r['name']} ({r['kind']}, 오른쪽 {r['offset']}m)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
