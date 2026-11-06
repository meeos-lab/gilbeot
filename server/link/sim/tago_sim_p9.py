"""Tago 정체 꼬리 경고 효과 — 본 실험 엔진(사전 고정 계획 docs/sim-preregistration.md).

사용:
  python -X utf8 tago_sim.py calib            # 보정: 사고 없는 흐름·차로 차단 처리 용량
  python -X utf8 tago_sim.py main [씨앗=24]    # 본 실험: 조건 표본 × 방식, 짝 비교 → results/main.jsonl
  python -X utf8 tago_sim.py lhs [표본=64]     # 전역 민감도(라틴 하이퍼큐브) → results/lhs.jsonl
  python -X utf8 tago_sim.py false [씨앗=24]   # 오탐 비용 → results/false.jsonl
  python -X utf8 tago_sim.py report            # 표·검정 → results/report.json
한 실행 = (조건, 방식). 조건은 씨앗에서 뽑고(같은 씨앗 = 같은 차 흐름·같은 사고), 방식만 바꿔 짝 비교한다.

모형(SUMO 1.28, libsumo, 0.5 s): 편도 4차로 직선, 상류 UP m, 제한 110 km/h. 사고는 사고 지점 바깥 차로 1~2개를 막는다.
Tago 모형은 앱 규칙을 따른다(server/link/link_server.py = LinkHub.kt):
  - 사고 의심 확정: 사고 차 둘 다 앱 차면 1 s, 하나면 무응답 30 s 뒤, 아니면 앱 차 2대가 사고 지점 300 m 안에서 30 s 정차
  - 정체 확정: 앱 차 2대가 시속 30 km 아래로 20 s(SLOW_HOLD) → 정체 꼬리 = 느린 앱 차의 가장 상류
  - 안내: 사고 의심은 앞 6 km(INCIDENT 말하는 거리), 정체 꼬리는 앞 3 km(권장 속도) — 앱 차에게만.
    권장 속도는 꼬리까지 2 km 넘게 90, 1~2 km 70, 1 km 안 50(앱 '정체 권장 속도'의 단계형)
  - relay: 확정 30 s 뒤 공식 채널(도로공사·내비)로 넘겨 모든 차가 같은 안내를 받는다(협약 가정)
공식 안내: 사고 뒤 지연(기준선 779 s) 이후 앞 6 km 의 모든 차, 일률 시속 80 km.
경고를 받은 차: 주시태만이 풀리고, 따름 비율만큼 권장 속도를 지키고 막힌 차로에서 미리 비킨다.
지표: 같은 차로 앞차까지 TTC < 1.5 s 인 차 쌍(사고 뒤), 그중 속도 차 시속 30 km 이상 = 고속 접근 상충(주 지표).
"""
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
STEP = float(os.environ.get("TAGO_STEP", "0.5"))   # 수치 점검: 0.25 면 차간 시간 0.4 s 가 간격보다 길다(SUMO: tau < step 이면 추돌 가능)
LANES, VMAX = int(os.environ.get("TAGO_LANES", "4")), 110 / 3.6   # R7 도로 형태: TAGO_LANES=3(수요는 TAGO_DEMAND_SCALE 로 줄인다)
DEMAND_SCALE = float(os.environ.get("TAGO_DEMAND_SCALE", "1"))
UP, DOWN = float(os.environ.get("TAGO_UP", "20000")), 2000.0   # 사고 지점 상류 20 km(40분 차단에도 꼬리가 들어오게), 하류 2 km. C3(120분 차단)는 TAGO_UP=30000
INC_POS, LEN = UP, UP + DOWN
T_INC = float(os.environ.get("TAGO_TINC", "600"))   # 예열(기본 10분 — 상류 20 km 를 다 못 채움, 점검은 900)
TTC_CONFLICT, TTC_STRICT, FAST_DV = 1.5, 1.0, 30 / 3.6   # 1.0 s: 문헌상 유일한 실증 최적 문턱(Jiang 2021) — 보조 지표
WARN_INC, WARN_TAIL = 6000.0, 2000.0   # 꼬리 경고 2 km(3 km 넘으면 효과 없음, Reinolsmann 2018)
SLOW_MS, SLOW_HOLD = 8.3, 20.0
OFFICIAL_KMH = 80.0
NO_ATTN = os.environ.get("TAGO_NOATTN") == "1"   # 제거 실험: 경고가 주시태만을 풀지 않는다
ATTN_P = float(os.environ.get("TAGO_ATTN_P", "1.0"))   # 경고를 받은 주시태만 운전자가 주의를 되찾을 확률(v2 기본 0.65 는 가정값 — Bakowski 2015 의 34.7 % 는 다시 화면을 본 비율이지 회복 확률이 아니다. 0~1 민감도는 robust attn)
REC_WIN = tuple(int(x) for x in os.environ.get("TAGO_REC_WIN", "-1500,300,480,1").split(","))   # 그림 기록 창: 사고 지점 기준 m 범위, 사고 뒤 s, 간격 s
PAIR_TTC = float(os.environ.get("TAGO_PAIR_TTC", "0"))   # >0 이면 이 TTC 미만 상충 쌍을 결과에 남긴다(문턱 민감도용, 지표는 그대로)
PAIR_T = (0.75, 1.0, 1.5, 2.0, 3.0)
COLL_DIAG = os.environ.get("TAGO_COLL_DIAG") == "1"          # 충돌 판정 점검: 쌍마다 첫 판정의 종류·차로·위치·두 차 속도를 기록
MINGAP_F = os.environ.get("TAGO_MINGAP_F")                    # SUMO --collision.mingap-factor(기본 = 차종 값, 0 = 실제로 겹칠 때만)                       # 쌍마다 각 TTC 문턱 안에서의 최대 속도 차를 따로 잡는다(지표 fast 는 1.5 s 칸과 같다)
REC_ID = os.environ.get("TAGO_REC_ID") == "1"   # 그림 기록에 차 번호를 붙인다(3D 재생에서 프레임 사이 보간용)
CF_MODEL = os.environ.get("TAGO_CF", "")        # M1 추종 모형 점검: "IDM"(SUMO 운전자 상태 장치의 지각 오차는 Krauss·IDM 에 적용됨). 비우면 Krauss(기존과 같음)
CAR_DECEL = os.environ.get("TAGO_DECEL", "4.5")  # M1b: 승용차 감속(m/s², 문자열 그대로 vType 에). 기본 4.5 = 기존과 같음
SEV = os.environ.get("TAGO_SEV", "")            # C3 운영 보정 확인: "cal" 이면 막힌 차로·처리 시간을 V2 보정 가중(results/validate_cal.json, 정체 사고 161건)에서 뽑는다
AGG = os.environ.get("TAGO_AGG") == "1"         # P1·P3·P5·P7(사전 등록 'P1~P8'): 속도·차로·급제동·통행 시간 집계를 레코드 "agg" 에 남긴다(읽기만, 지표 불변)
SLACK_KMH = 10.0                                # P6(c) 부분 준수: 준수 차가 권고보다 빠르게 달리는 여유 속도(km/h), mode "slack" 에서만
def _prov():
    import platform
    try:
        from importlib.metadata import version
        sv = version("eclipse-sumo")
    except Exception:
        sv = None
    return {"py": platform.python_version(), "sumo": sv, "os": platform.system(), "arch": platform.machine()}


PROV = _prov()   # E8: 결과 줄에 실행 환경(기계 간 비교용)
SEV_CAL = [((1, 20), 0.05), ((1, 40), 0.003), ((1, 60), 0.286), ((1, 90), 0.026), ((1, 120), 0.33),
           ((2, 20), 0.054), ((2, 40), 0.008), ((2, 60), 0.023), ((2, 90), 0.019), ((2, 120), 0.201)]   # (막힌 차로, 분) → 가중(validate_cal.py 2026-11-04)

# 조건 분포(문헌·실측으로 바꿀 자리 — PARAMS 를 고치면 된다). 출처는 docs 보고서에
PARAMS = {   # 출처는 docs/sim-preregistration.md '바꾼 것'과 보고서
    "demand": [(6691, 0.5), (6837, 0.25), (6128, 0.25)],   # 기흥~수원신갈 기점 방향 07·08·09시 실측(대/시, 도로공사 상시 교통량)과 뽑을 확률
    "demand_cv": 0.06,                     # 날마다의 변동(변동계수) — 날짜별 자료가 없어 가정
    "blocked": [(1, 0.5), (2, 0.5)],       # 막힌 차로 수 — 국내 분포 자료 없음, 반반 가정
    "dur_ln": (3.39, 0.82, 10, 90),        # 처리 시간(분) 로그정규 μ, σ, 자르기(오리건 2022, 국내 평균 38분)
    "rain_p": 0.15,                        # 비 올 확률(가정), 강도 약·중·강 같은 확률
    "rain": [(0.89, 0.10), (0.84, 0.17), (0.81, 0.25)],   # (원하는 속도 배수, 차두 시간 +s) — 속도 −11/−16/−19 %, 용량 −8.5/−13.8/−19.1 %(KHCM 표 2-7)
    "inatt": (0.06, 0.20, 0.52),           # 주시태만 비율 삼각(최소, 최빈, 최대)
    "comply": (0.15, 0.22, 0.85),          # 경고 따름 비율 삼각 — 최빈 22 %: 현장 15~22 %(Elicit 보고서 2026-11-02)
    "truck": 0.15, "tau": 0.4, "sigma": 0.5, "inatt_aware": 0.5, "inatt_rt": 2.0,   # tau 0.4·주의력 0.5: 주시태만 20~40 % 가 섞여도 기본 용량 약 8,160대/시(KHCM 8,200, calib3.py). 주시태만 = SUMO 운전자 상태 장치
    "gawk": [(1, 35.0), (2, 20.0)],        # 막힌 차로 수 → 열린 차로 구경 속도(km/h): 남는 용량 1차로 0.59·2차로 0.26(HCM 4차로 0.58·0.25, calib4.py)
}
if os.environ.get("TAGO_TAU"):            # v2 보정: 간격 0.25 s 에서 기본 용량을 KHCM 에 맞춘 차간 시간
    PARAMS["tau"] = float(os.environ["TAGO_TAU"])
