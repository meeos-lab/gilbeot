"""실측 근거: 경부선 사고(2023~2025) × 1시간 구간 속도 → 사고가 만든 정체의 분포와 2차 사고.

  python -X utf8 evidence_prep.py     # 먼저
  python -X utf8 evidence.py          # → results/evidence.json, results/evidence.md

정의(분석 전에 고정, docs/sim-preregistration.md '실측 근거' 절):
- 평소 속도 = 앞뒤 4주 같은 요일 같은 시각 속도의 중앙값(최소 3일).
- 정체를 만든 사고 = 사고 콘존 또는 바로 위 콘존의 속도가 사고 시각 또는 다음 시간에 평소의 0.7 미만.
- 정체 길이(시간별) = 사고 지점에서 위쪽으로, 평소의 0.7 미만인 콘존이 끊기지 않고 이어진 끝까지의 거리(km).
- 2차 사고(정적 정의) = 같은 방향에서 0 < 시차 ≤ 2시간, 사고 지점 위쪽 0~5 km. 대조 = 같은 시차, 아래쪽 0~5 km.
- 2차 사고(동적 정의) = 위쪽에서 2시간 안, 그 시각 그 지점이 그 사고의 정체 길이 안.
"""
import csv
import datetime as dt
import gzip
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
DATA, RES = HERE / "data", HERE / "results"
SLOW, UP_KM, WIN_H = 0.7, 5.0, 2.0


