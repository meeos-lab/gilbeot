import tago_sim as S
import libsumo as ts
import traci.constants as tc
work = S.RES / "_work" / "dbg"; net = S.build_net(work)
c = {"seed": 7, "demand": 9000, "blocked": 2, "dur": 3000, "rain": 0, "inatt": 0.2, "comply": 0.3, "truck": 0.15, "tau": S.PARAMS["tau"], "sigma": 0.5}
rou = S.build_routes(work, c, 1500, "dbg")
ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", "0.5", "--no-step-log", "true", "--no-warnings", "true", "--end", "1500", "--time-to-teleport", "-1", "--collision.action", "warn"])
passed = {0: 0, 1: 0, 2: 0, 3: 0}; last = {}
while ts.simulation.getTime() < 1500:
    ts.simulationStep(); t = ts.simulation.getTime()
    for v in ts.simulation.getDepartedIDList():
        if not v.startswith("crash"): ts.vehicle.subscribe(v, [tc.VAR_DISTANCE, tc.VAR_LANE_INDEX, tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION])
    if abs(t - 600) < 0.25:
        for k in range(2, 4): ts.lane.setMaxSpeed(f"inc_{k}", 20 / 3.6)
    sub = ts.vehicle.getAllSubscriptionResults()
    for v, d in sub.items():
        x = d[tc.VAR_DISTANCE]; px = last.get(v)
        if px is not None and t > 900 and px < S.INC_POS + 10 <= x:
            passed[d[tc.VAR_LANE_INDEX]] += 1
        last[v] = x
    if abs(t - 1000) < 0.25:
        for k in range(2):
            cid = f"crash{k}"
            print(cid, ts.vehicle.getRoadID(cid), ts.vehicle.getLaneIndex(cid), round(ts.vehicle.getLanePosition(cid), 1), ts.vehicle.getSpeed(cid), "dist", ts.vehicle.getDistance(cid))
        inc = [(v, d[tc.VAR_LANE_INDEX], round(d[tc.VAR_LANEPOSITION]), round(d[tc.VAR_DISTANCE])) for v, d in sub.items() if d[tc.VAR_ROAD_ID] == "inc"]
        print("inc 위 차", len(inc), inc[:8])
        print("충돌 누적", ts.simulation.getCollidingVehiclesNumber())
print("사고 지점 통과(900~1500s) 차로별", passed, "→ 대/시", {k: round(v / 600 * 3600) for k, v in passed.items()})
ts.close()
