"""정체 꼬리 경고 효과 시뮬레이션 — 경부고속도로 하행 기흥~수원신갈(사고 다발 구간), 아침 7~8시 실측 교통량.

사용: python -X utf8 queue_sim.py [회수=5] [--quick]
- 도구: SUMO 1.28(eclipse-sumo, libsumo). 차는 충돌하지 않는 모델이라 사고 대신 '추돌 위험 상충'(앞차와의 간격 ÷ 속도 차로 구한
  충돌까지 남은 시간 TTC < 1.5 s, 차 쌍마다 한 번)과 급감속(>= 4.5 m/s²)을 센다 — 미국 FHWA SSAM 과 같은 대리 지표.
- 실측 입력: 한국도로공사_상시 교통량조사결과(출퇴근 시간대별, 공공데이터 15145224) 기흥~수원신갈 기점 방향 07~08시 6,691대/시,
  OSM 차로 수 4·제한속도 110 km/h. 이 구간 하행 사고 11건(2023~2025, 도로공사 사고 상세) 중 5건이 07시대, 8건이 주시태만.
- 가정(바꿔 가며 민감도를 본다): 화물 15 %, 주시태만 운전자 15 %(반응 간격 2 s, 보통 0.5 s), 경고 따름 70 %, 경고 받은 차는 시속 80 km 로
  줄이고 막힌 차로에서 미리 비킨다, 경고는 주시태만을 푼다.
- 사고: 10분 뒤 5.3 km 지점에서 바깥 두 차로가 20분 막힌다.
- 경고 방식: 없음 / 공식(사고 뒤 6분 31초, 모든 차, 앞 6 km) / Tago(보급률 p, 앱 규칙 그대로 확정 — 사고 차 둘 다 보급이면 1 s,
  하나면 무응답 30 s 뒤, 아니면 보급 차 2대가 사고 지점 300 m 안에서 30 s 멈췄을 때. 앞 6 km 의 보급 차에만).
"""
import math
import os
import random
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import sumo
os.environ.setdefault("SUMO_HOME", sumo.SUMO_HOME)
import libsumo as ts  # noqa: E402
import traci.constants as tc  # noqa: E402

HERE = Path(__file__).parent
WORK = HERE / "_work"
LANES, VMAX = 4, 110 / 3.6
LEN, INC_POS = 16000.0, 13300.0           # 상류 13 km — 정체 꼬리가 도로 시작에 닿지 않게(8 km 판은 잘렸다)
DEMAND = 6691                          # 대/시, 실측
T_INC, T_CLEAR, T_END = 600.0, 1800.0, 2700.0
STEP = 0.5
OFFICIAL_DELAY = 391.0                 # 6분 31초(인지 뒤 안내까지 평균, 도로공사). 인지까지 6분 28초는 빼서 공식 쪽에 유리하게
OFFICIAL = {"official": 391.0, "official_full": 779.0, "official_ai": 80.0}   # 안내만 / 인지 6분28초+안내 6분31초 / 도로공사 AI CCTV 목표 80초
WARN_RANGE = 6000.0                    # 앞 6 km(Tago INCIDENT 말하는 거리)
WARN_KMH, COMPLY = 80.0, 0.70
INATT, TRUCK = 0.15, 0.15
TTC_CONFLICT = 1.5


def build_net():
    WORK.mkdir(exist_ok=True)
    (WORK / "n.nod.xml").write_text(f'<nodes><node id="a" x="0" y="0"/><node id="b" x="{INC_POS - 300}" y="0"/>'
                                    f'<node id="c" x="{INC_POS + 300}" y="0"/><node id="d" x="{LEN}" y="0"/></nodes>', encoding="utf-8")
    (WORK / "n.edg.xml").write_text(
        "<edges>" + "".join(f'<edge id="{i}" from="{f}" to="{t}" numLanes="{LANES}" speed="{VMAX:.2f}"/>'
                            for i, f, t in (("up", "a", "b"), ("inc", "b", "c"), ("down", "c", "d"))) + "</edges>", encoding="utf-8")
    bin_ = Path(sumo.SUMO_HOME) / "bin" / "netconvert"
    subprocess.run([str(bin_), "-n", str(WORK / "n.nod.xml"), "-e", str(WORK / "n.edg.xml"), "-o", str(WORK / "n.net.xml"),
                    "--no-turnarounds", "true"], check=True, capture_output=True)


