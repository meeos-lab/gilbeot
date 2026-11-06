"""검증 V3·V3b: 차단 차로·처리 시간이 기록된(ITS 돌발 이력) 보지 않은 사고를, 조합을 고르지 않고 그대로 넣어 재현한다(사전 고정 'V3'·'V3b').

  python -X utf8 v3_replay.py obs                 # 후보 사고일의 콘존 속도 실측·평소(±4주 같은 요일 중앙값) → data/v3_obs.json
  TAGO_V3_TAG=krauss [TAGO_V3_SET=b] ... python -X utf8 v3_replay.py run      # Krauss(v2 설정). SET=b 면 V3b 사고(부산행 저녁·서울행)만
  TAGO_V3_TAG=idm TAGO_CF=IDM TAGO_TAU=0.4 TAGO_DECEL=2.0 ... python -X utf8 v3_replay.py run   # IDM(b 2, T 0.4)
  python -X utf8 v3_replay.py report              # → results/report_v3.json, report_v3.md (V3 + V3b 파일을 모두 읽는다)
모형·검지기·콘존 속도 계산은 replay.py 와 같다. 다른 점: 방향(부산행 = CZS 콘존·'기점' 교통량, 서울행 = CZE 콘존·'종점' 교통량)과
시간대(아침 06~11시, 저녁 17~22시)를 사고마다 쓴다. 사고마다 (막힌 차로 수, 처리 시간)을 ITS 기록대로 고정하고 씨앗 1~3 을 돌린다.
판정(사고 단위): 비율(사고일/평소) RMSE 를 '사고 없음'(비율 1) 과 비교, 씨앗 3개 범위(±0.02)가 실측을 덮는 칸 비율, 사고 시간대 편향(예측−실측).
"""
import csv
import datetime as dt
import gzip
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import replay as R
import tago_sim as S

HERE = Path(__file__).parent
CAND = HERE / "data" / "v3_candidates.csv"
OBSF = HERE / "data" / "v3_obs.json"
SPEED = HERE / "data" / "gyeongbu_speed.csv.gz"
TAG = os.environ.get("TAGO_V3_TAG", "krauss")
SET = os.environ.get("TAGO_V3_SET", "")           # "" = V3(부산행 아침), "b" = V3b(그 밖)
OUT = S.RES / f"replay_v3{SET}_{TAG}.jsonl"
# 교통량(대/시): data/commute_volume_20251231.csv 기흥~수원신갈. 아침 06·10시는 09시 값, 저녁 17·21시는 18·20시 값(가정)
DEMAND = {"부산행": {6: 6128, 7: 6691, 8: 6837, 9: 6128, 10: 6128, 17: 4235, 18: 4235, 19: 3982, 20: 4103, 21: 4103},
          "서울행": {6: 5731, 7: 6306, 8: 6168, 9: 5731, 10: 5731, 17: 3836, 18: 3836, 19: 3488, 20: 4236, 21: 4236}}
T0 = {"morning": 6, "evening": 17}
ZONES = {"부산행": {"0010CZS460": ("서울TG-신갈JC", 402.6, 394.96), "0010CZS450": ("신갈JC-수원신갈IC", 394.96, 392.28), "0010CZS440": ("수원신갈IC-기흥IC", 392.28, 387.19)},
         "서울행": {"0010CZE440": ("기흥IC-수원신갈IC", 387.19, 392.28), "0010CZE450": ("수원신갈IC-신갈JC", 392.28, 394.96), "0010CZE460": ("신갈JC-서울TG", 394.96, 402.6)}}
SEEDS = [1, 2, 3]
T_END = 5 * 3600


def candidates():
    out = []
    for r in csv.DictReader(CAND.open(encoding="utf-8-sig")):
        if int(r["used_before"]) or not r["km"]:
            continue
        hh, mm = map(int, r["time"].split(":"))
        out.append({"day": r["day"], "dir": r["dir"], "window": r["window"], "km": float(r["km"]), "t_inc": (hh - T0[r["window"]]) * 3600 + mm * 60,
                    "blocked": int(r["n_lanes"]), "dur_min": float(r["dur_min"])})
    return out


def in_set(c):
    return (c["dir"] == "부산행" and c["window"] == "morning") if SET == "" else not (c["dir"] == "부산행" and c["window"] == "morning")