if os.environ.get("TAGO_COMPLY"):        # 강건성: 따름 비율 삼각 "최소,최빈,최대"(현장 15~22 %)
    PARAMS["comply"] = tuple(float(x) for x in os.environ["TAGO_COMPLY"].split(","))
if os.environ.get("TAGO_GAWK"):          # 실측 보정 민감도: 예 "1:15,2:15" (calib4.py: 남는 용량 0.38·0.24, 문헌 실측 0.37·0.23)
    PARAMS["gawk"] = [(int(k), float(v)) for k, v in (x.split(":") for x in os.environ["TAGO_GAWK"].split(","))]


def cond_for(seed):
    """씨앗 → 조건(같은 씨앗이면 어느 방식에서나 같다)"""
    r = random.Random(f"cond|{seed}")
    pick = lambda opts: r.choices([v for v, _ in opts], [w for _, w in opts])[0]
    d = pick(PARAMS["demand"]) * max(0.7, r.gauss(1.0, PARAMS["demand_cv"])) * DEMAND_SCALE   # 배율은 난수열 뒤에 곱한다(다른 추첨은 그대로)
    mu, sg, lo, hi = PARAMS["dur_ln"]
    dur = min(hi, max(lo, r.lognormvariate(mu, sg)))
    rain = r.randrange(3) + 1 if r.random() < PARAMS["rain_p"] else 0
    tri = lambda a: r.triangular(a[0], a[2], a[1])
    c = {"seed": seed, "demand": round(d), "blocked": pick(PARAMS["blocked"]), "dur": round(dur * 60), "rain": rain,
         "inatt": round(tri(PARAMS["inatt"]), 3), "comply": round(tri(PARAMS["comply"]), 3),
         "truck": PARAMS["truck"], "tau": PARAMS["tau"], "sigma": PARAMS["sigma"]}
    if SEV == "cal":                          # C3: 사고 규모만 보정 분포에서(다른 조건은 v2 씨앗과 같다 — 난수열을 따로 쓴다)
        r2 = random.Random(f"sev|{seed}")
        b, m = r2.choices([k for k, _ in SEV_CAL], [w for _, w in SEV_CAL])[0]
        c["blocked"], c["dur"], c["sev"] = b, m * 60, "cal"
    return c


def sumo_home():
    import sumo
    os.environ.setdefault("SUMO_HOME", sumo.SUMO_HOME)
    return Path(sumo.SUMO_HOME)


def build_net(work):
    work.mkdir(parents=True, exist_ok=True)
    geo = f"L{LANES}_U{UP:g}_D{DOWN:g}"                  # E8: 망 캐시를 도로 형태로 구분(p<pid> 가 재사용돼도 다른 TAGO_LANES/UP 의 망을 읽지 않는다)
    net = work / f"n_{geo}.net.xml"
    if net.exists():
        return net
    nod, edg = work / f"n_{geo}.nod.xml", work / f"n_{geo}.edg.xml"
    nod.write_text(f'<nodes><node id="a" x="0" y="0"/><node id="b" x="{INC_POS - 300}" y="0"/>'
                                    f'<node id="c" x="{INC_POS + 300}" y="0"/><node id="d" x="{LEN}" y="0"/></nodes>', encoding="utf-8")
    edg.write_text("<edges>" + "".join(f'<edge id="{i}" from="{f}" to="{t}" numLanes="{LANES}" speed="{VMAX:.2f}"/>'
                                    for i, f, t in (("up", "a", "b"), ("inc", "b", "c"), ("down", "c", "d"))) + "</edges>", encoding="utf-8")
    subprocess.run([str(sumo_home() / "bin" / "netconvert"), "-n", str(nod), "-e", str(edg), "-o", str(net),
                    "--no-turnarounds", "true"], check=True, capture_output=True)
    return net


def build_routes(work, c, t_end, tag, pre=0.0):
    """pre > 0(sham 만): 0~pre s 에 따로 뽑은 예열 차 w* 를 먼저 넣고, 본 흐름(같은 v* 차·같은 간격)과 사고는 pre 만큼 뒤로 민다"""
    r = random.Random(f"flow|{c['seed']}")
    t_inc = T_INC + pre
    sf, dtau = PARAMS["rain"][c["rain"] - 1] if c["rain"] else (1.0, 0.0)
    tau = c["tau"] + dtau
    cfm = f' carFollowModel="{CF_MODEL}"' if CF_MODEL else ""   # M1: 추종 모형 교체(기본 Krauss). IDM 이면 tau 가 희망 차두 시간 T
    dec = CAR_DECEL                                             # M1b: IDM 의 편안한 감속 b(기본 4.5 = Krauss 감속과 같음, 통상 IDM 은 2)
    lca = c.get("lc_assert", "1.2")                             # P6(b): 차로 변경 공격성(ov lc_assert). 기본 "1.2" = 기존과 같은 문자열
    lct = f' lcAssertive="{lca}"' if "lc_assert" in c else ""   # 화물차는 기본값(SUMO 1.0)이던 것을 P6(b) 에서만 승용차와 같게 바꾼다
    types = (f'<vType id="car" length="4.5" accel="2.6" decel="{dec}" emergencyDecel="9" sigma="{c["sigma"]}" tau="{tau}" maxSpeed="{VMAX + 3:.1f}" '
             f'speedFactor="normc({sf:.2f},0.08,0.6,1.2)" actionStepLength="{STEP}" lcAssertive="{lca}"{cfm}/>'
             f'<vType id="car_i" length="4.5" accel="2.6" decel="{dec}" emergencyDecel="9" sigma="{c["sigma"]}" tau="{tau}" maxSpeed="{VMAX + 3:.1f}" '
             f'speedFactor="normc({sf:.2f},0.08,0.6,1.2)" actionStepLength="{STEP}" lcAssertive="{lca}"{cfm}>'
             f'<param key="has.driverstate.device" value="true"/><param key="device.driverstate.initialAwareness" value="{PARAMS["inatt_aware"]}"/>'
             f'<param key="device.driverstate.minAwareness" value="0.1"/><param key="device.driverstate.maximalReactionTime" value="{PARAMS["inatt_rt"]}"/></vType>'
             f'<vType id="truck" vClass="truck" length="12" accel="1.3" decel="4.0" emergencyDecel="7" sigma="{c["sigma"]}" tau="{tau + 0.2}" maxSpeed="25" '
             f'speedFactor="normc({sf:.2f},0.05,0.6,1.1)" actionStepLength="{STEP}"{lct}{cfm}/>')
    vehs, t, i = [], 0.0, 0
    if pre > 0:                                           # sham 예열 차(본 흐름의 난수열은 건드리지 않는다)
        rp, tp, j = random.Random(f"pre|{c['seed']}"), 0.0, 0
        while True:
            tp += rp.expovariate(c["demand"] / 3600.0)
            if tp >= pre:
                break
            typ = "truck" if rp.random() < c["truck"] else ("car_i" if rp.random() < c["inatt"] else "car")
            vehs.append(f'<vehicle id="w{j}" type="{typ}" route="r" depart="{tp:.2f}" departLane="best" departSpeed="desired"/>')
            j += 1
    crash_done = not (c.get("blocked") and c.get("dur"))
    while t < t_end - pre:
        t += r.expovariate(c["demand"] / 3600.0)
        if not crash_done and t + pre >= t_inc:           # 사고 차: 자리 검사 없이 정해진 시각·자리에 넣는다(빽빽해도 반드시 선다)
            crash_done = True
            for k in range(c["blocked"]):
                vehs.append(f'<vehicle id="crash{k}" type="car" route="rinc" depart="{t_inc:.2f}" departLane="{k}" departPos="290" departSpeed="0" '
                            f'insertionChecks="none"><stop lane="inc_{k}" endPos="300" duration="{c["dur"]}"/></vehicle>')
        typ = "truck" if r.random() < c["truck"] else ("car_i" if r.random() < c["inatt"] else "car")   # 주시태만은 씨앗마다 고정
        vehs.append(f'<vehicle id="v{i}" type="{typ}" route="r" depart="{t + pre:.2f}" departLane="best" departSpeed="desired"/>')
        i += 1
    p = work / f"r_{tag}.rou.xml"
    p.write_text(f'<routes>{types}<route id="r" edges="up inc down"/><route id="rinc" edges="inc down"/>{"".join(vehs)}</routes>', encoding="utf-8")
    return p


SCHEMES = {   # 이름 → (공식 지연 s 또는 None, Tago 보급률, relay[, 꼬리 경고]) — 꼬리 경고 기본 True
    "none": (None, 0.0, False), "official": (779.0, 0.0, False), "official_ai": (80.0, 0.0, False),
    "tago1.5": (None, 0.015, False), "tago12": (None, 0.12, False), "tago50": (None, 0.5, False), "tago100": (None, 1.0, False),
    "tago50-inc": (None, 0.5, False, False),     # H4 비교: 같은 보급률, 사고 지점 경고만(꼬리 경고·단계 속도 없음, 일률 80 km/h)
    "official+tago12": (779.0, 0.12, False), "official+tago50": (779.0, 0.5, False),
    "official+tago1.5+relay": (779.0, 0.015, True), "official+tago12+relay": (779.0, 0.12, True),
    # 후속 실험(권고 방식만 바꿈, 알림 시점·대상은 같다): u80 = 일률 80 km/h, near = 꼬리 1 km 안에서만 70 km/h, none = 속도·차로 권고 없이 주의만
    "official+tago12+relay-u80": (779.0, 0.12, True, True, "u80"), "official+tago12+relay-near": (779.0, 0.12, True, True, "near"),
    "official+tago12+relay-none": (779.0, 0.12, True, True, "none"),
    "official+tago12+relay-u80near": (779.0, 0.12, True, True, "u80near"), "official+tago12+relay-u80nl": (779.0, 0.12, True, True, "u80nl"),
    "official+tago1.5+relay-u80": (779.0, 0.015, True, True, "u80"),
    # 관점 확장 E3~E5(docs/sim-preregistration.md 'E1~E8'): 여섯째 칸 = 동작 방식
    #   sham: 일률 80 문구·앞 6 km 를 사고 5~20분 전 무작위 시각에 한 번(사고 뒤 길벗 경고·연계 없음, 보급 0 — 공식 안내만 기준선대로)
    #   tail: 일률 80, 경고를 처리 종료가 아니라 정체 소멸(정체 길이 < 300 m)까지
    #   right: 일률 80 + 따르는 차를 가장 오른쪽 개방 차로로
    "official+tago12+relay-sham": (779.0, 0.0, False, False, "u80", "sham"),
    "official+tago12+relay-u80tail": (779.0, 0.12, True, True, "u80", "tail"),
    "official+tago12+relay-u80right": (779.0, 0.12, True, True, "u80", "right"),
    # 검토 뒤 보강 P6(docs/sim-preregistration.md 'P1~P8'): 보급 50 % 연계(격자용), slack = 준수 차가 권고 + 10 km/h 로 달리는 부분 준수
    "official+tago50+relay": (779.0, 0.5, True), "official+tago50+relay-u80": (779.0, 0.5, True, True, "u80"),
    "official-slack": (779.0, 0.0, False, True, "graded", "slack"),
    "official+tago12+relay-slack": (779.0, 0.12, True, True, "graded", "slack"), "official+tago12+relay-u80slack": (779.0, 0.12, True, True, "u80", "slack"),
}
SHAM_WARM = 2000.0          # sham 만: 사고 전 최소 예열 s(경고 최대 20분 전 + 앞 6 km 가 찰 시간). 모자라면 사고 앞에 예열 차 흐름(w*)을 덧붙인다
JAM_GONE = 300.0            # E4: 정체 소멸 = 정체 길이 < 300 m
MASS = {"car": 1500.0, "truck": 15000.0}   # E6 KE 가정값(kg) — SUMO 기본값 아님