def load():
    zones = json.loads((DATA / "gyeongbu_conzones.json").read_text(encoding="utf-8"))
    speed = {}
    with gzip.open(DATA / "gyeongbu_speed.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            speed[(r["date"], int(r["hour"]), r["zone"])] = float(r["speed"])
    acc = []
    with open(DATA / "accidents" / "accidents_2023_2025.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            if r["노선명"] != "경부선":
                continue
            hh, mm = map(int, r["사고시각"].split(":"))
            t = dt.datetime.fromisoformat(r["사고일자"]) + dt.timedelta(hours=hh, minutes=mm)
            acc.append({"t": t, "km": float(r["사고발생이정"]), "dir": "S" if r["방향"] == "부산" else "E",
                        "dead": int(r["사망"]), "hurt": int(r["부상"]), "cause": r["원인"]})
    return zones, speed, sorted(acc, key=lambda a: a["t"])


def zone_of(zones, d, km):
    for z, e in zones.items():
        if e["dir"] != d:
            continue
        lo, hi = sorted((e["from_km"], e["to_km"]))
        if lo < km <= hi:
            return z
    return None


def upstream_chain(zones, d, z0, max_km=30):
    """z0 에서 위쪽으로 이어지는 콘존(가까운 것부터). 하행(S)은 이정이 큰 쪽, 상행(E)은 작은 쪽이 위쪽"""
    chain, cur = [], zones[z0]
    while True:
        nxt = [z for z, e in zones.items() if e["dir"] == d and abs(e["to_km"] - cur["from_km"]) < 0.05]
        if not nxt:
            break
        z = nxt[0]
        chain.append(z); cur = zones[z]
        if abs(cur["from_km"] - zones[z0]["from_km"]) > max_km:
            break
    return chain


def ratio(speed, date, h, z):
    v = speed.get((date.isoformat(), h, z))
    if v is None:
        return None
    base = [speed[(d.isoformat(), h, z)] for k in (-4, -3, -2, -1, 1, 2, 3, 4)
            for d in [date + dt.timedelta(days=7 * k)] if (d.isoformat(), h, z) in speed]
    if len(base) < 3:
        return None
    return v / statistics.median(base)


def extent(zones, speed, a, z0, chain, t):
    """시각 t(시 단위)의 정체 길이: 사고 지점부터 위쪽으로 평소 0.7 미만이 이어진 끝까지(km)"""
    date, h = t.date(), t.hour
    r0 = ratio(speed, date, h, z0)
    if r0 is None or r0 >= SLOW:
        return 0.0, r0
    far = abs(zones[z0]["from_km"] - a["km"])
    for z in chain:
        r = ratio(speed, date, h, z)
        if r is None or r >= SLOW:
            break
        far = abs(zones[z]["from_km"] - a["km"])
    return far, r0


def boot(xs, n=5000):
    r = random.Random(1)
    m = sorted(statistics.mean(r.choices(xs, k=len(xs))) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n) - 1]


def main():
    zones, speed, acc = load()
    rows, skipped = [], 0
    for i, a in enumerate(acc):
        z0 = zone_of(zones, a["dir"], a["km"])
        if not z0:
            skipped += 1
            continue
        chain = upstream_chain(zones, a["dir"], z0)
        t0 = a["t"].replace(minute=0)
        ext = []
        for k in range(4):
            e, r0 = extent(zones, speed, a, z0, chain, t0 + dt.timedelta(hours=k))
            ext.append(e)
        r_h = [ratio(speed, (t0 + dt.timedelta(hours=k)).date(), (t0 + dt.timedelta(hours=k)).hour, z0) for k in range(2)]
        r_up = [ratio(speed, (t0 + dt.timedelta(hours=k)).date(), (t0 + dt.timedelta(hours=k)).hour, chain[0]) for k in range(2)] if chain else [None, None]
        known = [x for x in r_h + r_up if x is not None]
        if not known:
            skipped += 1
            continue
        impact = any(x < SLOW for x in known)
        dur = 0
        for e in ext:
            if e > 0: dur += 1
            else: break
        rows.append({"i": i, "t": a["t"].isoformat(), "km": a["km"], "dir": a["dir"], "zone": z0, "hurt": a["hurt"], "dead": a["dead"], "cause": a["cause"],
                     "impact": impact, "ext_km": ext, "max_ext": max(ext), "dur_h": dur, "r0": r_h, "r_up": r_up})
    by_i = {r["i"]: r for r in rows}
    # 2차 사고
    def later(a, sign, lo, hi):
        out = []
        for b in acc:
            dtm = (b["t"] - a["t"]).total_seconds() / 3600
            if dtm <= 0 or dtm > WIN_H or b["dir"] != a["dir"]:
                continue
            up = (b["km"] - a["km"]) if a["dir"] == "S" else (a["km"] - b["km"])   # 위쪽이면 +
            if lo <= sign * up <= hi:
                out.append((b, dtm, abs(up)))
        return out
    for r in rows:
        a = acc[r["i"]]
        r["sec_up"] = len(later(a, +1, 0.0, UP_KM))
        r["sec_down"] = len(later(a, -1, 0.001, UP_KM))
        dyn = 0
        for b, dtm, d in later(a, +1, 0.0, 30.0):
            k = int((b["t"].replace(minute=0) - a["t"].replace(minute=0)).total_seconds() // 3600)
            if 0 <= k < 4 and d <= r["ext_km"][k] + 0.5:
                dyn += 1
        r["sec_dyn"] = dyn
    day = [r for r in rows if 6 <= dt.datetime.fromisoformat(r["t"]).hour <= 20]
    imp = [r for r in day if r["impact"]]
    non = [r for r in day if not r["impact"]]
    def rate(xs, key):
        k = sum(1 for r in xs if r[key] > 0)
        return k, len(xs), k / len(xs) if xs else 0
    out = {"n_accidents": len(acc), "n_mapped": len(rows), "skipped": skipped, "n_day": len(day), "n_impact": len(imp),
           "impact_share": len(imp) / len(day) if day else None,
           "ext_impact": {"mean_max_km": statistics.mean(r["max_ext"] for r in imp) if imp else None,
                          "median_max_km": statistics.median(r["max_ext"] for r in imp) if imp else None,
                          "p90_max_km": sorted(r["max_ext"] for r in imp)[int(0.9 * len(imp))] if imp else None,
                          "share_over_6km": sum(r["max_ext"] > 6 for r in imp) / len(imp) if imp else None,
                          "mean_dur_h": statistics.mean(r["dur_h"] for r in imp) if imp else None,
                          "r0_first_hour_median": statistics.median([r["r0"][0] for r in imp if r["r0"][0] is not None])},
           "secondary": {
               "static_up_impact": rate(imp, "sec_up"), "static_up_nonimpact": rate(non, "sec_up"),
               "static_down_impact": rate(imp, "sec_down"), "static_down_nonimpact": rate(non, "sec_down"),
               "dynamic_impact": rate(imp, "sec_dyn")}}
    # 정체가 길수록 2차 사고가 느는가: 최대 정체 길이 구간별 위쪽 2차 사고 비율
    bins = [(0, 0.01), (0.01, 3), (3, 6), (6, 100)]
    out["secondary_by_extent"] = []
    for lo, hi in bins:
        xs = [r for r in day if lo <= r["max_ext"] < hi]
        if xs:
            k, n, p = rate(xs, "sec_up")
            out["secondary_by_extent"].append({"from_km": lo, "to_km": hi, "n": n, "k": k, "rate": p})
    out["rows"] = rows
    RES.mkdir(exist_ok=True)
    (RES / "evidence.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    s = out["secondary"]
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=1))





# 노선 종점 쪽 방향 값(그 방향으로 가면 이정이 커진다). 고속도로 노선 번호 규칙: 남북 노선은 남쪽, 동서 노선은 서쪽이 기점
END = {"경부선": "서울", "서해안선": "서울", "중부내륙선": "양평", "호남선": "천안", "중부선": "하남", "중앙선": "춘천", "남해선": "부산",
       "무안광주선": "광주", "순천완주선": "완주", "서1울양양선": "양양", "함양울산선": "울산", "평택제천선": "제천", "제2중부선": "하남",
       "ㄷ당진대전선": "대전", "광주대구선": "대구", "세종포천선": "포천", "ㄷ청주상주선": "상주"}


def national():
    """전국(정적 정의): 사고 뒤 같은 노선·방향 2시간 안 5 km 안의 사고가 위쪽(정체 쪽)인가 아래쪽인가.
    정체와 무관한 우연이면 반반. 이정이 같은(0.05 km 미만) 쌍은 같은 사고를 따로 적었을 수 있어 따로 센다. 순환선 등 END 에 없는 노선은 뺀다."""
    from scipy.stats import binomtest
    acc = []
    with open(DATA / "accidents" / "accidents_2023_2025.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            hh, mm = map(int, r["사고시각"].split(":"))
            acc.append((r["노선명"], r["방향"], dt.datetime.fromisoformat(r["사고일자"]) + dt.timedelta(hours=hh, minutes=mm), float(r["사고발생이정"]), r["원인"]))
    acc.sort(key=lambda x: x[2])
    up, down, same, skip, by = [], [], 0, 0, defaultdict(lambda: [0, 0])
    for i, (rt, d, t, km, _) in enumerate(acc):
        for rt2, d2, t2, km2, cause2 in acc[i + 1:]:
            dtm = (t2 - t).total_seconds() / 60
            if dtm > WIN_H * 60:
                break
            if rt2 != rt or d2 != d or abs(km2 - km) > UP_KM:
                continue
            if rt not in END:
                skip += 1; continue
            delta = km2 - km
            if abs(delta) < 0.05:
                same += 1; continue
            is_up = (delta < 0) if d == END[rt] else (delta > 0)
            (up if is_up else down).append({"route": rt, "min": dtm, "km": abs(delta), "cause": cause2})
            by[rt][0 if is_up else 1] += 1
    bt = binomtest(len(up), len(up) + len(down), 0.5, alternative="greater")
    ci = bt.proportion_ci(confidence_level=0.95)
    return {"n_accidents": len(acc), "up": len(up), "down": len(down), "same_point": same, "skipped_routes": skip,
            "share_up": len(up) / (len(up) + len(down)), "share_up_ci": [ci.low, ci.high], "p_one_sided": bt.pvalue,
            "up_min_median": statistics.median(x["min"] for x in up), "up_km_median": statistics.median(x["km"] for x in up),
            "up_causes": dict(sorted(defaultdict(int, {c: sum(1 for x in up if x["cause"] == c) for c in {x["cause"] for x in up}}).items(), key=lambda kv: -kv[1])),
            "by_route": {k: {"up": v[0], "down": v[1]} for k, v in sorted(by.items(), key=lambda kv: -sum(kv[1]))}}


if __name__ == "__main__":
    main()
    nat = national()
    p = RES / "evidence.json"
    d = json.loads(p.read_text(encoding="utf-8")); d["national"] = nat
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(nat, ensure_ascii=False, indent=1))


def negative_control(shift_days=(7, -7, 14, -14), win_km=UP_KM):
    """시간 이동 대조군: 사고 시각을 ±N일 옮긴 창(0~2시간 뒤, 같은 노선·방향 5 km 안)의 사고. 첫 사고와 인과가 없으므로
    방향 코딩과 배경 분포가 치우치지 않았다면 위쪽 비율은 50 % 근처여야 한다. 실제 쌍의 위쪽 비율과 피셔 정확 검정으로 비교."""
    from scipy.stats import binomtest, fisher_exact
    acc = []
    with open(DATA / "accidents" / "accidents_2023_2025.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            hh, mm = map(int, r["사고시각"].split(":"))
            acc.append((r["노선명"], r["방향"], dt.datetime.fromisoformat(r["사고일자"]) + dt.timedelta(hours=hh, minutes=mm), float(r["사고발생이정"])))
    by_rd = defaultdict(list)
    for a in acc:
        by_rd[(a[0], a[1])].append(a)
    up = down = 0
    for (rt, d), xs in by_rd.items():
        if rt not in END:
            continue
        for _, _, t, km in xs:
            for sd in shift_days:
                t0 = t + dt.timedelta(days=sd)
                for _, _, t2, km2 in xs:
                    dtm = (t2 - t0).total_seconds()
                    if 0 < dtm <= WIN_H * 3600 and abs(km2 - km) <= win_km and abs(km2 - km) >= 0.05:
                        is_up = (km2 - km < 0) if d == END[rt] else (km2 - km > 0)
                        up += is_up; down += (not is_up)
    nat = national()
    fe = fisher_exact([[nat["up"], nat["down"]], [up, down]], alternative="greater")
    return {"shifts_days": list(shift_days), "control_up": up, "control_down": down,
            "control_share_up": up / (up + down) if up + down else None,
            "control_binom_p_two_sided": binomtest(up, up + down, 0.5).pvalue if up + down else None,
            "real_up": nat["up"], "real_down": nat["down"], "fisher_odds": fe.statistic, "fisher_p_one_sided": fe.pvalue}
