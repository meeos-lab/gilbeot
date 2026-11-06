"""실제 사고 재현 검증: 실측 사고 3건의 시각·위치로 시뮬레이션을 돌려, 콘존·시간대 평균 속도를 실측(data/obs.json)과 비교한다.

  python -X utf8 replay_obs.py      # 실측 먼저
  python -X utf8 replay.py run      # 시뮬레이션(사고 3건 × 막힌 차로 2 × 처리 시간 5 × 씨앗 3 + 사고 없음)
  python -X utf8 replay.py report   # 비교 → results/replay.json, results/replay.md

모형은 본 실험 엔진(tago_sim)과 같다(도로·차 종류·주시태만·구경 감속·사고 차 넣기). 다른 점:
- 시계: t = 0 이 06:00, 11:00 까지. 교통량은 시간대별(06·10시는 09시 값으로 가정, 07·08·09시는 실측 6,691·6,837·6,128대/시).
- 경고 없음(실제 그날의 공식 안내는 넣지 않았다 — 속도 흐름에는 작은 영향).
- 검지기: 차로마다 250 m 간격 유도 루프, 1시간 주기. 콘존 속도 = 콘존 안 검지기 속도의 통과 대수 가중 평균(VDS 와 같은 지점 시간 평균).
- 막힌 차로 수와 처리 시간은 사고 자료에 없어 격자로 돌리고, 실측과 가장 맞는 조합이 우리 조건 분포 안에 드는지 본다.
"""
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import tago_sim as S

HERE = Path(__file__).parent
OBS = HERE / "data" / "obs.json"
TAG = os.environ.get("TAGO_REPLAY_TAG", "")
ALL_CASES = os.environ.get("TAGO_REPLAY_CASES") == "all"   # 검증 V1: 2025-04-14(392.0 km)까지      # v2 재현: TAGO_REPLAY_TAG=_v2 + v2 환경 변수 → replay_v2.*
OUT = S.RES / f"replay{TAG}.jsonl"
T0_HOUR, T_END = 6, 5 * 3600                     # 06:00 ~ 11:00
DEMAND = {6: 6128, 7: 6691, 8: 6837, 9: 6128, 10: 6128}
DUR_MIN = [20, 40, 60, 90, 120]
SEEDS = [1, 2, 3]
DET_STEP = 250.0