def official_delay_for(seed, default, draw=None):
    """E1: TAGO_OFFICIAL_DELAY_FILE(JSON, 키 delay_s)이 있으면 씨앗마다 하나를 뽑는다(음수는 0). 없으면 default.
    P4: draw(2, 3, …)가 있으면 난수열 "offdelay|씨앗|draw" 로 씨앗마다 다른 추출을 얻는다(draw 없음 = E1 의 첫 추출)"""
    fn = os.environ.get("TAGO_OFFICIAL_DELAY_FILE")
    if not fn or default is None:
        return default
    dj = json.loads(Path(fn).read_text(encoding="utf-8"))
    ds = dj["delay_s"] if "delay_s" in dj else dj["delays_s"]
    key = f"offdelay|{seed}" if not draw else f"offdelay|{seed}|{draw}"
    return max(0.0, float(random.Random(key).choice(ds)))


def jam_chain_len(xs):
    """처리 뒤 정체 길이: 느린 차(간격 300 m 미만으로 이어진 줄) 중 가장 긴 줄의 앞–뒤 거리. xs 는 내림차순"""
    best, front, back = 0.0, None, None
    for x in xs:
        if front is None or back - x >= 300:
            front = back = x
        else:
            back = x
        best = max(best, front - back)
    return best


def run_one(args):
    """(조건, 방식, 거짓 경보 여부) → 지표. 별도 프로세스에서 libsumo 를 쓴다"""
    c, scheme, false_alarm, *opt = args
    ov = opt[1] if len(opt) > 1 and opt[1] else {}          # 행동 가정 덮어쓰기(J1): attn_p 주의 회복 확률, redist 다시 딴짓까지 s(0 = 영구), delay 권고 반응 지연 s, comply 준수율
    attn_p, redist, delay = ov.get("attn_p", ATTN_P), ov.get("redist", 0.0), ov.get("delay", 0.0)
    relay_delay, loss, tail_err = ov.get("relay_delay", 30.0), ov.get("loss", 0.0), ov.get("tail_err", 0.0)   # 탐지·통신 실패(D1): 연계 지연 s, 연계 메시지 손실률, 꼬리 위치 오차 m(+ = 실제보다 하류)
    if "comply" in ov:
        c = {**c, "comply": ov["comply"]}
    if "lc_assert" in ov:                                     # P6(b): 차로 변경 공격성(vType lcAssertive)
        c = {**c, "lc_assert": ov["lc_assert"]}
    confirm_fix = bool(ov.get("confirm_fix", False))          # P9: 확정 규칙 앞 두 조항(1 s·31 s)을 사고 시각에 평가(기본 꺼짐 = 기존 동작)
    rec = {"grid": {}, "frames": [], "events": [], "ids": {}} if opt and opt[0] else None     # 그림용 기록(켜지 않으면 동작 같음)
    agg = None                                                # P1·P3·P5·P7 집계(TAGO_AGG=1, 읽기만)
    if AGG:
        agg = {"zone": [[0, 0.0, 0.0, 0, 0.0, 0.0] for _ in range(12)],       # 500 m 칸: [n, Σv, Σv², n_경고준수, Σv, Σv²]
               "lanevar": [[0.0, 0, 0.0, 0] for _ in range(12)],              # 500 m 칸: [Σ차로간표준편차, n, Σ인접차로최대차, n]
               "lanepos": [[[0, 0] for _ in range(LANES)] for _ in range(6)],   # 1 km 칸 × 차로: [경고준수 차 수, 전체 차 수]
               "road": [[0, 0.0] for _ in range(int(LEN // 1000) + 1)],       # 전 구간 1 km 칸: [n, Σv](사고 뒤)
               "brake": {"e25_all": 0, "e25_zone": 0, "e35_all": 0, "e35_zone": 0}, "bv_all": set(), "bv_zone": set(), "prev": {}}
    import libsumo as ts
    import traci.constants as tc
    work = RES / "_work" / f"p{os.getpid()}"
    net = build_net(work)
    dur = c["dur"]
    off_delay, p, relay, *rest = SCHEMES[scheme]
    tail_on = rest[0] if rest else True
    adv = rest[1] if len(rest) > 1 else "graded"      # Tago·넘김 메시지의 권고 방식
    mode = rest[2] if len(rest) > 2 else ""           # E3~E5: "sham" | "tail" | "right"(그 밖은 기존 동작)
    if scheme.startswith("official") and scheme != "official_ai":
        off_delay = official_delay_for(c["seed"], off_delay, ov.get("delay_draw"))   # E1(환경 변수 없으면 그대로 779), P4 는 ov delay_draw
    slack_kmh = SLACK_KMH if mode == "slack" else 0.0        # P6(c) 부분 준수
    pre = max(0.0, SHAM_WARM - T_INC) if mode == "sham" else 0.0   # sham 만 예열을 늘린다(본 흐름·사고는 같고 앞에 예열 흐름만 붙는다)
    t_inc = T_INC + pre
    t_clear = t_inc + dur
    t_end = t_clear + 900.0
    rou = build_routes(work, c if not false_alarm else {**c, "blocked": 0}, t_end, f"{c['seed']}", pre)
    sham_at = sham_end = None
    if mode == "sham":                                # 사고 5~20분 전 무작위 시각(씨앗 고정), 유지 = 처리 시간, 단 사고 시각에서 끊는다(사고 뒤 경고 없음)
        sham_at = t_inc - random.Random(f"sham|{c['seed']}").uniform(300.0, 1200.0)
        sham_end = min(sham_at + dur, t_inc)
    right_lane = next((k for k in range(LANES) if k >= c["blocked"]), LANES - 1)   # E5: 가장 오른쪽(0 쪽) 개방 차로
    rng = random.Random(f"{scheme}|{c['seed']}")
    ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", str(STEP), "--seed", str(c["seed"]), "--no-step-log", "true",
              "--no-warnings", "true", "--collision.action", "warn", "--end", str(t_end), "--time-to-teleport", "-1",
              "--threads", "1", "--thread-rngs", "64"]   # E8: 결정성에 걸린 값은 기본값이라도 명시(버전이 바뀌어도 같게)
             + (["--collision.mingap-factor", MINGAP_F] if MINGAP_F else []))
    coll = {}
    length, equipped, comply, inatt, attn_ok = {}, {}, {}, set(), {}
    warned, cw, cw_set, ow = set(), set(), {}, set()
    pair_ttc, pair_dv, pair_at = {}, {}, {}
    pair_drac, exposed, relapse, pending = {}, set(), {}, {}   # DRAC(m/s²), 상류 6 km 노출 차, 다시 딴짓 시각, 지연된 권고 반응
    wide = {}                                         # PAIR_TTC 기록: 쌍 → [최소 TTC, PAIR_T 문턱별 최대 속도 차 …]
    stop_since, slow_since = {}, {}
    inc_at = None if not false_alarm else t_inc + 1.0        # 거짓 경보: 사고 없이 Tago 가 바로 확정
    jam_known, tail = False, INC_POS
    depart, arrive, crashes = {}, {}, set()
    crash_ids = [f"crash{k}" for k in range(c["blocked"])]
    blocked_lanes = list(range(c["blocked"]))                 # 바깥(0)부터
    passed_fast = set()
    false_cleared = None
    official_at = (t_inc + off_delay) if off_delay is not None else None
    max_back = 0.0
    pair_t0 = {}                                      # E2·E4: 쌍이 처음 등록된 시각
    jam_gone_at = None                                # E4: 처리 뒤 정체 길이가 처음 300 m 아래로 내려간 시각
    sw, warn_first, warn_last = set(), None, None     # sham 으로 경고받은 차, 새 경고를 준 첫·끝 시각
    lane_comply, lane_all = [0] * LANES, [0] * LANES  # E5 점검: 앞 6 km 안 '경고받은 따르는 차' / 모든 차의 차로 분포(10 s 마다)
    t = 0.0
    while t < t_end:
        ts.simulationStep()
        t = ts.simulation.getTime()
        for v in ts.simulation.getDepartedIDList():
            if v.startswith("crash"):
                continue
            depart[v] = t
            ts.vehicle.subscribe(v, [tc.VAR_SPEED, tc.VAR_DISTANCE, tc.VAR_LANE_INDEX])
            typ = ts.vehicle.getTypeID(v)
            length[v] = 12.0 if typ == "truck" else 4.5
            u = random.Random(f"veh|{c['seed']}|{v}")     # 차마다 고정: 보급·따름(같은 씨앗이면 어느 방식에서나 같은 차)
            equipped[v] = u.random() < p
            comply[v] = u.random() < c["comply"]
            attn_ok[v] = u.random() < attn_p             # 차마다 고정(같은 씨앗이면 어느 방식에서나 같다)
            if typ == "car_i":
                inatt.add(v)
        for v in ts.simulation.getArrivedIDList():
            if v in depart:
                arrive[v] = t
            if agg is not None:
                agg["prev"].pop(v, None)
        if not false_alarm and abs(t - t_inc) < STEP / 2:
            if confirm_fix and p > 0 and inc_at is None:     # P9: 사고 차가 모두 앱 차면 1 s, 하나면 무응답 30 s 뒤
                n_eq = sum(random.Random(f"crash|{c['seed']}|{k}").random() < p for k in range(len(crash_ids)))
                if n_eq == len(crash_ids):
                    inc_at = t_inc + 1.0
                elif n_eq >= 1:
                    inc_at = t_inc + 31.0
            gawk = dict(PARAMS["gawk"]).get(c["blocked"])
            if gawk:                                      # 구경 감속: 열린 차로도 사고 옆을 천천히 지난다(용량 보정)
                for k in range(c["blocked"], LANES):
                    ts.lane.setMaxSpeed(f"inc_{k}", gawk / 3.6)
        if not false_alarm and abs(t - t_clear) < STEP / 2:
            for k in range(LANES):
                ts.lane.setMaxSpeed(f"inc_{k}", VMAX)
            if p > 0 and not confirm_fix:                     # 정정 전 경로: 처리 종료 시점에 기록값만 덮어쓴다(P9 에서 정정)
                n_eq = sum(random.Random(f"crash|{c['seed']}|{k}").random() < p for k in range(len(crash_ids)))
                if n_eq == len(crash_ids):
                    inc_at = t_inc + 1.0
                elif n_eq >= 1:
                    inc_at = t_inc + 31.0
        sub = ts.vehicle.getAllSubscriptionResults()
        ids = [v for v in sub if not v.startswith("crash")]
        active = t_inc <= t < (t_clear if not false_alarm else (false_cleared or t_end))
        if agg is not None:                               # P3 급제동(상승 에지)·P1/P5/P7 10 s 스냅샷 — 읽기만
            pv, br = agg["prev"], agg["brake"]
            for v in ids:
                s = sub[v][tc.VAR_SPEED]; q = pv.get(v)
                if q is None or t < t_inc:
                    pv[v] = (s, 0.0); continue
                dec = (q[0] - s) / STEP
                if dec >= 2.45 and q[1] < 2.45:
                    inz = 0 < INC_POS - sub[v][tc.VAR_DISTANCE] <= WARN_INC
                    br["e25_all"] += 1; agg["bv_all"].add(v)
                    if inz:
                        br["e25_zone"] += 1; agg["bv_zone"].add(v)
                if dec >= 3.43 and q[1] < 3.43:
                    br["e35_all"] += 1; br["e35_zone"] += int(0 < INC_POS - sub[v][tc.VAR_DISTANCE] <= WARN_INC)
                pv[v] = (s, dec)
            if t >= t_inc and float(t).is_integer() and int(t) % 10 == 0:
                lane_sp = {}
                for v in ids:
                    x, s, li = sub[v][tc.VAR_DISTANCE], sub[v][tc.VAR_SPEED], sub[v][tc.VAR_LANE_INDEX]
                    rb = int(x // 1000)
                    if 0 <= rb < len(agg["road"]):
                        agg["road"][rb][0] += 1; agg["road"][rb][1] += s
                    gap = INC_POS - x
                    if t < t_clear and 0 < gap <= WARN_INC:
                        wc = v in warned and comply[v]
                        b = min(11, int((gap - 1e-9) // 500)); z = agg["zone"][b]
                        z[0] += 1; z[1] += s; z[2] += s * s
                        if wc:
                            z[3] += 1; z[4] += s; z[5] += s * s
                        e = lane_sp.setdefault((b, li), [0, 0.0]); e[0] += 1; e[1] += s
                        lp = agg["lanepos"][min(5, int((gap - 1e-9) // 1000))][li]; lp[1] += 1; lp[0] += int(wc)
                for b in range(12):
                    m = {li: lane_sp[(b, li)][1] / lane_sp[(b, li)][0] for li in range(LANES) if (b, li) in lane_sp}
                    if len(m) >= 2:
                        lv = agg["lanevar"][b]; lv[0] += statistics.pstdev(m.values()); lv[1] += 1
                        adj = [abs(m[li] - m[li + 1]) for li in range(LANES - 1) if li in m and li + 1 in m]
                        if adj:
                            lv[2] += max(adj); lv[3] += 1
        # Tago: 사고 의심 확정(앱 차 2대 사고 지점 정차 30 s)
        if p > 0 and not false_alarm and inc_at is None and t > t_inc:
            n = 0
            for v in ids:
                if equipped[v] and sub[v][tc.VAR_SPEED] < 1.4 and INC_POS - 300 <= sub[v][tc.VAR_DISTANCE] <= INC_POS:
                    stop_since.setdefault(v, t)
                    n += t - stop_since[v] >= 30
                else:
                    stop_since.pop(v, None)
            if n >= 2:
                inc_at = t + 1.0
        # Tago: 정체 확정과 꼬리(느린 앱 차의 가장 상류)
        if p > 0 and tail_on and t_inc <= t and (t < t_clear + 300 or (mode == "tail" and jam_gone_at is None)):
            slow_eq = []
            for v in ids:
                if equipped[v] and sub[v][tc.VAR_SPEED] < SLOW_MS and 0 < sub[v][tc.VAR_DISTANCE] <= INC_POS:
                    slow_since.setdefault(v, t)
                    if t - slow_since[v] >= SLOW_HOLD:
                        slow_eq.append(sub[v][tc.VAR_DISTANCE])
                else:
                    slow_since.pop(v, None)
            if len(slow_eq) >= 2:
                jam_known = True
                tail = min(slow_eq) + tail_err
            elif jam_known and not slow_eq:
                jam_known = False
        if not false_alarm and t_inc <= t < t_clear:
            slow_all = sorted((sub[v][tc.VAR_DISTANCE] for v in ids if sub[v][tc.VAR_SPEED] < SLOW_MS and 0 < sub[v][tc.VAR_DISTANCE] <= INC_POS), reverse=True)
            if slow_all and INC_POS - slow_all[0] < 500:     # 정체 = 사고 지점부터 끊기지 않고(간격 300 m 미만) 이어진 느린 차 줄
                back = slow_all[0]
                for x in slow_all[1:]:
                    if back - x >= 300:
                        break
                    back = x
                max_back = max(max_back, INC_POS - back)
        if not false_alarm and t >= t_clear and jam_gone_at is None:   # E4: 처리 뒤 정체 소멸(읽기만 — tail 방식에서만 경고 종료에 쓴다)
            slow_all = sorted((sub[v][tc.VAR_DISTANCE] for v in ids if sub[v][tc.VAR_SPEED] < SLOW_MS and 0 < sub[v][tc.VAR_DISTANCE] <= INC_POS), reverse=True)
            if jam_chain_len(slow_all) < JAM_GONE:     # 처리 뒤에는 줄 머리가 사고 지점을 떠나므로 '가장 긴 이어진 줄'의 길이
                jam_gone_at = t
        if mode == "tail" and not false_alarm:        # E4 u80tail: 경고를 정체 소멸까지
            active = t_inc <= t < t_clear or (t >= t_clear and jam_gone_at is None)
        sham_on = sham_at is not None and sham_at <= t < sham_end
        # 거짓 경보 해제: 앱 차 3대가 그 지점을 시속 60 km 넘게 지나감(CLEAR_PASS)
        if false_alarm and false_cleared is None and t > t_inc:
            for v in ids:
                if equipped[v] and sub[v][tc.VAR_SPEED] > 16.7 and abs(sub[v][tc.VAR_DISTANCE] - INC_POS) < 50:
                    passed_fast.add(v)
            if len(passed_fast) >= 3:
                false_cleared = t
        # 상충
        if t >= t_inc:
            lanes = {}
            for v in ids:
                d = sub[v]
                lanes.setdefault(d[tc.VAR_LANE_INDEX], []).append((d[tc.VAR_DISTANCE], d[tc.VAR_SPEED], v))
                if t < t_clear and INC_POS - 6000 <= d[tc.VAR_DISTANCE] <= INC_POS:
                    exposed.add(v)
            if not false_alarm and t < t_clear:
                for k, lane in enumerate(blocked_lanes):
                    lanes.setdefault(lane, []).append((INC_POS, 0.0, crash_ids[k]))
            for lane_i, row in lanes.items():
                row.sort()
                for (xf, vf, f), (xl, vl, l) in zip(row, row[1:]):
                    dv = vf - vl
                    if dv > 0.5:
                        g = xl - xf - length.get(l, 4.5)
                        if PAIR_TTC and g >= 0 and g / dv < PAIR_TTC:
                            w = wide.setdefault((f, l), [9.9] + [0.0] * len(PAIR_T)); w[0] = min(w[0], g / dv)
                            for i_t, th in enumerate(PAIR_T, 1):
                                if g / dv < th:
                                    w[i_t] = max(w[i_t], dv)
                        if g >= 0 and g / dv < TTC_CONFLICT:
                            k = (f, l); ttc = g / dv
                            if ttc < pair_ttc.get(k, 9.9):
                                pair_ttc[k] = ttc; pair_at[k] = (xf, vf)
                            if rec is not None and dv >= FAST_DV and pair_dv.get(k, 0.0) < FAST_DV:
                                rec["events"].append([round(t, 1), round(xf, 1), lane_i] + ([round(xl, 1), round(dv * 3.6), round(vf * 3.6)] if REC_ID else []))   # 고속 접근 상충이 처음 성립한 때·곳(3D 재생용)
                            pair_dv[k] = max(pair_dv.get(k, 0.0), dv)
                            pair_t0.setdefault(k, t)
                            pair_drac[k] = max(pair_drac.get(k, 0.0), dv * dv / (2 * max(g, 0.1)))
            for col in ts.simulation.getCollisions():
                crashes.add((col.collider, col.victim))
                if COLL_DIAG and (col.collider, col.victim) not in coll:
                    coll[(col.collider, col.victim)] = [round(t, 1), col.type, col.lane, round(col.pos, 1), round(col.colliderSpeed * 3.6, 1), round(col.victimSpeed * 3.6, 1),
                                                        col.colliderType, col.victimType, None]
                    try:                                      # 실제 간격 = SUMO 앞차 간격 + 뒤차 minGap (음수면 겹침)
                        ld = ts.vehicle.getLeader(col.collider, 100.0)
                        if ld and ld[0] == col.victim:
                            coll[(col.collider, col.victim)][-1] = round(ld[1] + ts.vehicle.getMinGap(col.collider), 2)
                    except Exception:
                        pass
        if rec is not None:
            if int(t * 2) % 20 == 0:                       # 10 s × 100 m 칸 평균 속도
                for v in ids:
                    key = (int(t // 10), int(sub[v][tc.VAR_DISTANCE] // 100))
                    g = rec["grid"].setdefault(key, [0.0, 0]); g[0] += sub[v][tc.VAR_SPEED]; g[1] += 1
            if t_inc - 20 <= t <= t_inc + REC_WIN[2] and float(t).is_integer() and int(t - t_inc) % REC_WIN[3] == 0:
                if REC_ID:
                    rec.setdefault("tail", []).append([t, round(tail, 1) if jam_known else None])
                rec["frames"].append([t, [[round(sub[v][tc.VAR_DISTANCE], 1), sub[v][tc.VAR_LANE_INDEX], round(sub[v][tc.VAR_SPEED], 2),
                                           int(v in warned), int(equipped[v]), int(length[v] > 5)]
                                          + ([rec["ids"].setdefault(v, len(rec["ids"])), cw_set.get(v, 0) if v in cw else 80 if v in ow else 0, int(comply[v])] if REC_ID else [])
                                          for v in ids if INC_POS + REC_WIN[0] <= sub[v][tc.VAR_DISTANCE] <= INC_POS + REC_WIN[1]]])
        # 경고
        relay_at = (inc_at + relay_delay) if (relay and inc_at is not None) else None

        def follow(v, tago_msg):                          # 따르는 운전자의 반응(차로 바꾸기·권장 속도)
            lane = sub[v][tc.VAR_LANE_INDEX]
            if mode == "right" and tago_msg:               # E5: 따르는 차는 모두 가장 오른쪽 개방 차로로(같은 장치, 목표만 다름)
                if lane != right_lane:
                    ts.vehicle.changeLane(v, right_lane, 60.0)
            elif lane in blocked_lanes and not (tago_msg and adv in ("none", "u80nl")):   # u80nl: 일률 80, 차로 권고 없음
                ts.vehicle.changeLane(v, max(blocked_lanes) + 1, 60.0)
            if tago_msg and adv == "none":
                pass                                       # 권고 없음: 주의만 끈다
            elif tago_msg and tail_on and adv in ("graded", "near", "u80near"):
                cw.add(v)                                  # Tago 권장 속도(꼬리까지 거리별)
            else:
                ts.vehicle.setMaxSpeed(v, (OFFICIAL_KMH + slack_kmh) / 3.6); ow.add(v)   # P6(c) slack: 80 → 90
        for v, tt in list(relapse.items()):              # 주의가 돌아온 뒤 다시 딴짓
            if t >= tt:
                relapse.pop(v)
                if v in sub:
                    ts.vehicle.setParameter(v, "device.driverstate.awareness", str(PARAMS["inatt_aware"]))
        for v, (tt, msg) in list(pending.items()):      # 반응 지연이 지난 권고
            if t >= tt:
                pending.pop(v)
                if v in sub and active:
                    follow(v, msg)
        if sw and t >= sham_end:                          # sham 유지 끝: 제한을 풀고, 뒤의 공식 안내는 다시 받을 수 있게
            for v in sw:
                warned.discard(v)
                if v in ow:
                    ow.discard(v)
                    if v in sub:
                        ts.vehicle.setMaxSpeed(v, VMAX + 3)
            sw.clear()
        if active or sham_on:
            for v in ids:
                if v in warned:
                    continue
                x = sub[v][tc.VAR_DISTANCE]
                gap = INC_POS - x
                if gap <= 0:
                    continue
                by_official = official_at is not None and t >= official_at and gap <= WARN_INC
                got = not loss or random.Random(f"loss|{c['seed']}|{v}").random() >= loss   # 연계 메시지를 받은 차(차마다 고정)
                by_relay = got and relay_at is not None and t >= relay_at and gap <= WARN_INC
                by_tago = equipped[v] and ((inc_at is not None and t >= inc_at and gap <= WARN_INC) or (jam_known and 0 < tail - x <= WARN_TAIL))
                if got and relay_at is not None and t >= relay_at and jam_known and 0 < tail - x <= WARN_TAIL:
                    by_relay = by_tago = True                  # 넘긴 꼬리 경고는 사고 지점 6 km 밖의 꼬리에도 간다
                by_sham = sham_on and gap <= WARN_INC          # E3: 사고 전 가짜 경고(일률 80 과 같은 문구·범위)
                if not (by_official or by_relay or by_tago or by_sham):
                    continue
                warned.add(v)
                if by_sham:
                    sw.add(v)
                warn_first = t if warn_first is None else warn_first
                warn_last = t
                if v in inatt and not NO_ATTN and attn_ok.get(v, True):
                    ts.vehicle.setParameter(v, "device.driverstate.awareness", "1.0")   # 경고가 주의를 되돌린다
                    if redist:
                        relapse[v] = t + redist
                if comply[v]:
                    if delay:
                        pending[v] = (t + delay, by_tago or by_relay or by_sham)
                    else:
                        follow(v, by_tago or by_relay or by_sham)
        if active:
            if float(t).is_integer() and int(t) % 10 == 0:   # E5 점검 기록(읽기만)
                for v in ids:
                    if 0 < INC_POS - sub[v][tc.VAR_DISTANCE] <= WARN_INC:
                        ln = sub[v][tc.VAR_LANE_INDEX]
                        lane_all[ln] += 1
                        if v in warned and comply[v]:
                            lane_comply[ln] += 1
            for v in sorted(cw):                            # E8: 집합 반복 순서가 PYTHONHASHSEED 에 기대지 않게
                if v not in sub:
                    cw.discard(v); continue
                x = sub[v][tc.VAR_DISTANCE]
                if x > INC_POS + 100:
                    ts.vehicle.setMaxSpeed(v, VMAX + 3); cw.discard(v); continue
                d = (tail - x) if jam_known else (INC_POS - x)
                if adv == "near":
                    kmh = 70 if d <= 1000 else round((VMAX + 3) * 3.6)   # 꼬리 1 km 안에서만 권고, 그 밖은 원래 속도
                elif adv == "u80near":
                    kmh = 70 if d <= 1000 else 80                       # 일률 80, 꼬리 1 km 안에서만 70
                else:
                    kmh = 90 if d > 2000 else 70 if d > 1000 else 50
                if slack_kmh and kmh <= 90:
                    kmh += slack_kmh                           # P6(c) slack: 90·70·50 → 100·80·60
                if cw_set.get(v) != kmh:
                    cw_set[v] = kmh
                    ts.vehicle.setMaxSpeed(v, kmh / 3.6)
        for v in sorted(ow):                              # 일률 80 km/h 는 사고 지점을 지나면 푼다(E8: 정렬 = 순서 고정)
            if v not in sub:
                ow.discard(v)
            elif sub[v][tc.VAR_DISTANCE] > INC_POS + 100 or not (active or sham_on):
                ts.vehicle.setMaxSpeed(v, VMAX + 3); ow.discard(v)
        if not active and cw:                             # 끝나면 원래 속도로
            for v in sorted(cw):                            # E8: 집합 반복 순서가 PYTHONHASHSEED 에 기대지 않게
                if v in sub:
                    ts.vehicle.setMaxSpeed(v, VMAX + 3)
                cw.discard(v)
    ts.close()
    kinds = {"merge": 0, "queue": 0, "approach": 0, "other": 0}
    for k in pair_ttc:
        x, vf = pair_at[k]
        kinds["merge" if INC_POS - 300 <= x <= INC_POS else "queue" if vf < SLOW_MS else "approach" if pair_dv[k] >= FAST_DV else "other"] += 1
    tts = [arrive[v] - depart[v] for v in arrive if t_inc - 300 <= depart[v] <= t_clear]
    rel = lambda x: None if x is None else round(x - t_inc, 2)
    psum = pair_record(c, scheme, false_alarm, ov, pair_ttc, pair_dv, pair_t0, t_inc, t_clear, jam_gone_at,
                       equipped, comply, inatt, length, depart, exposed)
    agg_out = {}
    if agg is not None:                                   # P2 집단별 통행 시간 + P1/P3/P5/P7 집계(집합은 수로)
        wc = lambda v: v in warned and comply[v]
        tt_c = [arrive[v] - depart[v] for v in arrive if t_inc - 300 <= depart[v] <= t_clear and wc(v)]
        tt_o = [arrive[v] - depart[v] for v in arrive if t_inc - 300 <= depart[v] <= t_clear and not wc(v)]
        agg_out = {"agg": {"zone": agg["zone"], "lanevar": agg["lanevar"], "lanepos": agg["lanepos"], "road": agg["road"],
                           "brake": {**agg["brake"], "v25_all": len(agg["bv_all"]), "v25_zone": len(agg["bv_zone"]), "veh": len(depart)},
                           "travel_grp": {"warned_comply": [len(tt_c), statistics.mean(tt_c) if tt_c else None],
                                          "other": [len(tt_o), statistics.mean(tt_o) if tt_o else None]}}}
    return {"seed": c["seed"], "scheme": scheme, "false": false_alarm, "cond": c, **({"ov": ov} if ov else {}),
            "conflicts": len(pair_ttc), "fast": sum(1 for k in pair_ttc if pair_dv[k] >= FAST_DV), "severe": sum(1 for v in pair_ttc.values() if v < 0.75),
            "fast1": sum(1 for k, v in pair_ttc.items() if v < TTC_STRICT and pair_dv[k] >= FAST_DV),
            "drac": sum(1 for v in pair_drac.values() if v > 3.35), "exposed": len(exposed),
            "kinds": kinds, "crashes": len(crashes), "travel": statistics.mean(tts) if tts else None, "arrived": sum(1 for v in arrive if v[0] != "w"),
            "inc_at": None if inc_at is None else round(inc_at - t_inc, 1), "queue_km": round(max_back / 1000, 2),
            "false_cleared": None if false_cleared is None else round(false_cleared - t_inc, 1),
            "truncated": max_back > UP - 500,
            "prov": PROV,                                       # E8: 실행 환경
            **({"coll": list(coll.values())} if COLL_DIAG else {}), **({"mingap_f": MINGAP_F} if MINGAP_F else {}),
            **({"pairs": [[round(w[0], 4)] + [round(x * 3.6, 3) for x in w[1:]] for w in wide.values()]} if PAIR_TTC else {}),
            ("pairs_e" if PAIR_TTC else "pairs"): psum,     # E2·E4·E6 쌍 요약(PAIR_TTC 가 켜져 'pairs' 를 쓰면 'pairs_e')
            "official_delay": off_delay, "jam_gone_at": rel(jam_gone_at), "t_clear_rel": round(t_clear - t_inc, 2),
            "warn_first": rel(warn_first), "warn_last": rel(warn_last), "lane_comply": lane_comply, "lane_all": lane_all,
            **({"sham_at": rel(sham_at), "sham_end": rel(sham_end), "warm_pre": pre} if mode == "sham" else {}), **agg_out,
            **({"record": {"grid": [[k[0], k[1], g[0] / g[1]] for k, g in rec["grid"].items()], "frames": rec["frames"], "events": rec["events"], "tail": rec.get("tail", []),
                           "official_at": official_at, "relay_at": (inc_at + relay_delay) if (relay and inc_at is not None) else None,
                           "t_clear": t_clear}} if rec is not None else {})}


def pair_record(c, scheme, false_alarm, ov, pair_ttc, pair_dv, pair_t0, t_inc, t_clear, jam_gone_at,
                equipped, comply, inatt, length, depart, exposed):
    """E2·E4·E6: 상충 쌍(TTC < 1.5 s)마다 뒤차·앞차 종류·최대 속도 차·최소 TTC·단계를 남긴다(지표에는 손대지 않음).
    쌍 목록은 pool_run 이 정한 TAGO_OUT_STEM 이 있으면 results/pairs/{stem}_{seed}_{scheme}.json.gz, 레코드에는 요약만.
    단계: a = 처리 중, b = 처리 뒤 정체 소멸(가장 긴 느린 차 줄 < 300 m) 전, c = 소멸 뒤"""
    def kind(v):
        if v.startswith("crash"):
            return [None, None, None, None]
        return [int(equipped.get(v, False)), int(comply.get(v, False)), int(v in inatt), int(length.get(v, 4.5) > 5)]
    grp = lambda v: "crash" if v.startswith("crash") else f"a{int(equipped.get(v, False))}c{int(comply.get(v, False))}"
    rows = []
    s = {"n": 0, "by_f": {}, "by_l": {}, "f_inatt": [0, 0, 0], "f_truck": [0, 0, 0], "phase": {"a": [0, 0, 0], "b": [0, 0, 0], "c": [0, 0, 0]},
         "ke_MJ": {"all": 0.0, "fast": 0.0, "severe": 0.0}, "ke_by_f": {}}
    for (f, l), ttc in pair_ttc.items():
        dv, t0 = pair_dv[(f, l)], pair_t0[(f, l)]
        fast, sev = dv >= FAST_DV, ttc < 0.75
        ph = "a" if t0 < t_clear else "b" if (jam_gone_at is None or t0 < jam_gone_at) else "c"
        ke = 0.5 * (MASS["truck"] if length.get(f, 4.5) > 5 else MASS["car"]) * dv * dv / 1e6
        rows.append([f, l] + kind(f) + kind(l) + [round(dv, 3), round(ttc, 4), int(fast), int(sev), ph, round(t0 - t_inc, 2)])
        inc = [1, int(fast), int(sev)]
        for key, d in ((grp(f), s["by_f"]), (grp(l), s["by_l"])):
            d[key] = [a + b for a, b in zip(d.get(key, [0, 0, 0]), inc)]
        if f in inatt:
            s["f_inatt"] = [a + b for a, b in zip(s["f_inatt"], inc)]
        if length.get(f, 4.5) > 5:
            s["f_truck"] = [a + b for a, b in zip(s["f_truck"], inc)]
        s["phase"][ph] = [a + b for a, b in zip(s["phase"][ph], inc)]
        s["ke_MJ"]["all"] += ke; s["ke_MJ"]["fast"] += ke * fast; s["ke_MJ"]["severe"] += ke * sev
        s["ke_by_f"][grp(f)] = s["ke_by_f"].get(grp(f), 0.0) + ke
        s["n"] += 1
    s["ke_MJ"] = {k: round(v, 4) for k, v in s["ke_MJ"].items()}
    s["ke_by_f"] = {k: round(v, 4) for k, v in s["ke_by_f"].items()}
    veh, vexp = {}, {}                                  # 1,000대당 비율의 분모: 출발한 차·노출(처리 중 앞 6 km 에 있던) 차, 집단별
    for v in depart:
        veh[grp(v)] = veh.get(grp(v), 0) + 1
        if v in exposed:
            vexp[grp(v)] = vexp.get(grp(v), 0) + 1
    s["veh"], s["veh_exp"] = veh, vexp
    s["veh_inatt"] = sum(1 for v in depart if v in inatt)
    s["veh_truck"] = sum(1 for v in depart if length.get(v, 4.5) > 5)
    stem = os.environ.get("TAGO_OUT_STEM")
    s["file"] = None
    if stem:
        import gzip, hashlib
        tag = f"{stem}_{c['seed']}_{scheme}" + ("_false" if false_alarm else "") + (("_" + hashlib.md5(json.dumps(ov, sort_keys=True).encode()).hexdigest()[:8]) if ov else "")
        fn = RES / "pairs" / f"{tag}.json.gz"
        fn.parent.mkdir(parents=True, exist_ok=True)
        cols = ["f", "l", "f_app", "f_comply", "f_inatt", "f_truck", "l_app", "l_comply", "l_inatt", "l_truck", "dv_max_ms", "ttc_min", "fast", "severe", "phase", "t0_rel"]
        with gzip.open(fn, "wt", encoding="utf-8") as g:
            json.dump({"seed": c["seed"], "scheme": scheme, "false": false_alarm, "ov": ov or {}, "cols": cols, "rows": rows}, g, ensure_ascii=False)
        s["file"] = str(fn.relative_to(RES)).replace("\\", "/")
    return s


def pool_run(tasks, out, procs=None):
    RES.mkdir(exist_ok=True)
    os.environ["TAGO_OUT_STEM"] = out.stem            # 자식 프로세스(spawn)가 쌍 파일 이름에 쓴다
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            d = json.loads(line); done.add((d["seed"], d["scheme"], d["false"], json.dumps(d.get("ov") or {}, sort_keys=True)))
    todo = [x for x in tasks if (x[0]["seed"], x[1], x[2], json.dumps(x[4] if len(x) > 4 and x[4] else {}, sort_keys=True)) not in done]   # 덮어쓰기(ov)가 다르면 다른 실행
    print(f"{len(tasks)} 실행 중 {len(todo)} 남음 → {out.name}", flush=True)
    t0 = time.time()
    with mp.get_context("spawn").Pool(procs or int(os.environ.get("TAGO_PROCS", 0)) or max(1, os.cpu_count() - 4),
                                      maxtasksperchild=1) as pool, out.open("a", encoding="utf-8") as f:   # E8: 실행마다 새 프로세스(libsumo 정적 상태가 넘어오지 않게)
        for i, r in enumerate(pool.imap_unordered(run_one, todo), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)


def calib():
    """보정: 사고 없는 흐름(실측 교통량)과 차로 차단 때 사고 지점 통과 유량"""
    import libsumo as ts
    work = RES / "_work" / "calib"
    net = build_net(work)
    for blocked in (0, 1, 2):
        c = {"seed": 1, "demand": 6691, "blocked": blocked, "dur": 1800, "rain": False, "inatt": 0.15, "comply": 0.7, "truck": 0.15, "tau": PARAMS["tau"], "sigma": PARAMS["sigma"]}
        rou = build_routes(work, c, 2400, "calib")
        ts.start(["sumo", "-n", str(net), "-r", str(rou), "--step-length", str(STEP), "--no-step-log", "true", "--no-warnings", "true", "--end", "2400", "--time-to-teleport", "-1"])
        ts.route.add("rinc", ["inc", "down"])
        n, sp = 0, []
        while ts.simulation.getTime() < 2400:
            ts.simulationStep(); t = ts.simulation.getTime()
            if blocked and abs(t - 600) < STEP / 2:
                for k in range(blocked):
                    ts.vehicle.add(f"crash{k}", "rinc", typeID="car", depart="now", departLane=str(k), departPos="290", departSpeed="0")
                    ts.vehicle.setStop(f"crash{k}", "inc", pos=300.0, laneIndex=k, duration=1800)
            if t > 1200:
                n += ts.simulation.getArrivedNumber()
                if t % 30 == 0:
                    ids = [v for v in ts.vehicle.getIDList() if not v.startswith("crash")]
                    ups = [ts.vehicle.getSpeed(v) for v in ids if ts.vehicle.getDistance(v) < INC_POS - 3000]
                    sp.append(statistics.mean(ups) * 3.6 if ups else 0)
        ts.close()
        flow = n / 1200 * 3600
        print(f"차단 {blocked}차로: 하류 유량 {flow:.0f}대/시 = 열린 차로당 {flow / (LANES - blocked):.0f}대/시, 상류 평균 속도 {statistics.mean(sp):.0f}km/h", flush=True)


def main_exp(n):
    seeds = range(1, n + 1)
    schemes = list(SCHEMES)
    pool_run([(cond_for(s), sc, False) for s in seeds for sc in schemes], RES / "main.jsonl")


def followup_exp(n):
    """후속 실험(권고 방식, 사전 고정 docs/sim-preregistration.md '후속'): v2 설정 + 넘김 권고 방식 3가지 → results/fu_{tag}.jsonl"""
    tag = os.environ.get("TAGO_V2_TAG", "pc")
    schemes = ("official+tago12+relay-u80", "official+tago12+relay-near", "official+tago12+relay-none")
    if tag != "pc":                                  # 다른 기계 재현은 기준선·단계까지 같은 기계에서
        schemes = ("official", "official+tago12+relay") + schemes
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in schemes], RES / f"fu_{tag}.jsonl")


def robust_exp(kind, n):
    """강건성 실험(사전 고정 docs/sim-preregistration.md '강건성'): v2 설정 위에서
    comply = TAGO_COMPLY 아래 기준선·단계·일률 80(PC) → results/rb_comply.jsonl
    design = 80+꼬리 70·일률 80 차로 권고 없음·보급 1.5 % 일률 80(PC, 짝은 v2_main·fu_pc) → results/rb_design.jsonl
    attn   = TAGO_ATTN_P 아래 기준선·단계·일률 80(맥) → results/rb_attn{p}.jsonl"""
    G, U = "official+tago12+relay", "official+tago12+relay-u80"
    if kind == "comply":
        assert os.environ.get("TAGO_COMPLY"), "TAGO_COMPLY 를 정한다"
        schemes, out = ("official", G, U), "rb_comply.jsonl"
    elif kind == "design":
        schemes, out = ("official+tago12+relay-u80near", "official+tago12+relay-u80nl", "official+tago1.5+relay-u80"), "rb_design.jsonl"
    else:
        schemes, out = ("official", G, U), f"rb_attn{ATTN_P:g}.jsonl"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in schemes], RES / out)


def confirm_exp(lo, hi):
    """확인 실험 R6(사전 고정 docs/sim-preregistration.md 'R6'): 새 씨앗 lo~hi, 기준선·단계·일률 80, 상충 쌍 기록 → results/r6_confirm.jsonl"""
    assert PAIR_TTC >= 3.0, "TAGO_PAIR_TTC=3 으로 쌍을 남긴다"
    pool_run([(cond_for(s), sc, False) for s in range(lo, hi + 1)
              for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80")], RES / "r6_confirm.jsonl")


def j1_sets(n=32):
    """J1 매개변수 집합(라틴 하이퍼큐브, 시드 j1): attn_p, redist(s), delay(s), comply"""
    r = random.Random("j1")
    col = lambda: r.sample([(i + r.random()) / n for i in range(n)], n)
    a, b, d, cp = col(), col(), col(), col()
    return [{"attn_p": round(a[i], 3), "redist": round(5 * (600 / 5) ** b[i], 1), "delay": round(8 * d[i], 2),
             "comply": round(0.05 + 0.8 * cp[i], 3)} for i in range(n)]


def j1_exp():
    """탐색 실험 J1(사전 고정 docs/sim-preregistration.md 'J1') → results/j1.jsonl"""
    tasks = []
    for k, ov in enumerate(j1_sets()):
        for s in range(301 + 4 * k, 305 + 4 * k):
            for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80"):
                tasks.append((cond_for(s), sc, False, False, ov))
    pool_run(tasks, RES / "j1.jsonl")


def d1_conds():
    """D1 조건: 하나씩 바꾼다(기본: 연계 30 s, 손실 0, 꼬리 오차 0)"""
    return ([{"relay_delay": d} for d in (0.0, 5.0, 15.0, 60.0)] + [{"loss": q} for q in (0.1, 0.3)]
            + [{"tail_err": e} for e in (-1000.0, -500.0, 500.0, 1000.0)])


def d1_exp():
    """탐지·통신 실패 D1(사전 고정 docs/sim-preregistration.md 'D1') → results/d1.jsonl"""
    pool_run([(cond_for(s), "official+tago12+relay-u80", False, False, ov) for ov in d1_conds() for s in range(1, 25)], RES / "d1.jsonl")


def d2_conds():
    """D2 조건: 실패를 겹친다(사전 고정 'D2'). 중간 결합 = 지연 15 s + 손실 10 % + 꼬리 오차 +500 m, 나쁜 결합 = 60 s + 30 % + +1,000 m"""
    return [{"relay_delay": 15.0, "loss": 0.1, "tail_err": 500.0}, {"relay_delay": 60.0, "loss": 0.3, "tail_err": 1000.0}]


def d2_exp():
    """결합 실패 D2(사전 고정 docs/sim-preregistration.md 'D2') → results/d2.jsonl"""
    pool_run([(cond_for(s), "official+tago12+relay-u80", False, False, ov) for ov in d2_conds() for s in range(1, 25)], RES / "d2.jsonl")


def m1_exp(n=24):
    """추종 모형 점검 M1(사전 고정 'M1'): TAGO_CF=IDM 에서 기준선·단계·일률 80 → results/m1_{모형}.jsonl"""
    assert CF_MODEL, "TAGO_CF=IDM 을 정한다"
    tag = CF_MODEL.lower() + (f"_b{CAR_DECEL.rstrip('0').rstrip('.')}" if CAR_DECEL != "4.5" else "")   # M1b: m1_idm_b2.jsonl
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80")],
             RES / f"m1_{tag}.jsonl")


def sevcal_exp(n=24):
    """운영 보정 확인 C3(사전 고정 'C3'): TAGO_SEV=cal TAGO_UP=30000 TAGO_TINC=1200 에서 기준선·단계·일률 80 → results/sev_cal_{tag}.jsonl"""
    assert SEV == "cal" and UP >= 30000 and T_INC >= 1200, "TAGO_SEV=cal TAGO_UP=30000 TAGO_TINC=1200 을 정한다"
    tag = os.environ.get("TAGO_V2_TAG", "mac")
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80")],
             RES / f"sev_cal_{tag}.jsonl")


def lanes_exp(lo, hi):
    """도로 형태 R7(사전 고정 'R7'): TAGO_LANES=3 TAGO_DEMAND_SCALE=0.75 에서 기준선·단계·일률 80, 씨앗 lo~hi → results/r7_lanes{N}_{lo}-{hi}.jsonl"""
    assert LANES != 4 and DEMAND_SCALE != 1, "TAGO_LANES=3 TAGO_DEMAND_SCALE=0.75 를 정한다"
    pool_run([(cond_for(s), sc, False) for s in range(lo, hi + 1) for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80")],
             RES / f"r7_lanes{LANES}_{lo}-{hi}.jsonl")


def idm_design_exp(n=24):
    """모형 강건 권고 설계 C(사전 고정 'C'): TAGO_CF=IDM TAGO_DECEL=2.0 TAGO_TAU=0.4 에서 권고 변형 4개 → results/m1_idm_b2_design.jsonl"""
    assert CF_MODEL == "IDM" and CAR_DECEL != "4.5", "TAGO_CF=IDM TAGO_DECEL=2.0 TAGO_TAU=0.4 를 정한다"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1)
              for sc in ("official+tago12+relay-near", "official+tago12+relay-none", "official+tago12+relay-u80near", "official+tago12+relay-u80nl")],
             RES / "m1_idm_b2_design.jsonl")


def check_run():
    """최소 재현·회귀 확인: 씨앗 3 단계 방식 한 번을 돌려 v2 본 실험(results/v2_main.jsonl)의 같은 줄과 지표를 비교한다"""
    ref = next((json.loads(x) for x in (RES / "v2_main.jsonl").read_text(encoding="utf-8").splitlines()
                if x.strip() and json.loads(x)["seed"] == 3 and json.loads(x)["scheme"] == "official+tago12+relay"), None)
    r = run_one((cond_for(3), "official+tago12+relay", False))
    keys = ("conflicts", "fast", "severe", "fast1", "crashes", "arrived")
    print("이번:", {k: r[k] for k in keys})
    if ref:
        print("v2 본 실험:", {k: ref[k] for k in keys})
        print("같음" if all(r[k] == ref[k] for k in keys) else "다름!")
    (RES / "check_last.json").write_text(json.dumps({"run": {k: r[k] for k in keys}, "ref": {k: ref[k] for k in keys} if ref else None,
                                                     "env": {k: os.environ.get(k) for k in ("TAGO_STEP", "TAGO_TAU", "TAGO_TINC", "TAGO_GAWK", "TAGO_ATTN_P", "TAGO_CF")}},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")


def v2_exp(n):
    """수정 모형(v2, 사전 고정 docs/sim-preregistration.md 'v2'): TAGO_STEP=0.25 TAGO_TINC=900 TAGO_GAWK=... TAGO_ATTN_P=0.65"""
    tag = os.environ.get("TAGO_V2_TAG", "main")
    schemes = ("none", "official", "official_ai", "tago12", "official+tago12", "official+tago1.5+relay", "official+tago12+relay", "tago100") if tag == "main"         else ("official", "official+tago12+relay")
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in schemes], RES / f"v2_{tag}.jsonl")


def maincal_exp(n):
    """실측 보정 민감도: 사고 용량을 문헌 실측에 맞춘(TAGO_GAWK) 주요 방식 재실험 → results/main_cal.jsonl"""
    assert os.environ.get("TAGO_GAWK"), "TAGO_GAWK 를 정한다"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1)
              for sc in ("none", "official", "official_ai", "official+tago12", "official+tago12+relay", "tago100")], RES / "main_cal.jsonl")


