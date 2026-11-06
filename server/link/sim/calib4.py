"""보정 4: tau 0.4·주의력 0.5·주시태만 20 % 에서 사고 때 남는 용량 비율(구경 감속별)."""
import multiprocessing as mp
import os

import tago_sim as S


def measure(args):
    blocked, gawk = args
    import libsumo as ts
    import traci.constants as tc
    work = S.RES / "_work" / f"g{os.getpid()}"
    net = S.build_net(work)
    c = {"seed": 7, "demand": 9000, "blocked": blocked, "dur": 3000, "rain": 0, "inatt": 0.2, "comply": 0.3, "truck": 0.15, "tau": S.PARAMS["tau"], "sigma": 0.5}
    rou = S.build_routes(work, c, 2400, "g")
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", str(S.STEP), "--no-step-log", "true", "--no-warnings", "true", "--end", "2400", "--time-to-teleport", "-1", "--collision.action", "warn"])   # 추돌한 차를 순간이동시키지 않는다
    mid, down = S.INC_POS - 3000, S.INC_POS + 10
    last, n_mid, n_down = {}, 0, 0
    while ts.simulation.getTime() < 2400:
        ts.simulationStep(); t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            if not v.startswith("crash"):
                ts.vehicle.subscribe(v, [tc.VAR_DISTANCE])
        if blocked and abs(t - 600) < S.STEP / 2:
            for k in range(blocked, S.LANES):
                ts.lane.setMaxSpeed(f"inc_{k}", gawk / 3.6)
        if blocked and abs(t - 900) < S.STEP / 2:
            ok = all(f"crash{k}" in ts.vehicle.getIDList() and ts.vehicle.getSpeed(f"crash{k}") < 0.1 for k in range(blocked))
            print(f"  {blocked}차로 구경 {gawk}: 사고 차 {'서 있음' if ok else '없음!'}", flush=True)
        for v, d in ts.vehicle.getAllSubscriptionResults().items():
            x = d[tc.VAR_DISTANCE]; px = last.get(v)
            if px is not None and t > 1200:
                n_mid += px < mid <= x
                n_down += px < down <= x
            last[v] = x
    ts.close()
    return blocked, gawk, n_mid / 1200 * 3600, n_down / 1200 * 3600


if __name__ == "__main__":
    grid = [(0, None), (1, 13), (2, 13), (1, 14), (2, 14)]
    with mp.get_context("spawn").Pool(9) as pool:
        rows = pool.map(measure, grid)
    base = rows[0][2]
    print(f"기본 {base:.0f}대/시", flush=True)
    for b, g, m, d in rows[1:]:
        print(f"{b}차로 막힘 구경 {g}km/h: {d:.0f}대/시 = {d / base:.2f}", flush=True)
