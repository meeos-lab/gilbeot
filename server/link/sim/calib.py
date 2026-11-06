"""보정: 운전자 차간 시간(tau)·흔들림(sigma)·구경 감속별로 도로 중간(사고 지점 3 km 앞)과 사고 지점 하류의 처리 유량을 잰다.

사용: python -X utf8 calib.py  → results/calib.jsonl, 표 출력
기본 용량 = 수요를 넘치게 넣었을 때 사고 없는 도로 중간 지점 통과 유량(입구 정체와 무관하게).
사고 때 용량 = 차단 뒤 사고 지점 하류 통과 유량 / 기본 용량.
"""
import itertools
import json
import multiprocessing as mp
import os
import statistics
from pathlib import Path

import tago_sim as S

OUT = S.RES / "calib.jsonl"


def measure(args):
    tau, sigma, blocked, gawk = args
    import libsumo as ts
    import traci.constants as tc
    work = S.RES / "_work" / f"c{os.getpid()}"
    net = S.build_net(work)
    c = {"seed": 7, "demand": 9000, "blocked": blocked, "dur": 3000, "rain": False, "inatt": 0.15, "comply": 0.7, "truck": 0.15, "tau": tau, "sigma": sigma}
    rou = S.build_routes(work, c, 2400, f"cal")
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", "0.5", "--no-step-log", "true", "--no-warnings", "true", "--end", "2400", "--time-to-teleport", "-1"])
    ts.route.add("rinc", ["inc", "down"])
    mid, down = S.INC_POS - 3000, S.INC_POS + 500
    last = {}
    n_mid, n_down = 0, 0
    while ts.simulation.getTime() < 2400:
        ts.simulationStep(); t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            if not v.startswith("crash"):
                ts.vehicle.subscribe(v, [tc.VAR_DISTANCE])
        if blocked and abs(t - 600) < 0.25:
            for k in range(blocked):
                ts.vehicle.add(f"crash{k}", "rinc", typeID="car", depart="now", departLane=str(k), departPos="290", departSpeed="0")
                ts.vehicle.setStop(f"crash{k}", "inc", pos=300.0, laneIndex=k, duration=3000)
            if gawk:
                for k in range(blocked, S.LANES):
                    ts.lane.setMaxSpeed(f"inc_{k}", gawk / 3.6)
        sub = ts.vehicle.getAllSubscriptionResults()
        for v, d in sub.items():
            x = d[tc.VAR_DISTANCE]; px = last.get(v)
            if px is not None and t > 1200:
                if px < mid <= x:
                    n_mid += 1
                if px < down <= x:
                    n_down += 1
            last[v] = x
    ts.close()
    return {"tau": tau, "sigma": sigma, "blocked": blocked, "gawk": gawk, "mid": n_mid / 1200 * 3600, "down": n_down / 1200 * 3600}


if __name__ == "__main__":
    grid = [(tau, sg, 0, None) for tau in (1.0, 0.8, 0.7, 0.6) for sg in (0.5, 0.3)]
    grid += [(tau, sg, b, g) for tau in (1.0, 0.8, 0.7, 0.6) for sg in (0.5, 0.3) for b in (1, 2) for g in (None, 70, 50, 35)]
    with mp.get_context("spawn").Pool(28) as pool:
        rows = pool.map(measure, grid)
    OUT.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    base = {(r["tau"], r["sigma"]): r["mid"] for r in rows if r["blocked"] == 0}
    for (tau, sg), b in sorted(base.items()):
        line = [f"tau {tau} sigma {sg}: 기본 {b:.0f}대/시(차로당 {b / 4:.0f})"]
        for bl in (1, 2):
            for g in (None, 70, 50, 35):
                r = next(x for x in rows if x["tau"] == tau and x["sigma"] == sg and x["blocked"] == bl and x["gawk"] == g)
                line.append(f"{bl}차로·{g or '-'} {r['down'] / b:.2f}")
        print(" | ".join(line), flush=True)