E_SCHEMES = ("official", "official+tago12+relay", "official+tago12+relay-u80",
             "official+tago12+relay-sham", "official+tago12+relay-u80tail", "official+tago12+relay-u80right")


def e_runs_exp(n, out="e_main.jsonl"):
    """관점 확장 E2~E6(사전 고정 docs/sim-preregistration.md 'E1~E8'): 씨앗 1~n × 여섯 방식, 쌍 기록 포함 → results/e_main.jsonl"""
    assert not os.environ.get("TAGO_OFFICIAL_DELAY_FILE"), "e_runs 는 779 s 기준 — TAGO_OFFICIAL_DELAY_FILE 을 끈다(E1 은 e_delay)"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in E_SCHEMES], RES / out)


def e_delay_exp(n):
    """E1 모형 연결: 공식 안내 지연을 ITS–DB 실측 분포에서 씨앗마다 뽑아 기준선·단계·일률 80 → results/e_delay.jsonl"""
    fn = os.environ.setdefault("TAGO_OFFICIAL_DELAY_FILE", str(HERE / "data" / "its_registration_delay.json"))
    assert Path(fn).exists(), f"{fn} 이 없다(키 delay_s 리스트)"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in E_SCHEMES[:3]], RES / "e_delay.jsonl")


P_BASE = ("official", "official+tago12+relay", "official+tago12+relay-u80")