def build_obs():
    data = {}
    allz = {z for d in ZONES.values() for z in d}
    with gzip.open(SPEED, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["zone"] in allz:
                v = float(r["speed"])
                if v > 0:
                    data[(r["date"].replace("-", ""), r["zone"], int(r["hour"]))] = v   # 날짜가 20221201 과 2023-01-01 두 꼴로 섞여 있다
    res = []
    for c in candidates():
        d = dt.date.fromisoformat(c["day"]); key = d.strftime("%Y%m%d")
        base_days = [(d + dt.timedelta(days=7 * k)).strftime("%Y%m%d") for k in (-4, -3, -2, -1, 1, 2, 3, 4)]
        hours = list(range(T0[c["window"]], T0[c["window"]] + 5))
        zones = {}
        for z, (name, a, b) in ZONES[c["dir"]].items():
            rows = {}
            for h in hours:
                v = data.get((key, z, h)); base = [data[(bd, z, h)] for bd in base_days if (bd, z, h) in data]
                if v is None or len(base) < 3:
                    continue
                med = statistics.median(base)
                rows[h] = {"day": v, "base_med": med, "n": len(base), "ratio": v / med}
            zones[z] = {"name": name, "from_km": a, "to_km": b, "hours": rows}
        res.append({**c, "hours": hours, "zones": zones, "n_cells": sum(len(z["hours"]) for z in zones.values())})
    OBSF.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for o in res:
        print(o["day"], o["dir"], o["window"], o["km"], o["blocked"], o["dur_min"], "cells", o["n_cells"])


def routes(work, c, case, tag):
    r = random.Random(f"flow|{c['seed']}")
    head = S.build_routes(work, {**c, "blocked": 0, "dur": 0, "demand": 1}, 1, f"{tag}_types").read_text(encoding="utf-8")
    types = head[head.index("<vType"):head.index("<route ")]
    dem, t0 = DEMAND[case["dir"]], T0[case["window"]]
    vehs, t, i, crash_done = [], 0.0, 0, not c["blocked"]
    while t < T_END:
        t += r.expovariate(dem[t0 + int(t // 3600)] / 3600.0)
        if not crash_done and t >= case["t_inc"]:
            crash_done = True
            for k in range(c["blocked"]):
                vehs.append(f'<vehicle id="crash{k}" type="car" route="rinc" depart="{case["t_inc"]:.2f}" departLane="{k}" departPos="290" departSpeed="0" '
                            f'insertionChecks="none"><stop lane="inc_{k}" endPos="300" duration="{c["dur"]}"/></vehicle>')
        typ = "truck" if r.random() < c["truck"] else ("car_i" if r.random() < c["inatt"] else "car")
        vehs.append(f'<vehicle id="v{i}" type="{typ}" route="r" depart="{t:.2f}" departLane="best" departSpeed="desired"/>')
        i += 1
    p = work / f"r_{tag}.rou.xml"
    p.write_text(f'<routes>{types}<route id="r" edges="up inc down"/><route id="rinc" edges="inc down"/>{"".join(vehs)}</routes>', encoding="utf-8")
    return p


def run(job):
    case, seed = job
    import libsumo as ts
    work = S.RES / "_work" / f"v3{os.getpid()}"
    net = S.build_net(work)
    blocked, dur_min = case["blocked"], int(round(case["dur_min"]))
    c = {**S.cond_for(seed), "blocked": blocked, "dur": dur_min * 60, "rain": 0, "inatt": 0.20}
    tag = f"{case['day']}_{blocked}_{dur_min}_{seed}"
    rou = routes(work, c, case, tag)
    add, det = R.detectors(work, tag)
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "-a", str(add), "--step-length", str(S.STEP), "--seed", str(seed), "--no-step-log", "true",
              "--no-warnings", "true", "--collision.action", "warn", "--time-to-teleport", "-1", "--end", str(T_END)])
    if blocked:
        ts.simulationStep(case["t_inc"])
        g = dict(S.PARAMS["gawk"])[blocked]
        for k in range(blocked, S.LANES):
            ts.lane.setMaxSpeed(f"inc_{k}", g / 3.6)
        ts.simulationStep(case["t_inc"] + dur_min * 60)
        for k in range(S.LANES):
            ts.lane.setMaxSpeed(f"inc_{k}", S.VMAX)
    ts.simulationStep(T_END)
    ts.close()
    acc = {}
    t0 = T0[case["window"]]
    for iv in ET.parse(det).getroot().iter("interval"):
        n, v = int(iv.get("nVehContrib")), float(iv.get("speed"))
        if n <= 0 or v < 0:
            continue
        x = int(iv.get("id")[1:].split("_")[0])
        h = t0 + int(float(iv.get("begin")) // 3600)
        a = acc.setdefault((x, h), [0.0, 0])
        a[0] += v * n; a[1] += n
    det.unlink(missing_ok=True)
    return {"day": case["day"], "dir": case["dir"], "window": case["window"], "blocked": blocked, "dur_min": dur_min, "seed": seed,
            "det": [[x, h, a[0] / a[1] * 3.6, a[1]] for (x, h), a in acc.items()]}


def run_all():
    obs = [o for o in json.loads(OBSF.read_text(encoding="utf-8")) if in_set(o)]
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            d = json.loads(line); done.add((d["day"], d["seed"]))
    jobs = [(o, s) for o in obs for s in SEEDS if (o["day"], s) not in done]
    strata = sorted({(o["dir"], o["window"]) for o in obs})
    for d, w in strata:                      # 층(방향·시간대)마다 '사고 없음' 기준 실행
        ref = next(o for o in obs if o["dir"] == d and o["window"] == w)
        jobs += [({**ref, "day": f"base_{d}_{w}", "blocked": 0, "dur_min": 0}, s) for s in SEEDS if (f"base_{d}_{w}", s) not in done]
    print(len(jobs), "실행 →", OUT.name, flush=True)
    with mp.get_context("spawn").Pool(min(len(jobs), int(os.environ.get("TAGO_PROCS", 0)) or max(1, os.cpu_count() - 4))) as pool, OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(pool.imap_unordered(run, jobs), 1):
            f.write(json.dumps(r) + "\n"); f.flush()
            print(f"  {i}/{len(jobs)} {r['day']} 씨앗{r['seed']}", flush=True)


def zone_speed(det, km_inc, zone, h, direction):
    """콘존(이정 a→b)의 시뮬레이션 속도. 사고 지점 = INC_POS, 진행 방향으로 상류가 x < INC_POS"""
    a, b = zone["from_km"], zone["to_km"]
    sgn = 1.0 if direction == "부산행" else -1.0          # 부산행: 이정이 줄어드는 쪽으로 진행(상류 = 큰 이정)
    xs = sorted((S.INC_POS - sgn * (a - km_inc) * 1000, S.INC_POS - sgn * (b - km_inc) * 1000))
    num = den = 0.0
    for x, hh, v, n in det:
        if hh == h and xs[0] <= x <= xs[1] and x >= 1000:
            num += v * n; den += n
    return num / den if den else None


def report():
    obs = {o["day"]: o for o in json.loads(OBSF.read_text(encoding="utf-8"))}
    out, L = {}, ["# 검증 V3·V3b: 차단 차로·처리 시간을 ITS 기록대로 넣은 보지 않은 사고 재현", ""]
    for tag in ("krauss", "idm"):
        rows = []
        for p in (S.RES / "mac" / f"replay_v3_{tag}.jsonl", S.RES / "mac" / f"replay_v3b_{tag}.jsonl"):   # 맥 결과는 results/mac/ 에만 둔다
            if p.exists():
                rows += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        if not rows:
            continue
        per = []
        for day, o in obs.items():
            sims = [r for r in rows if r["day"] == day]
            bname = "base" if (o["dir"] == "부산행" and o["window"] == "morning") else f"base_{o['dir']}_{o['window']}"
            base = [r for r in rows if r["day"] in (bname, f"base_{o['dir']}_{o['window']}")]
            if not sims or not base:
                continue
            cells = []
            for z, zo in o["zones"].items():
                for h in o["hours"]:
                    ob = zo["hours"].get(str(h))
                    if not ob:
                        continue
                    bvals = [zone_speed(r["det"], o["km"], zo, h, o["dir"]) for r in base]; bvals = [v for v in bvals if v]
                    svals = [zone_speed(r["det"], o["km"], zo, h, o["dir"]) for r in sims]; svals = [v for v in svals if v]
                    if not bvals or not svals:
                        continue
                    bm = statistics.mean(bvals); ratios = [v / bm for v in svals]
                    cells.append({"zone": z, "hour": h, "obs": ob["ratio"], "pred": statistics.mean(ratios), "lo": min(ratios), "hi": max(ratios),
                                  "inside": min(ratios) - 0.02 <= ob["ratio"] <= max(ratios) + 0.02})
            if not cells:
                continue
            rmse = (sum((c["pred"] - c["obs"]) ** 2 for c in cells) / len(cells)) ** 0.5
            null = (sum((1.0 - c["obs"]) ** 2 for c in cells) / len(cells)) ** 0.5
            h_inc = T0[o["window"]] + int(o["t_inc"] // 3600)
            inc_cells = [c for c in cells if c["hour"] in (h_inc, h_inc + 1)]
            bias = statistics.mean(c["pred"] - c["obs"] for c in inc_cells) if inc_cells else None
            per.append({"day": day, "dir": o["dir"], "window": o["window"], "km": o["km"], "blocked": o["blocked"], "dur_min": o["dur_min"], "n": len(cells),
                        "rmse": round(rmse, 3), "rmse_null": round(null, 3), "better_than_null": rmse < null,
                        "coverage": round(sum(c["inside"] for c in cells) / len(cells), 2), "bias_incident_hours": None if bias is None else round(bias, 3), "cells": cells})
        if not per:
            continue
        summ = lambda ps: {"n_incidents": len(ps), "better_share": round(sum(p["better_than_null"] for p in ps) / len(ps), 2),
                           "rmse_median": round(statistics.median(p["rmse"] for p in ps), 3), "rmse_null_median": round(statistics.median(p["rmse_null"] for p in ps), 3),
                           "coverage_mean": round(statistics.mean(p["coverage"] for p in ps), 2),
                           "bias_median": round(statistics.median(p["bias_incident_hours"] for p in ps if p["bias_incident_hours"] is not None), 3)}
        out[tag] = {"all": summ(per), "strata": {f"{d}_{w}": summ([p for p in per if p["dir"] == d and p["window"] == w])
                                                 for d, w in sorted({(p["dir"], p["window"]) for p in per})}, "incidents": per}
        a = out[tag]["all"]
        L += [f"## {tag}: 사고 {a['n_incidents']}건 — '사고 없음'보다 나은 사고 {a['better_share'] * 100:.0f} %, RMSE 중앙값 {a['rmse_median']} (사고 없음 {a['rmse_null_median']}), 씨앗 범위 포함률 {a['coverage_mean']}, 사고 시간대 편향 중앙값 {a['bias_median']:+.3f}", ""]
        for k, v in out[tag]["strata"].items():
            L.append(f"- {k}: {v['n_incidents']}건, 나음 {v['better_share'] * 100:.0f} %, RMSE {v['rmse_median']} (사고 없음 {v['rmse_null_median']}), 포함 {v['coverage_mean']}, 편향 {v['bias_median']:+.3f}")
        L += ["", "| 사고 | 방향 | 시간대 | km | 차단 | 처리(분) | 칸 | RMSE | 사고 없음 | 나음 | 포함 | 편향 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for p in per:
            L.append(f"| {p['day']} | {p['dir']} | {p['window']} | {p['km']} | {p['blocked']} | {p['dur_min']:.0f} | {p['n']} | {p['rmse']} | {p['rmse_null']} | {'예' if p['better_than_null'] else '아니오'} | {p['coverage']} | {p['bias_incident_hours']} |")
        L.append("")
    if "krauss" in out and "idm" in out:
        pairs = [(k["rmse"], i["rmse"]) for k in out["krauss"]["incidents"] for i in out["idm"]["incidents"] if k["day"] == i["day"]]
        if pairs:
            L += [f"Krauss 대 IDM(같은 사고 {len(pairs)}건): IDM 이 RMSE 가 작은 사고 {sum(1 for k, i in pairs if i < k)}건, 중앙값 차이(IDM−Krauss) {statistics.median(i - k for k, i in pairs):+.3f}", ""]
    (S.RES / "report_v3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (S.RES / "report_v3.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"obs": build_obs, "run": run_all, "report": report}[cmd]()