def routes(work, c, t_inc, tag):
    r = random.Random(f"flow|{c['seed']}")
    head = S.build_routes(work, {**c, "blocked": 0, "dur": 0, "demand": 1}, 1, f"{tag}_types").read_text(encoding="utf-8")
    types = head[head.index("<vType"):head.index("<route ")]
    vehs, t, i, crash_done = [], 0.0, 0, not c["blocked"]
    while t < T_END:
        t += r.expovariate(DEMAND[T0_HOUR + int(t // 3600)] / 3600.0)
        if not crash_done and t >= t_inc:
            crash_done = True
            for k in range(c["blocked"]):
                vehs.append(f'<vehicle id="crash{k}" type="car" route="rinc" depart="{t_inc:.2f}" departLane="{k}" departPos="290" departSpeed="0" '
                            f'insertionChecks="none"><stop lane="inc_{k}" endPos="300" duration="{c["dur"]}"/></vehicle>')
        typ = "truck" if r.random() < c["truck"] else ("car_i" if r.random() < c["inatt"] else "car")
        vehs.append(f'<vehicle id="v{i}" type="{typ}" route="r" depart="{t:.2f}" departLane="best" departSpeed="desired"/>')
        i += 1
    p = work / f"r_{tag}.rou.xml"
    p.write_text(f'<routes>{types}<route id="r" edges="up inc down"/><route id="rinc" edges="inc down"/>{"".join(vehs)}</routes>', encoding="utf-8")
    return p


def detectors(work, tag):
    det, rows = work / f"det_{tag}.out.xml", []
    edges = (("up", 0.0, S.INC_POS - 300), ("inc", S.INC_POS - 300, S.INC_POS + 300), ("down", S.INC_POS + 300, S.LEN))
    x = DET_STEP
    while x < S.LEN - 20:
        for e, a, b in edges:
            if a + 5 <= x <= b - 5:
                for k in range(S.LANES):
                    rows.append(f'<inductionLoop id="d{int(x)}_{k}" lane="{e}_{k}" pos="{x - a:.1f}" period="3600" file="{det.name}"/>')
        x += DET_STEP
    p = work / f"det_{tag}.add.xml"
    p.write_text("<additional>" + "".join(rows) + "</additional>", encoding="utf-8")
    return p, det


def run(job):
    case, blocked, dur_min, seed = job
    import libsumo as ts
    work = S.RES / "_work" / f"rp{os.getpid()}"
    net = S.build_net(work)
    c = {**S.cond_for(seed), "blocked": blocked, "dur": dur_min * 60, "rain": 0, "inatt": 0.20}
    t_inc = (case["t_inc"] if blocked else 99999.0)
    tag = f"{case['day']}_{blocked}_{dur_min}_{seed}"
    rou = routes(work, c, t_inc, tag)
    add, det = detectors(work, tag)
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "-a", str(add), "--step-length", str(S.STEP), "--seed", str(seed), "--no-step-log", "true",
              "--no-warnings", "true", "--collision.action", "warn", "--time-to-teleport", "-1", "--end", str(T_END)])
    if blocked:
        ts.simulationStep(t_inc)
        g = dict(S.PARAMS["gawk"])[blocked]
        for k in range(blocked, S.LANES):
            ts.lane.setMaxSpeed(f"inc_{k}", g / 3.6)
        ts.simulationStep(t_inc + dur_min * 60)
        for k in range(S.LANES):
            ts.lane.setMaxSpeed(f"inc_{k}", S.VMAX)
    ts.simulationStep(T_END)
    ts.close()
    acc = {}
    for iv in ET.parse(det).getroot().iter("interval"):
        n, v = int(iv.get("nVehContrib")), float(iv.get("speed"))
        if n <= 0 or v < 0:
            continue
        x = int(iv.get("id")[1:].split("_")[0])
        h = T0_HOUR + int(float(iv.get("begin")) // 3600)
        a = acc.setdefault((x, h), [0.0, 0])
        a[0] += v * n; a[1] += n
    det.unlink(missing_ok=True)
    return {"day": case["day"], "blocked": blocked, "dur_min": dur_min, "seed": seed,
            "det": [[x, h, a[0] / a[1] * 3.6, a[1]] for (x, h), a in acc.items()]}


def cases():
    obs = json.loads(OBS.read_text(encoding="utf-8"))
    out = []
    for o in obs:
        hh, mm = map(int, o["time"].split(":"))
        lo = o["zones"]["0010CZS440" if ALL_CASES else "0010CZS450"]["to_km"]
        if lo < o["km"] <= o["zones"]["0010CZS450"]["from_km"]:   # 사고가 신갈JC~수원신갈IC 안(재현 대상), 검증 V1 은 수원신갈IC~기흥IC 까지
            out.append({"day": o["day"], "km": o["km"], "t_inc": (hh - T0_HOUR) * 3600 + mm * 60})
    return out


def run_all():
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            d = json.loads(line); done.add((d["day"], d["blocked"], d["dur_min"], d["seed"]))
    cs = cases()
    jobs = [(c, b, m, s) for c in cs for b in (1, 2) for m in DUR_MIN for s in SEEDS]
    jobs += [(cs[0] | {"day": "base"}, 0, 0, s) for s in SEEDS]
    jobs = [j for j in jobs if (j[0]["day"], j[1], j[2], j[3]) not in done]
    print(len(jobs), "실행", flush=True)
    with mp.get_context("spawn").Pool(min(len(jobs), int(os.environ.get("TAGO_PROCS", 0)) or max(1, os.cpu_count() - 4))) as pool, OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(pool.imap_unordered(run, jobs), 1):
            f.write(json.dumps(r) + "\n"); f.flush()
            print(f"  {i}/{len(jobs)} {r['day']} {r['blocked']}차로 {r['dur_min']}분 씨앗{r['seed']}", flush=True)


def zone_speed(det, km_inc, zone, h):
    """콘존(이정 a→b, 하행이라 a > b)의 시뮬레이션 속도: 사고 지점 = INC_POS 로 놓고 이정 차를 거리로"""
    a, b = zone["from_km"], zone["to_km"]
    x0, x1 = S.INC_POS - (a - km_inc) * 1000, S.INC_POS - (b - km_inc) * 1000
    num = den = 0.0
    for x, hh, v, n in det:
        if hh == h and x0 <= x <= x1 and x >= 1000:      # 들어오는 끝 1 km 는 뺀다
            num += v * n; den += n
    return num / den if den else None


def report():
    obs = {o["day"]: o for o in json.loads(OBS.read_text(encoding="utf-8"))}
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    base = [r for r in rows if r["day"] == "base"]
    out, L = {}, ["# 실제 사고 재현 검증", ""]
    zones_used = ["0010CZS460", "0010CZS450"]
    for day, o in obs.items():
        sims = [r for r in rows if r["day"] == day]
        if not sims:
            continue
        hours = [7, 8, 9, 10]
        obs_r = {(z, h): o["zones"][z]["hours"].get(str(h), {}).get("ratio") for z in zones_used for h in hours}
        obs_v = {(z, h): o["zones"][z]["hours"].get(str(h), {}).get("day") for z in zones_used for h in hours}
        fits = []
        for b in (1, 2):
            for m in DUR_MIN:
                rs = [r for r in sims if r["blocked"] == b and r["dur_min"] == m]
                if not rs:
                    continue
                sim_r, sim_v = {}, {}
                for z in zones_used:
                    for h in hours:
                        vals = [zone_speed(r["det"], o["km"], o["zones"][z], h) for r in rs]
                        bvals = [zone_speed(r["det"], o["km"], o["zones"][z], h) for r in base]
                        vals = [v for v in vals if v]; bvals = [v for v in bvals if v]
                        if vals and bvals:
                            sim_v[(z, h)] = statistics.mean(vals)
                            sim_r[(z, h)] = statistics.mean(vals) / statistics.mean(bvals)
                keys = [k for k in sim_r if obs_r.get(k)]
                rmse = (sum((sim_r[k] - obs_r[k]) ** 2 for k in keys) / len(keys)) ** 0.5 if keys else None
                fits.append({"blocked": b, "dur_min": m, "rmse_ratio": rmse,
                             "sim_ratio": {f"{z}@{h}": round(sim_r[(z, h)], 2) for (z, h) in sim_r},
                             "sim_speed": {f"{z}@{h}": round(sim_v[(z, h)], 1) for (z, h) in sim_v}})
        fits.sort(key=lambda f: f["rmse_ratio"] if f["rmse_ratio"] is not None else 9)
        out[day] = {"km": o["km"], "time": o["time"], "obs_ratio": {f"{z}@{h}": (round(v, 2) if v else None) for (z, h), v in obs_r.items()},
                    "obs_speed": {f"{z}@{h}": v for (z, h), v in obs_v.items()}, "fits": fits}
        L += [f"## {day} {o['time']} {o['km']} km ({o['hurt']}, {o['cause']})", "",
              "| 콘존·시 | 실측 속도 | 실측/평소 | " + " | ".join(f"{f['blocked']}차로 {f['dur_min']}분" for f in fits[:3]) + " |",
              "|---|---|---|" + "---|" * min(3, len(fits))]
        for z in zones_used:
            for h in hours:
                k = f"{z}@{h}"
                ov = obs_v.get((z, h))
                L.append(f"| {o['zones'][z]['name']} {h}시 | {'' if ov is None else round(ov)} | {out[day]['obs_ratio'][k] or ''} | " +
                         " | ".join(str(f["sim_ratio"].get(k, "")) for f in fits[:3]) + " |")
        L += ["", "맞춤 순위(비율 RMSE): " + ", ".join(f"{f['blocked']}차로 {f['dur_min']}분 {f['rmse_ratio']:.3f}" for f in fits[:5] if f["rmse_ratio"] is not None), ""]
    (S.RES / f"replay{TAG}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (S.RES / f"replay{TAG}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    run_all() if cmd == "run" else report()