def p_main_exp(n=24):
    """검토 뒤 보강 P1·P3·P5·P6(c)·P7(사전 등록 'P1~P8'): TAGO_AGG=1 에서 기준선·단계·일률 80·u80right(씨앗 1~n), 사고 없는 none(false 경로),
    부분 준수 slack 세 방식 → results/p_main.jsonl"""
    assert AGG, "TAGO_AGG=1 로 집계를 켠다"
    schemes = P_BASE + ("official+tago12+relay-u80right",)
    slack = ("official-slack", "official+tago12+relay-slack", "official+tago12+relay-u80slack")
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in schemes] + [(cond_for(s), "none", True) for s in range(1, n + 1)]
             + [(cond_for(s), sc, False) for s in range(1, n + 1) for sc in slack], RES / "p_main.jsonl")


def p9_exp(n=24):
    """P9 확정 규칙 정정 재실행(맥): 씨앗 1~n × 기준선·단계·일률 80 × {정정 전, 정정 후(ov confirm_fix)} → results/p9_confirm.jsonl"""
    pool_run([(cond_for(s), sc, False, False, {"confirm_fix": True}) for s in range(1, n + 1) for sc in P_BASE]
             + [(cond_for(s), sc, False) for s in range(1, n + 1) for sc in P_BASE], RES / "p9_confirm.jsonl")


