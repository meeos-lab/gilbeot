"""M1 추종 모형 보정(사전 고정 docs/sim-preregistration.md 'M1'): IDM 의 희망 차두 시간 T 를 Krauss(v2, tau 0.5)와 같은 기본 용량이 되게 고른다.

  TAGO_STEP=0.25 TAGO_TINC=900 TAGO_GAWK="1:13,2:13" python -X utf8 calib_cf.py   → results/calib_cf.json
측정(calib3·calib4 와 같은 방식, 간격은 TAGO_STEP): 수요 9,000대/시, 주시태만 20 %(주의력 0.5), 화물 15 %.
  기본 용량 = 사고 없음, 사고 지점 3 km 상류를 900~1,800 s 에 지난 차 수(대/시).
  남는 용량 = 600 s 에 1·2차로 차단(구경 13 km/h, v2 와 같음), 사고 지점 바로 아래를 1,200~2,400 s 에 지난 차 수 ÷ 기본 용량.
후보 T: 0.6·0.8·1.0·1.2·1.4 s. 규칙: 기본 용량이 Krauss(tau 0.5) 측정값에 가장 가까운 T 를 고른다(결과를 보기 전에 정한 규칙). 구경 감속은 바꾸지 않고 남는 용량을 보고만 한다.
"""
import json
import multiprocessing as mp
import os
from pathlib import Path


def measure(args):
    cf, tau, blocked = args
    os.environ["TAGO_CF"] = cf
    import tago_sim as S
    S.CF_MODEL = cf
    import libsumo as ts
    import traci.constants as tc
    work = S.RES / "_work" / f"cf{os.getpid()}"
    net = S.build_net(work)
    t_end = 2400 if blocked else 1800
    c = {"seed": 7, "demand": 9000, "blocked": blocked, "dur": 3000, "rain": 0, "inatt": 0.2, "comply": 0.3, "truck": 0.15, "tau": tau, "sigma": 0.5}
    rou = S.build_routes(work, c, t_end, f"cf{cf}{tau}{blocked}")
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", str(S.STEP), "--no-step-log", "true", "--no-warnings", "true",
              "--end", str(t_end), "--time-to-teleport", "-1", "--collision.action", "warn"])
    mid, down = S.INC_POS - 3000, S.INC_POS + 10
    gawk = dict(S.PARAMS["gawk"]).get(blocked)
    last, n_mid, n_down, coll = {}, 0, 0, 0
    while ts.simulation.getTime() < t_end:
        ts.simulationStep(); t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            if not v.startswith("crash"):
                ts.vehicle.subscribe(v, [tc.VAR_DISTANCE])
        if blocked and abs(t - S.T_INC) < S.STEP / 2 and gawk:
            for k in range(blocked, S.LANES):
                ts.lane.setMaxSpeed(f"inc_{k}", gawk / 3.6)
        coll += ts.simulation.getCollidingVehiclesNumber()
        for v, d in ts.vehicle.getAllSubscriptionResults().items():
            x = d[tc.VAR_DISTANCE]; px = last.get(v)
            if px is not None:
                if not blocked and 900 < t:
                    n_mid += px < mid <= x
                if blocked and 1200 < t:
                    n_down += px < down <= x
            last[v] = x
    ts.close()
    flow = (n_mid / 900 if not blocked else n_down / 1200) * 3600
    return {"cf": cf, "tau": tau, "blocked": blocked, "flow": round(flow), "coll_steps": coll}


if __name__ == "__main__":
    ts = [float(x) for x in os.environ.get("TAGO_T_GRID", "0.6,0.8,1.0,1.2,1.4").split(",")]   # M1b 보정 격자 확장용
    grid = [("", 0.5, b) for b in (0, 1, 2)] + [("IDM", T, b) for T in ts for b in (0, 1, 2)]
    with mp.get_context("spawn").Pool(int(os.environ.get("TAGO_PROCS", 0)) or len(grid)) as pool:
        rows = pool.map(measure, grid)
    base = {(r["cf"], r["tau"]): r["flow"] for r in rows if r["blocked"] == 0}
    out = {"rows": rows, "base_per_lane": {f"{k[0] or 'Krauss'} tau {k[1]}": round(v / 4) for k, v in base.items()},
           "residual": {f"{r['cf'] or 'Krauss'} tau {r['tau']} blocked {r['blocked']}": round(r["flow"] / base[(r["cf"], r["tau"])], 2) for r in rows if r["blocked"]}}
    kr = base[("", 0.5)]
    pick = min((k for k in base if k[0] == "IDM"), key=lambda k: abs(base[k] - kr))
    out["krauss_base"], out["pick_T"], out["pick_base"] = kr, pick[1], base[pick]
    name = "calib_cf" + (f"_b{os.environ['TAGO_DECEL']}" if os.environ.get("TAGO_DECEL") else "") + ("_grid2" if os.environ.get("TAGO_T_GRID") else "") + ".json"   # M1b: calib_cf_b2.0.json
    Path(__file__).with_name("results").joinpath(name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
