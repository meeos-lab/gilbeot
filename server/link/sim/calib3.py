"""보정 3: 주시태만 운전자가 섞인 상태에서 기본 용량(사고 없음)을 잰다 — 차간 시간 tau × 주의력 × 주시태만 비율."""
import multiprocessing as mp
import os

import tago_sim as S


def measure(args):
    tau, aware, inatt = args
    S.PARAMS["inatt_aware"] = aware
    import libsumo as ts
    import traci.constants as tc
    work = S.RES / "_work" / f"k{os.getpid()}"
    net = S.build_net(work)
    c = {"seed": 7, "demand": 9000, "blocked": 0, "dur": 0, "rain": 0, "inatt": inatt, "comply": 0.3, "truck": 0.15, "tau": tau, "sigma": 0.5}
    rou = S.build_routes(work, c, 1800, "k")
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", "0.5", "--no-step-log", "true", "--no-warnings", "true", "--end", "1800", "--time-to-teleport", "-1"])
    mid = S.INC_POS - 3000
    last, n = {}, 0
    while ts.simulation.getTime() < 1800:
        ts.simulationStep(); t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            ts.vehicle.subscribe(v, [tc.VAR_DISTANCE])
        for v, d in ts.vehicle.getAllSubscriptionResults().items():
            x = d[tc.VAR_DISTANCE]; px = last.get(v)
            if px is not None and t > 900 and px < mid <= x:
                n += 1
            last[v] = x
    ts.close()
    return tau, aware, inatt, n / 900 * 3600


if __name__ == "__main__":
    grid = [(tau, aw, ia) for tau in (0.4, 0.5, 0.6) for aw in (0.3, 0.5, 0.7) for ia in (0.2, 0.4)]
    with mp.get_context("spawn").Pool(18) as pool:
        for tau, aw, ia, cap in sorted(pool.map(measure, grid)):
            print(f"tau {tau} 주의력 {aw} 주시태만 {int(ia * 100)}%: 기본 용량 {cap:.0f}대/시(차로당 {cap / 4:.0f})", flush=True)