def p8_exp(n=24):
    """P8 국내 준수율: TAGO_COMPLY=0.64,0.73,0.82 에서 기준선·단계·일률 80 → results/p8_comply.jsonl"""
    assert os.environ.get("TAGO_COMPLY", "").startswith("0.64"), "TAGO_COMPLY=0.64,0.73,0.82 를 정한다"
    pool_run([(cond_for(s), sc, False) for s in range(1, n + 1) for sc in P_BASE], RES / "p8_comply.jsonl")


def e_delay2_exp(n=24, draws=(2, 3, 4)):
    """P4 E1 다중 추출: 공식 지연을 씨앗마다 추출 2~4 로 다시 뽑아 기준선·단계·일률 80 → results/e_delay2.jsonl"""
    fn = os.environ.setdefault("TAGO_OFFICIAL_DELAY_FILE", str(HERE / "data" / "its_registration_delay.json"))
    assert Path(fn).exists(), f"{fn} 이 없다(키 delay_s 리스트)"
    pool_run([(cond_for(s), sc, False, False, {"delay_draw": k}) for k in draws for s in range(1, n + 1) for sc in P_BASE], RES / "e_delay2.jsonl")


def p6_grid_exp(n=6):
    """P6(a) 준수율 × 보급률 격자(맥): 준수율 {5,25,45,65,85 %} × 보급 {1.5,12,50 %} × 단계·일률 80 + 준수율별 기준선, 씨앗 1~n → results/p6_grid.jsonl"""
    pen = {"1.5": ("official+tago1.5+relay", "official+tago1.5+relay-u80"), "12": ("official+tago12+relay", "official+tago12+relay-u80"),
           "50": ("official+tago50+relay", "official+tago50+relay-u80")}
    tasks = []
    for cp in (0.05, 0.25, 0.45, 0.65, 0.85):
        for s in range(1, n + 1):
            tasks.append((cond_for(s), "official", False, False, {"comply": cp}))
            for scs in pen.values():
                tasks += [(cond_for(s), sc, False, False, {"comply": cp}) for sc in scs]
    pool_run(tasks, RES / "p6_grid.jsonl")