def build_routes(seed):
    rng = random.Random(seed)
    types = (f'<vType id="car" length="4.5" accel="2.6" decel="4.5" emergencyDecel="9" sigma="0.5" tau="1.0" maxSpeed="{VMAX + 3:.1f}" speedFactor="normc(1,0.08,0.8,1.2)" actionStepLength="{STEP}" lcAssertive="1.2"/>'
             f'<vType id="truck" vClass="truck" length="12" accel="1.3" decel="4.0" emergencyDecel="7" sigma="0.5" tau="1.2" maxSpeed="25" actionStepLength="{STEP}"/>')
    vehs, t, i = [], 0.0, 0
    while t < T_END:
        t += rng.expovariate(DEMAND / 3600.0)
        typ = "truck" if rng.random() < TRUCK else "car"
        vehs.append(f'<vehicle id="v{i}" type="{typ}" route="r" depart="{t:.2f}" departLane="best" departSpeed="max"/>')
        i += 1
    (WORK / f"r{seed}.rou.xml").write_text(f'<routes>{types}<route id="r" edges="up inc down"/>{"".join(vehs)}</routes>', encoding="utf-8")


def run(scenario, p, seed, comply=COMPLY, inatt=INATT, record=None, levers=()):
    """scenario: none | official* | tago | official*+tago. p: 보급률. levers(Tago 설계 손잡이, 기본 끔):
    tail = 정체 꼬리 앞 3 km 에도 경고, graded = 꼬리까지 거리별 권장 속도 90/70/50, relay = 확정 30 s 뒤 공식 채널로 모든 차에,
    fast = 앱 차 1대 정차로 확정. 반환: 지표 dict"""
    build_routes(seed)
    rng = random.Random(f"{scenario}|{p}|{seed}")
    ts.start(["sumo", "-n", str(WORK / "n.net.xml"), "-r", str(WORK / f"r{seed}.rou.xml"), "--step-length", str(STEP),
              "--seed", str(seed), "--no-step-log", "true", "--no-warnings", "true", "--collision.action", "warn", "--end", str(T_END)])
    ts.route.add("rinc", ["inc", "down"])
    pair_ttc = {}                                       # (뒤차, 앞차) → 사고 뒤 가장 짧은 TTC — 상충은 쌍마다 한 번
    pair_dv = {}                                        # 그때의 가장 큰 속도 차(고속 접근 상충 = 시속 30 km 이상)
    pair_at = {}
    tail, cw, cw_set = INC_POS, set(), {}               # 정체 꼬리 위치, 경고를 따르는 차, 마지막으로 준 권장 속도
    length = {}
    equipped, inattentive, warned, comply_set = {}, set(), set(), {}
    crash_cars = ["crash0", "crash1"]
    stop_since, tago_at, hard_brakes, braking, crashes = {}, None, 0, set(), set()
    depart, arrive, passed = {}, {}, 0
    base_sc = scenario.replace("+tago", "")
    official_at = T_INC + OFFICIAL[base_sc] if base_sc in OFFICIAL else None
    use_tago = scenario == "tago" or scenario.endswith("+tago")
    t = 0.0
    while t < T_END:
        ts.simulationStep()
        t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            if v.startswith("crash"):
                continue
            depart[v] = t
            ts.vehicle.subscribe(v, [tc.VAR_SPEED, tc.VAR_ACCELERATION, tc.VAR_DISTANCE, tc.VAR_LANE_INDEX])
            length[v] = 12.0 if ts.vehicle.getTypeID(v) == "truck" else 4.5
            equipped[v] = rng.random() < p
            comply_set[v] = rng.random() < comply
            if ts.vehicle.getTypeID(v) == "car" and rng.random() < inatt:
                inattentive.add(v)
                ts.vehicle.setActionStepLength(v, 2.0)
        for v in ts.simulation.getArrivedIDList():
            if v in depart:
                arrive[v] = t
        # 사고: 바깥 두 차로에 멈춘 차 두 대
        if abs(t - T_INC) < STEP / 2:
            for k, lane in enumerate((0, 1)):
                cid = crash_cars[k]
                ts.vehicle.add(cid, "rinc", typeID="car", depart="now", departLane=str(lane), departPos="290", departSpeed="0")
                ts.vehicle.setStop(cid, "inc", pos=300.0, laneIndex=lane, duration=T_CLEAR - T_INC)
            if use_tago:                               # 사고 차가 보급 차인가
                n_eq = sum(rng.random() < p for _ in crash_cars)
                if n_eq == 2:
                    tago_at = T_INC + 1.0
                elif n_eq == 1:
                    tago_at = T_INC + 31.0             # 무응답 30 s → 강한 확정(근거 6점 이상)
        sub = ts.vehicle.getAllSubscriptionResults()     # 한 번에 받는다(차마다 묻지 않는다)
        ids = [v for v in sub if not v.startswith("crash")]
        if record is not None:                            # 그림용 기록: 시공간 속도 격자(10 s × 100 m)와 1초마다 차 위치
            for v in ids:
                x = sub[v][tc.VAR_DISTANCE]
                if 0 <= x < LEN:
                    key = (int(t // 10), int(x // 100))
                    a = record.setdefault("grid", {}).setdefault(key, [0.0, 0])
                    a[0] += sub[v][tc.VAR_SPEED]; a[1] += 1
            if abs(t - round(t)) < 1e-6 and T_INC - 60 <= t <= T_CLEAR + 120:
                record.setdefault("frames", []).append((t, [(round(sub[v][tc.VAR_DISTANCE], 1), sub[v][tc.VAR_LANE_INDEX], round(sub[v][tc.VAR_SPEED], 1),
                                                            1 if v in warned else 0, 1 if equipped.get(v) else 0, 1 if length.get(v, 4.5) > 5 else 0)
                                                           for v in ids if INC_POS - 2500 <= sub[v][tc.VAR_DISTANCE] <= INC_POS + 400]))
            record["tago_at"] = tago_at
        # Tago 확정: 보급 차 2대가 사고 지점 300 m 안에서 30 s 넘게 멈춤(급제동+정차 = 3점, 모르는 차 2대)
        if use_tago and tago_at is None and t > T_INC:
            n = 0
            for v in ids:
                if not equipped.get(v):
                    continue
                x = abs(sub[v][tc.VAR_DISTANCE])
                if sub[v][tc.VAR_SPEED] < 1.4 and INC_POS - 300 <= x <= INC_POS:
                    stop_since.setdefault(v, t)
                    if t - stop_since[v] >= 30:
                        n += 1
                else:
                    stop_since.pop(v, None)
            if n >= (1 if "fast" in levers else 2):
                tago_at = t + 1.0
        if t >= T_INC:                                    # 추돌 위험 상충: 같은 차로 바로 앞 차까지 간격 ÷ 속도 차
            lanes = {}
            for v in ids:
                d = sub[v]
                lanes.setdefault(d[tc.VAR_LANE_INDEX], []).append((d[tc.VAR_DISTANCE], d[tc.VAR_SPEED], v))
            if t < T_CLEAR:                               # 사고 차(멈춤)도 앞차로 넣는다
                for k, lane in enumerate((0, 1)):
                    lanes.setdefault(lane, []).append((INC_POS, 0.0, crash_cars[k]))
            for row in lanes.values():
                row.sort()
                for (xf, vf, f), (xl, vl, l) in zip(row, row[1:]):
                    g = xl - xf - length.get(l, 4.5)
                    dv = vf - vl
                    if dv > 0.5 and g >= 0:
                        ttc = g / dv
                        if ttc < TTC_CONFLICT:
                            k = (f, l)
                            pair_ttc[k] = min(pair_ttc.get(k, 9.9), ttc)
                            pair_dv[k] = max(pair_dv.get(k, 0.0), dv)
                            if ttc <= pair_ttc[k]:
                                pair_at[k] = (xf, vf)        # 가장 위험했던 순간의 뒤차 위치·속도(갈래 나누기)
        if levers and T_INC <= t < T_CLEAR:               # 정체 꼬리: 사고 지점 상류에서 시속 30 km 아래인 차들의 앞쪽 끝(2 % 분위로 튀는 값 제외)
            slow = sorted(sub[v][tc.VAR_DISTANCE] for v in ids if sub[v][tc.VAR_SPEED] < 8.3 and 0 < sub[v][tc.VAR_DISTANCE] <= INC_POS)
            tail = slow[int(0.02 * len(slow))] if len(slow) >= 5 else INC_POS
        relay_at = (tago_at + 30.0) if ("relay" in levers and tago_at is not None) else None
        if t >= T_INC:
            for c in ts.simulation.getCollisions():   # 시뮬레이터 안 추돌(반응 늦은 운전자). 쌍마다 한 번
                crashes.add((c.collider, c.victim))
        for v in ids:
            acc = sub[v][tc.VAR_ACCELERATION]
            if acc <= -4.5:
                if v not in braking and t >= T_INC:
                    hard_brakes += 1                      # 급감속(4.5 m/s² 이상)이 시작된 횟수
                braking.add(v)
            else:
                braking.discard(v)
            if v in warned or t < T_INC or t >= T_CLEAR:
                continue
            x = sub[v][tc.VAR_DISTANCE]
            gap = INC_POS - x
            if not (0 < gap <= WARN_RANGE or ("tail" in levers and 0 < tail - x <= 3000 and gap > 0)):
                continue
            got = ((official_at is not None and t >= official_at) or (tago_at is not None and t >= tago_at and equipped.get(v))
                   or (relay_at is not None and t >= relay_at))
            if not got:
                continue
            warned.add(v)
            if v in inattentive:
                ts.vehicle.setActionStepLength(v, STEP)   # 경고가 주의를 되돌린다
            if comply_set.get(v):
                cw.add(v)
                if "graded" not in levers:
                    ts.vehicle.setMaxSpeed(v, min(ts.vehicle.getMaxSpeed(v), WARN_KMH / 3.6))
                lane = sub[v][tc.VAR_LANE_INDEX]
                if lane in (0, 1):
                    ts.vehicle.changeLane(v, 2 + (lane == 1), 30.0)
        if "graded" in levers and t < T_CLEAR:          # 꼬리까지 거리별 권장 속도(앱의 '정체 권장 속도'를 늘린 것)
            for v in cw:
                if v not in sub:
                    continue
                d = tail - sub[v][tc.VAR_DISTANCE]
                kmh = 90 if d > 2000 else 70 if d > 1000 else 50
                if cw_set.get(v) != kmh and sub[v][tc.VAR_DISTANCE] <= INC_POS:
                    cw_set[v] = kmh
                    ts.vehicle.setMaxSpeed(v, kmh / 3.6)
        # 사고 지점을 지난 차는 원래 속도로
        for v in list(warned):
            if v in sub and sub[v][tc.VAR_DISTANCE] > INC_POS + 100:
                ts.vehicle.setMaxSpeed(v, VMAX + 3)
                warned.discard(v); warned.add(v + "#done"); cw.discard(v)
    ts.close()
    conflicts = len(pair_ttc)
    fast_conf = sum(1 for k in pair_ttc if pair_dv.get(k, 0) >= 8.33)
    kinds = {"merge": 0, "queue": 0, "approach": 0, "other": 0}
    for k in pair_ttc:
        x, vf = pair_at.get(k, (0.0, 0.0))
        if INC_POS - 300 <= x <= INC_POS:
            kinds["merge"] += 1                           # 사고 지점 앞 300 m 합류
        elif vf < 8.3:
            kinds["queue"] += 1                           # 정체 안 가다 서다(시속 30 km 아래)
        elif pair_dv.get(k, 0) >= 8.33:
            kinds["approach"] += 1                        # 고속으로 정체 꼬리에 다가감(속도 차 시속 30 km 이상)
        else:
            kinds["other"] += 1
    min_ttc = list(pair_ttc.values())
    tts = [arrive[v] - depart[v] for v in arrive if T_INC - 300 <= depart[v] <= T_CLEAR]
    return {"conflicts": conflicts, "severe": sum(1 for x in min_ttc if x < 0.75), "hard_brakes": hard_brakes,
            "crashes": len([c for c in crashes if not c[1].startswith("crash")]), "fast_conf": fast_conf, "kinds": kinds,
            "travel_s": statistics.mean(tts) if tts else float("nan"), "arrived": len(arrive), "tago_at": None if tago_at is None else round(tago_at - T_INC, 1)}


SCENARIOS = [("none", 0.0), ("official_full", 0.0), ("official", 0.0), ("official_ai", 0.0),
             ("tago", 0.05), ("tago", 0.2), ("tago", 0.5), ("tago", 1.0),
             ("official_full+tago", 0.2), ("official+tago", 0.2), ("official_ai+tago", 0.2)]
NAMES = {"none": "경고 없음", "official_full": "공식 12분59초", "official": "공식 6분31초", "official_ai": "공식 AI 80초"}


def main(n=5, quick=False):
    build_net()
    seeds = list(range(1, n + 1))
    scen = SCENARIOS[:3] if quick else SCENARIOS
    print(f"기흥~수원신갈 하행, {DEMAND}대/시, 4차로, 사고 2차로 {int((T_CLEAR - T_INC) / 60)}분. 회수 {n}")
    print(f"{'경고 방식':<22} {'상충(TTC<1.5s)':>14} {'심각(<0.75s)':>12} {'추돌':>6} {'급감속':>8} {'통행시간(s)':>11} {'경고까지(s)':>11}")
    base = None
    for sc, p in scen:
        rs = []
        for s_ in seeds:
            rs.append(run(sc, p, s_)); print(f'  {sc} {p} seed {s_}: {rs[-1]}', flush=True)
        m = {k: statistics.mean(r[k] for r in rs) for k in ("conflicts", "severe", "hard_brakes", "travel_s", "crashes")}
        sd = statistics.pstdev(r["conflicts"] for r in rs)
        tag = [r["tago_at"] for r in rs if r["tago_at"] is not None]
        name = f"Tago {int(p * 100)}%" if sc == "tago" else (NAMES[sc.replace('+tago', '')] + (f"+Tago {int(p * 100)}%" if sc.endswith("+tago") else ""))
        if base is None:
            base = m
        warn = (f"{int(OFFICIAL[sc.replace('+tago', '')])}" if sc.replace('+tago', '') in OFFICIAL else "-") + (f"/{statistics.mean(tag):.0f}" if tag else "")
        print(f"{name:<22} {m['conflicts']:>9.1f}±{sd:<4.1f} {m['severe']:>12.1f} {m['crashes']:>6.1f} {m['hard_brakes']:>8.0f} {m['travel_s']:>11.0f} {warn:>11}"
              f"   상충 {100 * (m['conflicts'] - base['conflicts']) / max(base['conflicts'], 1e-9):+.0f}%", flush=True)


LEVERS = [("none", 0.0, ()), ("tago", 0.2, ()), ("tago", 0.2, ("tail", "graded")), ("tago", 0.2, ("fast",)), ("tago", 0.2, ("relay",)),
          ("tago", 0.2, ("relay", "tail", "graded", "fast")), ("tago", 0.5, ("relay", "tail", "graded", "fast")), ("tago", 1.0, ("tail", "graded"))]


def levers_main(n=3):
    """Tago 설계 손잡이로 상충 감소를 어디까지 올릴 수 있나(가정은 그대로 두고 앱이 바꿀 수 있는 것만)"""
    build_net()
    print(f"손잡이 실험, 회수 {n}. 상충 = TTC<1.5s 쌍, 고속 = 그중 속도 차 시속 30km 이상", flush=True)
    base = None
    for sc, p, lv in LEVERS:
        rs = [run(sc, p, s_, levers=lv) for s_ in range(1, n + 1)]
        m = {k: statistics.mean(r[k] for r in rs) for k in ("conflicts", "fast_conf", "severe", "travel_s")}
        tag = [r["tago_at"] for r in rs if r["tago_at"] is not None]
        if base is None:
            base = m
        name = "경고 없음" if sc == "none" else f"Tago {int(p * 100)}% " + ("+".join(lv) if lv else "(지금 규칙)")
        print(f"{name:<44} 상충 {m['conflicts']:7.1f} ({100 * (m['conflicts'] / base['conflicts'] - 1):+.0f}%)  고속 {m['fast_conf']:6.1f} "
              f"({100 * (m['fast_conf'] / max(base['fast_conf'], 1e-9) - 1):+.0f}%)  심각 {m['severe']:6.1f}  통행 {m['travel_s']:5.0f}s  확정 {statistics.mean(tag) if tag else float("nan"):5.0f}s", flush=True)


def sensitivity(n=5):
    """가정을 바꿔도 결론이 유지되는지: 경고 따름 50/90 %, 주시태만 5/30 % 에서 경고 없음 대 Tago 20 %"""
    build_net()
    print("민감도(상충 평균, 경고 없음 → Tago 20 %)", flush=True)
    for label, kw in (("따름 50%", {"comply": 0.5}), ("따름 90%", {"comply": 0.9}), ("주시태만 5%", {"inatt": 0.05}), ("주시태만 30%", {"inatt": 0.30})):
        a = [run("none", 0.0, s, **kw)["conflicts"] for s in range(1, n + 1)]
        b = [run("tago", 0.2, s, **kw)["conflicts"] for s in range(1, n + 1)]
        ma, mb = statistics.mean(a), statistics.mean(b)
        print(f"  {label:<10} {ma:7.1f} → {mb:7.1f}  ({100 * (mb - ma) / ma:+.0f}%)", flush=True)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--levers" in sys.argv:
        levers_main(int(a[0]) if a else 3)
    elif "--sens" in sys.argv:
        sensitivity(int(a[0]) if a else 5)
    else:
        main(int(a[0]) if a else 5, "--quick" in sys.argv)