def p6_lc_exp(n=12):
    """P6(b) 차로 변경 공격성(맥): lcAssertive {0.8, 1.6} × 기준선·단계·일률 80 × 씨앗 1~n → results/p6_lc.jsonl"""
    pool_run([(cond_for(s), sc, False, False, {"lc_assert": la}) for la in ("0.8", "1.6") for s in range(1, n + 1) for sc in P_BASE], RES / "p6_lc.jsonl")


def p_spacetime_exp(seed=23):
    """그림용(검토 C-3): v2 대표 씨앗(기준선 고속 접근 하위 중앙값 = 씨앗 23)의 기준선·단계·일률 80 을 그림 기록을 켜고 → results/p_spacetime.jsonl"""
    pool_run([(cond_for(seed), sc, False, True) for sc in P_BASE], RES / "p_spacetime.jsonl", procs=3)


def lhs_exp(n):
    """라틴 하이퍼큐브: 가정을 함께 흔들어 기준선 → 기준선+Tago20 감소율에 무엇이 가장 영향을 주나"""
    keys = [("demand", 5500, 7400), ("dur", 600, 5400), ("inatt", 0.06, 0.52), ("comply", 0.15, 0.85), ("tau", 0.3, 0.6), ("sigma", 0.2, 0.8), ("truck", 0.05, 0.25)]   # 조건 분포의 범위와 같게
    r = random.Random("lhs")
    cols = {k: r.sample([lo + (hi - lo) * (i + r.random()) / n for i in range(n)], n) for k, lo, hi in keys}
    tasks = []
    for i in range(n):
        c = cond_for(10000 + i)
        for k, _, _ in keys:
            c[k] = round(cols[k][i]) if k in ("demand", "dur") else round(cols[k][i], 3)
        c["blocked"] = 2 if i % 2 else 1
        c["rain"] = False
        for sc in ("official", "official+tago12", "official+tago12+relay"):
            tasks.append((c, sc, False))
    pool_run(tasks, RES / "lhs.jsonl")


def false_exp(n):
    seeds = range(1, n + 1)
    pool_run([(cond_for(s), sc, True) for s in seeds for sc in ("none", "tago12", "official+tago12+relay")], RES / "false.jsonl")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "calib"
    if cmd == "numcheck":                    # python tago_sim.py numcheck <이름>  (간격은 TAGO_STEP)
        pool_run([(cond_for(s), sc, False) for s in range(1, 9) for sc in ("official", "official+tago12+relay", "official+tago12+relay-u80")],
                 RES / f"num_{sys.argv[2]}.jsonl")
        sys.exit()
    if cmd == "d1":                          # python tago_sim.py d1
        d1_exp()
        sys.exit()
    if cmd == "d2":                          # python tago_sim.py d2
        d2_exp()
        sys.exit()
    if cmd == "m1":                          # TAGO_CF=IDM python tago_sim.py m1 [씨앗 수]
        m1_exp(int(sys.argv[2]) if len(sys.argv) > 2 else 24)
        sys.exit()
    if cmd == "idmdesign":                   # TAGO_CF=IDM TAGO_DECEL=2.0 TAGO_TAU=0.4 python tago_sim.py idmdesign [씨앗 수]
        idm_design_exp(int(sys.argv[2]) if len(sys.argv) > 2 else 24)
        sys.exit()
    if cmd == "lanes":                       # TAGO_LANES=3 TAGO_DEMAND_SCALE=0.75 python tago_sim.py lanes <lo> <hi>
        lanes_exp(int(sys.argv[2]), int(sys.argv[3]))
        sys.exit()
    if cmd == "sevcal":                      # TAGO_SEV=cal TAGO_UP=30000 TAGO_TINC=1200 python tago_sim.py sevcal [씨앗 수]
        sevcal_exp(int(sys.argv[2]) if len(sys.argv) > 2 else 24)
        sys.exit()
    if cmd == "e_runs":                      # python tago_sim.py e_runs [씨앗 수=24]  (v2 환경 변수와 함께)
        e_runs_exp(int(sys.argv[2]) if len(sys.argv) > 2 else 24, os.environ.get("TAGO_E_OUT", "e_main.jsonl"))
        sys.exit()
    if cmd == "e_delay":                     # TAGO_OFFICIAL_DELAY_FILE=data/its_registration_delay.json python tago_sim.py e_delay [씨앗 수=24]
        e_delay_exp(int(sys.argv[2]) if len(sys.argv) > 2 else 24)
        sys.exit()
    if cmd == "check":                       # python tago_sim.py check  (v2 환경 변수와 함께: 씨앗 3 단계 = v2 본 실험과 같아야 함)
        check_run()
        sys.exit()
    if cmd in ("p_main", "p8", "e_delay2", "p6grid", "p6lc", "p_spacetime", "p9"):   # 검토 뒤 보강 P1~P9(v2 환경 변수와 함께)
        fn = {"p_main": p_main_exp, "p8": p8_exp, "e_delay2": e_delay2_exp, "p6grid": p6_grid_exp, "p6lc": p6_lc_exp, "p_spacetime": p_spacetime_exp, "p9": p9_exp}[cmd]
        fn(int(sys.argv[2])) if len(sys.argv) > 2 else fn()
        sys.exit()
    if cmd == "j1":                          # python tago_sim.py j1
        j1_exp()
        sys.exit()
    if cmd == "confirm":                     # python tago_sim.py confirm 101 200
        confirm_exp(int(sys.argv[2]), int(sys.argv[3]))
        sys.exit()
    if cmd == "robust":                      # python tago_sim.py robust comply|design|attn [씨앗 수]
        robust_exp(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 24)
        sys.exit()
    arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if cmd == "calib":
        calib()
    elif cmd == "main":
        main_exp(arg or 24)
    elif cmd == "followup":
        followup_exp(arg or 24)
    elif cmd == "v2":
        v2_exp(arg or 24)
    elif cmd == "maincal":
        maincal_exp(arg or 24)
    elif cmd == "lhs":
        lhs_exp(arg or 64)
    elif cmd == "false":
        false_exp(arg or 24)
