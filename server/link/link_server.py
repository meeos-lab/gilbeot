"""Tago 도로 링크(차대차) 기준 엔진 + 중계 서버.

주행 중인 모든 Tago 차가 익명으로 연결된다. 앞차가 겪은 급제동·정체·사고 의심·폭우를 같은 길 뒤쪽 차에 알리고,
앞차들의 속도·와이퍼로 '앞길 미리보기'(10km, 500m 칸), 정체를 녹이는 권장 속도, 비 예보를 만든다.
가족 그룹은 선택 기능: 위험은 같은 도로 링크에서 오고, 그룹 차끼리는 이름·위치를 서로 보고 휴게소를 같이 정한다.
앱 내장 엔진(app/.../engine/LinkHub.kt)이 같은 규칙을 따르고, check_link_parity.py로 결과를 맞춘다.

- 시간은 요청에 실린 시각 t(초)만 쓴다(서버 시계 없음). 차들은 실제 시각(epoch 초)을 보낸다 → 두 엔진 결과가 같다
- 위치는 시연 경로(경부고속도로 하행) 위 거리 s(m). 웹 참가자는 위경도를 보내면 경로에 투영한다
- 모르는 차의 보고는 서로 다른 2대 이상이어야 알린다. 그룹 차의 보고는 1대로 바로(서로 위치 공유에 동의한 사이)
- 차량 ID·VIN·번호판은 받지 않는다. 차 id는 주행마다 새로 만든다

실행: python link_server.py  (기본 :8788, 에뮬레이터에서는 http://10.0.2.2:8788)
"""
import hmac
import json
import math
import os
import random
import re
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
PORT = int(os.environ.get("TAGO_LINK_PORT", "8788"))
ROUTE_FILE = json.loads((HERE / "gyeongbu_route.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 경로
LAT0 = sum(p[0] for p in ROUTE_FILE["route"]) / len(ROUTE_FILE["route"])
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 110540.0


def xy(lat, lon):
    return (lon * KX, lat * KY)


def r6(x):
    return math.floor(x * 1e6 + 0.5) / 1e6          # 앱 엔진과 같은 반올림(파이썬 round의 짝수 반올림을 쓰지 않는다)


def latlon(p):
    return [r6(p[1] / KY), r6(p[0] / KX)]


ROUTE = [xy(*p) for p in ROUTE_FILE["route"]]
CUM = [0.0]
for _a, _b in zip(ROUTE, ROUTE[1:]):
    CUM.append(CUM[-1] + math.hypot(_b[0] - _a[0], _b[1] - _a[1]))
LENGTH = CUM[-1]


def project(p):
    """점 → 경로 위 거리 s(m)"""
    return project_d(p)[0]


def project_d(p):
    """점 → (경로 위 거리 s, 경로까지 거리 d) — 경로 밖(다른 도로)의 공식 돌발을 거를 때 d 를 쓴다"""
    best, bs = math.inf, 0.0
    for i, (a, b) in enumerate(zip(ROUTE, ROUTE[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        d = math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
        if d < best:
            best, bs = d, CUM[i] + t * math.sqrt(L2)
    return bs, best


def point_at(s):
    s = max(0.0, min(LENGTH, s))
    for i in range(len(CUM) - 1):
        if CUM[i + 1] >= s:
            seg = CUM[i + 1] - CUM[i] or 1e-9
            t = (s - CUM[i]) / seg
            a, b = ROUTE[i], ROUTE[i + 1]
            return latlon((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return latlon(ROUTE[-1])


def _rest_areas():
    out = []
    for r in ROUTE_FILE["restAreas"]:
        if out and r["s"] - out[-1]["s"] < 300:          # 같은 휴게소가 두 번 들어간 것(OSM 중복) 정리
            continue
        name = r["name"].split("(")[0].strip()
        out.append({"name": name, "nameEn": (r.get("nameEn") or name).split("(")[0].strip(), "kind": r["kind"], "s": r["s"],
                    "lat": r["lat"], "lon": r["lon"]})
    return out


REST = _rest_areas()
# 휴게소(s) → 그 휴게소의 전기차 충전소 경로 위 위치들(fetch_ev_stations.py 가 경로 파일 evStations 에 넣은 공공데이터 좌표). 없으면 없음
EV_STATIONS = {}
CHG_STAT_IDS = {}                                # 휴게소(s) → 그 휴게소 충전소 id(공공데이터 statId) — 충전기 공식 상태를 휴게소에 모을 때
for _e in ROUTE_FILE.get("evStations", []):
    EV_STATIONS.setdefault(float(_e["rest"]), []).append(float(_e["s"]))
    CHG_STAT_IDS.setdefault(float(_e["rest"]), []).append(str(_e["statId"]))
# 구역(설계 10판 §8, build_zones.py): 사고 다발 구간(도로공사 사고 이력)·터널·교량(OSM). 경로 파일에 없으면 빈 목록
ZONES = ROUTE_FILE.get("zones", [])

# ---------------------------------------------------------------- 규칙
ALERT_RANGE = 10000.0        # 내 앞 10km 안의 위험만 알린다
MERGE_M = 1000.0             # 같은 종류가 1km 안이면 하나의 위험
ANON_CONFIRM = 2             # 모르는 차는 서로 다른 2대 이상이어야 확정
SLOW_MS = 8.3                # 30km/h 미만이 이어지면 정체
SLOW_HOLD = 20.0             # …20초 이상
FAST_MS = 16.7               # 60km/h를 넘으면 정체 해제
STOP_MS = 1.4                # 5km/h 미만 = 멈춤
INCIDENT_HOLD = 30.0         # 급제동 뒤 30초 넘게 멈춰 있으면 사고 의심
INCIDENT_NEAR = 300.0        # 급제동 지점 300m 안에서
TTL = {"HARD_BRAKE": 300, "CONGESTION": 120, "INCIDENT": 900, "HEAVY_RAIN": 600, "ICING": 900,
       "BLOCKED": 1200, "DEBRIS": 900, "SMOKE": 600, "DOWNHILL": 1800, "SIREN": 30, "CHARGER_FAULT": 3600, "CHARGER_WAIT": 3600}
MERGE = {"DEBRIS": 300.0, "SIREN": 3000.0, "CHARGER_FAULT": 500.0, "CHARGER_WAIT": 500.0}   # 종류별 묶는 거리(없으면 MERGE_M). 낙하물은 한 지점이라 좁게, 긴급차량은 움직이니 넓게
# 차가 보내는 신호 → 위험 종류. TURNBACK: 후진·되돌아감, SWERVE: 제동 없는 급조향, RECIRC_ON/OFF: 내기순환, BRAKE_HOLD: 브레이크 20초 이상
# RECIRC_OFF는 해제하지 않는다: 차는 터널을 나가며 바로 외기로 돌리지만 연기 보고는 10분(TTL) 동안 남아 뒤차 보고와 겹쳐 확인된다
# SIREN: 마이크가 사이렌을 듣는 동안 5초마다 보낸다(해제 신호 없음 — 마지막 보고 30초 뒤 사라진다)
# CHARGE_FAIL: 꽂았는데 충전이 안 됨(충전기 고장·결제 오류 의심), CHARGE_OK: 충전 시작(해제), CHARGE_START: 정차 뒤 오래 기다려 꽂음(충전 대기, 값 = 분)
EVENT_TYPE = {"TURNBACK": "BLOCKED", "SWERVE": "DEBRIS", "RECIRC_ON": "SMOKE", "RECIRC_OFF": "", "BRAKE_HOLD": "DOWNHILL",
              "CHARGE_FAIL": "CHARGER_FAULT", "CHARGE_OK": "CHARGER_FAULT_CLEARED", "CHARGE_START": "CHARGER_WAIT",
              "CHARGE_REPORT": "CHARGER_FAULT", "CHARGE_MOVED": "CHARGER_FAULT"}
ONE_SHOT = ("HARD_BRAKE", "SMOKE", "DEBRIS", "BLOCKED", "DOWNHILL", "SIREN", "CHARGER_WAIT")
# 충전 위험은 휴게소(충전기가 있는 곳)에 붙는다: 차 위치에서 500m 안의 휴게소가 없으면 버린다(고속도로 본선에서 꽂을 수 없다)
CHARGER = ("CHARGER_FAULT", "CHARGER_WAIT")
CHARGER_NEAR = 500.0
# 충전기 신고(운전자 1분 설문 CHARGE_REPORT)·자리 옮겨 충전(CHARGE_MOVED)·다른 차 충전 성공(CHARGE_SUCCESS). 앱 엔진(LinkHub.kt)과 같은 값
# 같은 자리 = 주차 한 칸 폭(주차장법 시행규칙 일반형 너비 2.5 m) 안. 그보다 멀리서 충전되면 '다른 기기'
CHARGE_SPOT_M = 2.5
# 충전소 반경: 공공데이터 충전소 좌표(충전소 단위 한 점, 휴게소마다 2~3곳)를 경로에 투영한 s 에서 이 안. 충전기 몇 대 묶음 + 위치 오차를 덮는 추정값(실측 아님). 휴게소 중심에서 충전소까지 경로 방향 −127~+89 m(2026-11-05 fetch_ev_stations.py). 좌표가 없는 휴게소는 CHARGER_NEAR
STATION_NEAR = 100.0
# 충전기 공식 상태(한국환경공단 충전소 정보 stat: 0 알수없음 1 통신이상 2 충전대기 3 충전중 4 운영중지 5 점검중 6 예약중 9 상태미확인 — OpenAPI 활용가이드 v1.25 3.2절).
# 4·5 만 '안 됨'으로 센다(1·9 는 통신 문제일 수 있어 세지 않는다). 받은 지 30분 넘은 상태는 버린다(근거 미기재 — 상태 조회 기간 최대 10분의 3배)
CHG_DOWN = (4, 5)
CHG_OFFICIAL_TTL = 1800.0
CHARGE_SYM = ("no_start", "screen_off", "payment", "connector", "notice")
SYM_KO = {"no_start": "충전 시작 안 됨", "screen_off": "화면 꺼짐", "payment": "결제 안 됨", "connector": "커넥터 파손", "notice": "'고장' 안내문"}
SYM_EN = {"no_start": "won't start", "screen_off": "screen off", "payment": "payment fails", "connector": "damaged connector", "notice": "out-of-order sign"}
PLACE_KO = {"entrance": "입구 쪽", "middle": "가운데", "end": "끝 쪽"}
PLACE_EN = {"entrance": "near the entrance", "middle": "in the middle", "end": "at the far end"}
BROKEN = ("1", "2", "3", "all")
BROKEN_KO = {"1": "1대 고장", "2": "2대 고장", "3": "3대 이상 고장", "all": "전부 고장"}
BROKEN_EN = {"1": "1 down", "2": "2 down", "3": "3+ down", "all": "all down"}
# 사고 판단(docs/incident-judgment-design.md 10판 10-1·10-2): 한 차의 60 s·300 m 사건 창에 근거를 더한다. 앱 엔진(LinkHub.kt)과 같은 값
INC_POINTS = {"HARD_BRAKE": 1, "SWERVE": 1, "IMPACT": 3, "STOP": 2, "AIRBAG": 3, "COMM_LOSS": 2, "NO_RESPONSE": 2}
INC_ORDER = ["SWERVE", "HARD_BRAKE", "IMPACT", "STOP", "AIRBAG", "COMM_LOSS", "NO_RESPONSE"]   # 근거 읽는 순서
INC_HARD = ("STOP", "IMPACT", "AIRBAG", "COMM_LOSS")   # 이 중 하나는 있어야 사고 의심(급제동+급조향만으로는 아니다)
INC_WINDOW, INC_NEAR = 60.0, 300.0
INC_MIN, INC_STRONG = 3, 6                   # 사고 의심 문턱 / 2단계·모르는 차 1대 확정 문턱
COMM_LOSS, COMM_AFTER = 8.0, 15.0            # 충돌 뒤 15 s 안의 보고를 끝으로 8 s 넘게 무응답 = 통신 끊김
STRONG_SESSION, STRONG_GAP = 120.0, 1800.0   # 모르는 차 1대 확정: 세션 2분 이상, 차마다 30분에 한 번
CLEAR_PASS = 3                               # 다른 차 3대가 60 km/h 넘게 지나가면 해제, 1~2대면 '일부 차로 통행'
IMPACT_A, IMPACT_DV, IMPACT_DT_MIN, IMPACT_DT_MAX, IMPACT_HOLD = 14.0, 2.2, 0.08, 0.5, 0.5   # 충돌 재검증(차와 같은 규칙)
# 공식 돌발 정보(설계 10판 §8·10-3): 순정 내비 TrafficStatus.trafficEventList 를 차가 올린다(/api/road/official).
# 사고 의심 ±2 km 에 공식 사고가 있으면 2단계 '공식 확인'(문장이 바뀐다), 공식 endTime 이 지나면 사고 의심도 거둔다.
# 사고 의심이 없는 공식 돌발은 화면에만(순정 내비가 이미 말한다 — 같은 지점·시간의 안내는 한 번만)
# 구역(③): 다발 구간 1.5 km 앞에서 한 번, 교량은 외기 4 °C 이하일 때만 결빙 주의, 다발 구간 ±300 m 의 사고 의심은 문장에 맥락,
# 터널 ±200 m 안에서 끊긴 보고는 '사고로 인한 통신 끊김'으로 세지 않는다(터널은 원래 끊긴다)
ZONE_SAY, ZONE_NEAR, TUNNEL_MARGIN, ICE_TEMP = 1500.0, 300.0, 200.0, 4.0
# 사고 위험성(④, 설계 §6-2): 지금 이 차·이 길·이 날씨의 점수(0~10). 허브는 환경·도로 묶음만, 차가 운전 묶음(과속·잦은 급제동·피로)을 더한다
RISK_PTS = {"AHEAD": 3, "ICE": 2, "ICE_HARD": 3, "ZONE": 2, "RAIN": 2, "TUNNEL": 1, "NIGHT": 1, "DEBRIS": 1}
RISK_ORDER = ["AHEAD", "ICE", "ZONE", "RAIN", "TUNNEL", "NIGHT", "DEBRIS"]
RISK_CAUTION, RISK_HIGH = 3, 6              # 주의 3~5 · 높음 6↑
RISK_AHEAD, RISK_NEAR = 3000.0, 1000.0       # 앞 3 km 사고 의심·정체 꼬리 / 1 km 안 구역·낙하물
KST = 9 * 3600                               # 시연 경로는 국내 — 야간 20~6시, 새벽 0~7시(결빙)
OFFICIAL_TYPES = ("ACCIDENT", "ROAD_DAMAGE", "DISASTER")
OFFICIAL_NEAR, OFFICIAL_MERGE, OFFICIAL_OFFROUTE, OFFICIAL_TTL = 2000.0, 300.0, 1000.0, 1800.0   # 교차 확인 거리 / 같은 사건 묶기 / 경로 밖 버림 / endTime 없을 때 만료
OFFICIAL_KO = {"ACCIDENT": "사고", "ROAD_DAMAGE": "도로 파손", "DISASTER": "재난"}
OFFICIAL_EN = {"ACCIDENT": "crash", "ROAD_DAMAGE": "road damage", "DISASTER": "disaster"}
OFFICIAL_CAUSE = {"ACCIDENT": 2, "ROAD_DAMAGE": 9, "DISASTER": 99}   # DENM causeCode: accident / hazardousLocation-SurfaceCondition / dangerousSituation
DESC_MAX = 40
INC_KO = {"SWERVE": "급조향", "HARD_BRAKE": "급제동", "IMPACT": "충돌", "STOP": "정차", "AIRBAG": "에어백 전개", "COMM_LOSS": "통신 끊김", "NO_RESPONSE": "응답 없음"}
INC_EN = {"SWERVE": "swerved", "HARD_BRAKE": "braked hard", "IMPACT": "crash-level deceleration", "STOP": "stopped", "AIRBAG": "airbag deployed",
          "COMM_LOSS": "lost contact", "NO_RESPONSE": "no response"}
CAUSE_CODE = {"INCIDENT": 2, "CONGESTION": 1, "SIREN": 95, "BLOCKED": 2}   # ETSI DENM causeCode 대응(교통 막힘 주의 = dangerousEndOfQueue 27 은 플래그)   # 한 번 보고하고 끝나는 종류('활성'에 두지 않는다)
# 긴급차량(사이렌): 뒤에서 다가오는 움직이는 위험. 차마다 처음 들은 때·곳(onset)을 이어 긴급차량의 위치·속도를 짐작한다
SIREN_RANGE = 2000.0         # 내 뒤 2km 안에서 다가올 때만 알린다
SIREN_NEAR = 500.0           # 500m 안이면 한 번 더 말한다
SIREN_TRACK = 60.0           # 최근 60초의 onset으로 속도를 잰다
SIREN_MIN_DT = 3.0           # onset 두 개가 3초 이상 떨어져야 방향을 안다(반대 차로 긴급차량은 거꾸로 움직여 걸러진다)
SIREN_EXTRAP = 15.0          # 마지막 onset 뒤 최대 15초까지 속도로 앞으로 민다
SIREN_ETA_MAX = 90.0         # 통과 예상 시간은 90초 안일 때만 말한다
# 긴급차량 위치 신호(비컨, docs/dev/40-algorithms.md A-13): 구급차가 kind "ev" + 토큰으로 도로 링크에 들어와 위치·속도·목적지(dest_s)·출동 여부(on)를 보낸다.
# 허브는 그 차에 묶인 SIREN 위험 하나를 두고(위치 = 비컨, 바로 확정, 정보 품질 7), 3 km 안의 마이크 보고는 같은 위험의 근거로 더한다
EV_TOKEN = os.environ.get("TAGO_EV_TOKEN", "meeos-ev-demo")   # 시연용 토큰(운영은 기관 인증서로 바꾼다). 틀리면 403
EV_RANGE = 5000.0            # 위치가 정확하므로(마이크 추정은 청취 반경 300 m·처음 들은 곳 오차) 뒤 5 km 까지 알린다 — 그 너머는 사이 나들목에서 빠질 수 있다(이 1차원 모델은 나들목을 모른다)
EV_TRACK = 10.0              # 비컨 속도: 최근 10초 위치로 잰다(GPS 1초 흔들림을 덜 탄다)
EV_MOVE = 2.0                # 경로 위 속도가 ±2 m/s 를 넘어야 앞으로/거꾸로 달린다고 본다(멈춘 비컨의 흔들림은 말하지 않는다)
EV_STALE = 15.0              # 15초 넘게 소식 없는 비컨은 꺼진 것으로 본다
EV_DEST_MARGIN = 300.0       # 목적지(dest_s)를 300 m 넘게 지난 차에는 알리지 않는다(예상 경로 밖)
EV_ETA_MIN_MAX = 600.0       # 비컨: 90초 넘는 통과 예상은 10분 안일 때만 분으로 말한다
# 길 터 주기 물결(A-13b): 차가 시속 30 이상에서 급히 줄이며 오른쪽으로 비키면 YIELD 를 보낸다. 서로 다른 차 2대 이상의 YIELD 지점이
# 60초 안에 교통 흐름(그 차들의 경로 위 속도 평균)보다 5 m/s 넘게 빨리 앞으로 옮겨 가면 뒤에 긴급차량이 있다고 본다
YIELD_WINDOW = 60.0
YIELD_MIN = 2                # 물결로 보는 최소 차 수
YIELD_CONFIRM = 3            # 물결만으로 확정하려면 3대(마이크·비컨과 함께면 2대)
YIELD_FAST = 5.0             # 물결 속도 - 교통 흐름 > 5 m/s(경로 위 속도 — 시연은 DEMO_SCALE 배 압축된 거리)
YIELD_NEAR = 150.0           # 시연: 구급차가 150 m 뒤로 다가오면 시연 차가 비킨다(YIELD)
EMS_ALL = ("beacon", "mic", "yield")   # 시연 구급차가 내는 근거(시연 호출 ems: "all" 또는 "mic"·"beacon"·"yield" 를 쉼표로)
RAIN_NEAR = 6000.0           # 되돌아가는 차 지점 6km 안에 확인된 폭우(비 시작 지점)가 있으면 '침수 의심'
STICKY = ("CONGESTION", "HEAVY_RAIN", "ICING", "INCIDENT", "CHARGER_FAULT")   # 보고 차가 해제할 때까지 남는 종류
LEVEL_UP = ("INCIDENT", "HARD_BRAKE", "BLOCKED")            # 차 3대 이상 확인되면 한 번 더 말하는 종류(나머지는 한 번만 — 소리를 줄인다)
CRUISE_MS = 25.0             # 간격을 분으로 말할 때 기준 속도(90km/h)
REST_AHEAD = 1000.0          # 다같이 휴게소: 가장 앞선 차보다 1km 이상 앞의 휴게소
ACTIVE_SEC = 60.0            # 이 시간 안에 보고한 차만 '주변 차'로 센다
CLOCK_SKEW_SEC = 30.0        # 요청 t 가 '허브 시각 + 그 뒤 실제 경과'와 이보다 크게 어긋나면 그 차의 시계가 틀린 것: 창(window)엔 수신 시각을 쓰고 보기에 clockSkew(ADR-43)
LIMIT_MAX = 200              # 차가 1 s 상태에 실은 제한속도(km/h, 순정 내비)로 받는 상한 — 0 이하·초과는 모름(ADR-44)
MI_M = 1609.344              # 영어 거리 글의 마일(지역 단위 "mi" — 어바인, ADR-45)
FT_M = 0.3048                # …피트
MI_FT_MAX = 0.5              # 이 마일 미만은 100 ft 단위로
UNITS = ("km", "mi")         # join 의 units 로 받는 값(그 밖·없음은 km)
BIN_M, BINS = 500.0, 20      # 앞길 미리보기: 500m 칸 20개(10km)
JAM_KMH = 40                 # 칸 평균이 이보다 느리고 차가 2대 이상이면 정체 칸
ADVISE_KMH = 80              # 정체 꼬리 권장 속도는 거리와 무관하게 80 하나(docs/sim-report.md 3.10: 단계 감속은 고속 접근 상충을 늘렸다)
PULSE_SEC = 8.0              # 관제 화면: 최근 8초의 보고를 '신호'로 보여 준다
MAX_STEPS = 600              # 시연 도로를 한 번에 돌리는 최대 걸음(초)
GONE_SEC = 300.0             # 5분(ACTIVE_SEC의 5배) 넘게 소식 없는 차: 남아 있는 보고(정체·폭우 등)를 거둔다. 차가 꽉 차면 도로에서 뺀다
MAX_CARS = 200               # 도로 위 차는 200대까지(시연은 30대 안팎) — 넘치면 소식 없는 차부터 빼고, 그래도 꽉 차면 새 차를 받지 않는다
GROUP_MAX = 50               # 그룹은 50개까지 — 넘치면 가장 오래된 그룹과 코드를 지운다
CODE_TTL = 1800.0            # 참가 코드는 만든 뒤 30분까지만 받는다(그룹은 그대로, 이미 합류한 사람은 그대로)
JOIN_TRIES, JOIN_LOCK = 5, 60.0   # 같은 차가 코드를 5번 틀리면 60초 동안 받지 않는다(차 id 없는 휴대폰 참가는 한 칸을 같이 쓴다)
CODE_WRONG_MAX = 20          # 코드가 살아 있는 동안 도로 전체에서 20번 틀리면 그 코드는 닫는다(4자리 코드를 차례로 넣어 맞히지 못하게)
NAME_MAX, CAR_MAX, KIND_MAX = 20, 40, 12   # 사람이 적는 이름·차 설명 글자 수(제어 문자는 뺀다)

PRIORITY = {"OFFICIAL": 0, "SIREN": -1, "INCIDENT": 0, "BLOCKED": 1, "HARD_BRAKE": 2, "DEBRIS": 3, "ICING": 4, "SMOKE": 5, "DOWNHILL": 6, "CONGESTION": 7,
            "HEAVY_RAIN": 8, "CHARGER_FAULT": 9, "CHARGER_WAIT": 10}   # 같은 곳이면 앞의 것만 말한다. 긴급차량 양보가 가장 먼저
TYPE_KO = {"OFFICIAL": "도로 정보", "HARD_BRAKE": "급제동", "CONGESTION": "정체", "INCIDENT": "사고 의심", "HEAVY_RAIN": "폭우", "ICING": "결빙 위험",
           "BLOCKED": "길 막힘 의심", "DEBRIS": "낙하물 의심", "SMOKE": "연기·매연", "DOWNHILL": "긴 내리막", "SIREN": "긴급차량",
           "CHARGER_FAULT": "충전기 고장 의심", "CHARGER_WAIT": "충전 대기"}
TYPE_EN = {"OFFICIAL": "road info", "HARD_BRAKE": "hard braking", "CONGESTION": "slow traffic", "INCIDENT": "a possible crash", "HEAVY_RAIN": "heavy rain",
           "ICING": "possible ice", "BLOCKED": "a possible road block", "DEBRIS": "possible debris", "SMOKE": "smoke or fumes",
           "DOWNHILL": "a long downhill", "SIREN": "an emergency vehicle", "CHARGER_FAULT": "a possible charger fault",
           "CHARGER_WAIT": "a charging queue"}


def L(lang, ko, en):
    return en if lang == "en" else ko


def r1(x):
    return math.floor(x * 10 + 0.5) / 10


def rnd(x):
    return int(math.floor(x + 0.5))


def ms(x):
    """시각을 0.001 s 로(DENM TimestampIts 의 단위). 앱 엔진과 같은 반올림"""
    return math.floor(x * 1000 + 0.5) / 1000


# ---------------------------------------------------------------- 프로토콜(51 §1.1·§10, ADR-41)
# 버전: 허브가 만든 모든 응답에 싣는다. 필드를 더하는 호환 변경은 같은 값, 옛 받는 쪽이 깨지는 변경은 /2 로 올린다
API = "gilbeot-road/1"
# 요청 스키마(server/link/schema/*.schema.json, JSON Schema 2020-12). 두 엔진이 같은 파일을 읽어 같은 규칙으로 검사한다(앱은 Java 리소스로 넣는다)
SCHEMA_DIR = HERE / "schema"
REQ_SCHEMA = {"POST reset": "road-reset.request", "POST join": "road-join.request", "POST state": "road-state.request",
              "POST event": "road-event.request", "POST respond": "road-respond.request", "POST official": "road-official.request",
              "POST demo": "road-demo.request", "GET ": "road-view.query", "GET world": "road-view.query"}
SCHEMAS = {n: json.loads((SCHEMA_DIR / f"{n}.schema.json").read_text(encoding="utf-8")) for n in sorted(set(REQ_SCHEMA.values()))}
# DENM(ETSI EN 302 637-3) 대응 필드: 위험이 알려지는 반경(RelevanceDistance 열거 0~7, 이 거리 이하면 그 이름), 유효 시간 상한(ValidityDuration 0..86400)
RELEVANCE = ((50.0, "lessThan50m"), (100.0, "lessThan100m"), (200.0, "lessThan200m"), (500.0, "lessThan500m"),
             (1000.0, "lessThan1000m"), (5000.0, "lessThan5km"), (10000.0, "lessThan10km"))
RELEVANCE_OVER = "over10km"
DENM_VALIDITY_MAX = 86400
# 오류 응답: RFC 9457 Problem Details(type·title·status·detail·instance) + 확장 error(옛 키, 그대로)·field·rule·retryAfter
PROBLEM_TYPE = "urn:meeos:gilbeot-road:problem:"
PROBLEM_MEDIA = "application/problem+json; charset=utf-8"
PROBLEM_TITLE = {"schema": "Request does not match the schema", "token": "Emergency-vehicle token rejected", "not found": "Not found",
                 "car": "Unknown car", "code": "Unknown or expired join code", "locked": "Too many wrong join codes", "full": "Capacity reached"}


def problem(code, obj, method, path):
    """허브 오류 객체에 RFC 9457 필드를 더한다(옛 error 키는 남긴다). LinkHub.problem 과 같은 글"""
    err = obj["error"]
    detail = {"schema": f"{obj.get('field') or '(body)'}: {obj.get('rule')}", "token": "kind \"ev\" needs a valid token",
              "not found": f"no handler for {method} {path}", "car": "join the road first (unknown me)",
              "code": "join code is wrong or expired", "locked": f"retry after {obj.get('retryAfter')} s", "full": "road or group is full"}.get(err, err)
    return {**obj, "type": PROBLEM_TYPE + err.replace(" ", "-"), "title": PROBLEM_TITLE.get(err, err), "status": code, "detail": detail, "instance": path}


def response_headers(code, obj):
    """응답 헤더(Content-Type·Retry-After) — 허브 오류(type 있음)는 problem+json, 429 는 Retry-After = retryAfter 초"""
    h = {"Content-Type": PROBLEM_MEDIA if isinstance(obj, dict) and "type" in obj else "application/json; charset=utf-8"}
    if isinstance(obj, dict) and obj.get("retryAfter") is not None:
        h["Retry-After"] = str(obj["retryAfter"])
    return h


def relevance(m):
    return next((name for d, name in RELEVANCE if m <= d), RELEVANCE_OVER)


def _jtype(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return {str: "string", list: "array", dict: "object"}.get(type(v), "?")


def _at(path, k):
    return f"{path}.{k}" if path else k


def schema_error(sch, v, path=""):
    """요청 스키마로 v 를 본다 → 처음 어긋난 (경로, 키워드) 또는 None. 쓰는 키워드는 JSON Schema 2020-12 의 일부
    (type·required·properties·items·minimum·maximum·minLength·maxLength·pattern·minItems·maxItems — schema/check_schemas.py 가 그 밖을 막는다).
    순서: type → 숫자 범위 → 글(길이는 코드 포인트, pattern 은 전체 일치) → 배열(개수 → 원소 차례) → 객체(required 차례 → properties 이름순).
    LinkHub.schemaError 와 같다"""
    types = sch.get("type")
    if types is not None and _jtype(v) not in ([types] if isinstance(types, str) else types):
        return path, "type"
    t = _jtype(v)
    if t == "number":
        if "minimum" in sch and v < sch["minimum"]:
            return path, "minimum"
        if "maximum" in sch and v > sch["maximum"]:
            return path, "maximum"
    elif t == "string":
        if "minLength" in sch and len(v) < sch["minLength"]:
            return path, "minLength"
        if "maxLength" in sch and len(v) > sch["maxLength"]:
            return path, "maxLength"
        if "pattern" in sch and not re.fullmatch(sch["pattern"], v):
            return path, "pattern"
    elif t == "array":
        if "minItems" in sch and len(v) < sch["minItems"]:
            return path, "minItems"
        if "maxItems" in sch and len(v) > sch["maxItems"]:
            return path, "maxItems"
        if "items" in sch:
            for i, x in enumerate(v):
                e = schema_error(sch["items"], x, f"{path}[{i}]")
                if e:
                    return e
    elif t == "object":
        for k in sch.get("required", ()):
            if k not in v:
                return _at(path, k), "required"
        props = sch.get("properties", {})
        for k in sorted(props):
            if k in v:
                e = schema_error(props[k], v[k], _at(path, k))
                if e:
                    return e
    return None


def dist_text(lang, m, units="km"):
    """거리 글. 한국어는 늘 m·km, 영어는 그 차의 지역 단위(km, 또는 mi·ft — 어바인). LinkHub.distText 와 같은 글"""
    if lang != "en" or units != "mi":
        if m < 950:
            return L(lang, f"{rnd(m / 100) * 100}m", f"{rnd(m / 100) * 100} m")
        return L(lang, f"{r1(m / 1000)}km", f"{r1(m / 1000)} km")
    mi = m / MI_M
    if mi < MI_FT_MAX:
        return f"{rnd(m / FT_M / 100) * 100} ft"
    return f"{r1(mi)} mi"


def units_of(x):
    return x if x in UNITS else "km"


def has_final(word):
    c = word[-1] if word else ""
    return "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 != 0


def josa(word, a, b):
    return word + (a if has_final(word) else b)


def clean(x, n):
    """사람이 적은 글: 제어 문자(줄바꿈·방향 바꾸기·짝 없는 대리 문자 등)를 빼고 앞뒤 공백을 지운 뒤 n자까지(앱 엔진과 같은 규칙)"""
    s = "".join(ch for ch in str(x) if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Zl", "Zp")).strip()
    return s[:n].strip()


def lang_of(x):
    return "en" if x == "en" else "ko"


# ---------------------------------------------------------------- 시연 도로(설 연휴 귀성, 경부고속도로 하행)
# 앞쪽에서 사고(차 2대 멈춤) → 그 뒤로 1.5km 정체 → 더 앞에는 비 구간. 모르는 Tago 차 14대가 이 도로를 1초 단위로 달린다.
# 거리는 시연을 시작한 차의 위치 s0 기준, 시간은 시작 시각 t0 기준. 경로 위 이동은 DEMO_SCALE배로 압축한다
DEMO_SCALE = 4.0
JAM_TAIL, JAM_HEAD = 5000.0, 6500.0   # 정체 구간(꼬리, 머리) — 앱 LinkHub 와 같은 이름
JAM_MS = 4.0                 # 정체 안 속도(14km/h)
JAM_END = 150                # 시작 150초 뒤 정체가 풀린다
CRASH_END = 110              # 사고 차 2대가 멈춰 있는 시간
RAIN_FROM, RAIN_TO = 9000.0, 22000.0   # 비 구간
DEBRIS_S = 3000.0            # 낙하물: 지나는 차가 핸들을 급히 꺾는다
DOWNHILL_FROM, DOWNHILL_TO = 7000.0, 9500.0   # 긴 내리막: 지나는 차가 브레이크를 오래 밟는다
TUNNEL_FROM, TUNNEL_TO = 12000.0, 12600.0   # 터널: 지나는 차가 내기순환으로 바꾼다(연기)
TURNBACK_S = 14500.0         # 침수: 여기 닿은 차는 되돌아간다(비 구간 안)
BRAKE_HOLD_SEC = 20
BRAKE_ENTRIES = 0            # 정체 꼬리에서 급제동으로 보고하는 차 수(0: 정체는 권장 속도로 알린다 — 같은 내용을 두 번 말하지 않게)
# (종류, 시작 위치, 자유 주행 속도 m/s). crash = 사고 차(정체 머리에 멈춰 있다)
DEMO_CARS = [("anon", -2500, 24.0), ("anon", -1200, 25.5), ("anon", 1500, 23.5), ("anon", 2600, 26.0), ("anon", 3700, 24.5),
             ("anon", 4600, 25.0), ("anon", 5300, 24.0), ("anon", 5800, 25.0), ("anon", 6200, 24.0), ("crash", 6400, 0.0),
             ("crash", 6420, 0.0), ("anon", 7600, 25.0), ("anon", 9600, 24.5), ("anon", 11500, 25.0)]
# 가족 그룹 시연(선택): 삼촌은 앞에서 같은 길(정체에 걸린다), 이모는 뒤
DEMO_FAMILY = [("삼촌", "Uncle", "아반떼 · 흰색", "white Avante", 3000.0, 25.0, 41), ("이모", "Aunt", "쏘렌토 · 검정", "black Sorento", -1500.0, 24.0, None)]
# 구급차: AMB_K초에 정체 꼬리 뒤에서 나타나 사고 지점으로 간다. 근처(HEAR_M) Tago 차의 마이크가 사이렌을 듣고 5초마다 보고한다.
# 같이 나타나는 모르는 Tago 차 5대가 구급차 바로 앞을 달린다(처음 듣는 차들). 사고 지점에 닿으면 사이렌을 끈다
AMB_K = 50
AMB_OFF = 500.0              # 시작 위치(시연 시작 지점 기준)
AMB_MS, AMB_JAM_MS = 33.0, 14.0   # 120km/h, 정체 안에서는 50km/h(차들이 비켜 준다)
AMB_STOP = 6360.0            # 사고 차(6400) 바로 뒤에 선다
AMB_WITNESS = [(250.0, 24.0), (700.0, 24.0), (1150.0, 24.0), (1600.0, 24.0), (2050.0, 24.0)]   # (구급차 기준 위치, 자유 주행 속도)
HEAR_M = 300.0               # 차 안 마이크가 사이렌을 듣는 거리
SIREN_EVERY = 5              # 듣는 동안 보고 간격(초)
YIELD_M = 250.0              # 관제 화면: 구급차 앞 250m 안의 차는 비켜 선다
# 여정(가족 그룹): 네 가지를 나눠 담는다 — 차량 관측(타고 있는 차의 위치·속도·정차와 관측 시각), 사람의 선택(제안·수락·확인),
# 장소 조건(쉬어 갈 휴게소와 근거), 서비스 판단(제안과 그 이유). 휴게소 제안과 다음 한 단계 카드는 같은 '할 일(act)' 형식이다:
# 제안(proposed)·대기(pending) → 끝(done) 또는 취소(cancelled). 끝났을 때는 차 관측으로 끝났는지(vehicle) 사람이 확인했는지(person)를 남긴다
# 다음 한 단계 카드: board·rest·arrive는 타고 있는 차의 관측으로 서버가 넘기고, task(사람이 하는 일)는 누군가 '했어요'를 눌러야 끝난다
STEP_KINDS = ("board", "rest", "arrive", "task")
STEP_MAX, STEP_LABEL_MAX = 6, 24
NEAR_STOP = 800.0            # 휴게소 800m 안에서 멈추면 그곳에 섰다고 본다
ARRIVE_NEAR = 500.0          # 경로 끝 500m 안에서 멈추면 도착
MOVE_MS = 10 / 3.6           # 시속 10km를 넘으면 출발
BASIS = {"lead_1km": ("가장 앞선 일행도 1km 이상 남은 다음 휴게소", "Next rest area at least 1 km past the lead car"),
         "agreed": ("일행이 정한 휴게소", "The rest area the group chose"),
         "next": ("타고 있는 차 앞의 다음 휴게소", "The next rest area ahead of the car")}


# ---------------------------------------------------------------- 허브
class Hub:
    def __init__(self, rng=None):
        self.rng = rng or random.SystemRandom()      # 차 id·그룹 id·코드는 맞힐 수 없게(운영체제 난수)
        self.reset()

    def reset(self, clock_guard=True):
        """도로를 비운다(시연을 처음부터 다시, 시험용). clock_guard=False 는 시계 오차 가드를 끈다 — 논리 시각을 건너뛰는 대조 대본용(check_link_parity run·run_ev·run_schema)"""
        self.clock_guard = clock_guard
        self.cars = []               # 도로 위 모든 차(익명). 그룹 참가자도 여기
        self.hazards = []
        self.official = []           # 공식 돌발 정보(순정 내비가 준 것을 차가 올림): {id, type, s, end, desc, t, first, by}
        self.chg_official = {}       # 충전기 공식 상태: 충전소 id → {"t": 받은 시각, "chargers": {충전기 id: 상태 코드}} (/api/road/chargerstatus)
        self.pulses = []             # 관제 화면용 최근 보고(시각, 위치, 종류)
        self.groups = {}
        self.codes = {}
        self.tries = {}              # 코드 틀린 횟수: 차 id(휴대폰 참가는 "") → {"n", "until"}
        self.now = 0.0
        self.anchor = None           # (허브 now, 그 now 를 정한 실제 시각) — 시계 오차 가드(clock)
        self.cur_units = "km"        # 지금 보기(view)를 만드는 차의 거리 단위(km·mi) — km_text 가 읽는다
        self.seq = 0
        self.demo = None             # {"t0", "s0", "k", "entries", "amb", "ems"}
        self.yields = []             # 아직 위험에 붙지 않은 YIELD: (t, s, 경로 위 속도, 차 id)
        self.ev_token = EV_TOKEN

    def _id(self, n, chars="0123456789abcdef"):
        return "".join(self.rng.choice(chars) for _ in range(n))

    def car(self, cid):
        return next((c for c in self.cars if c["id"] == cid), None)

    def _new_car(self, name, desc, kind, lang, demo=None):
        """차 id는 그 차의 열쇠다(이 id로 위치·보고를 보낸다) — 맞힐 수 없게 만들고 본인에게만 준다. 남에게는 pub(보기용 이름표)만 보인다"""
        if len(self.cars) >= MAX_CARS:
            self._purge()
            if len(self.cars) >= MAX_CARS:
                return None
        cid, pub = "c" + self._id(12), "v" + self._id(8)
        while self.car(cid):
            cid = "c" + self._id(12)
        while any(x["pub"] == pub for x in self.cars):
            pub = "v" + self._id(8)
        c = {"id": cid, "pub": pub, "name": name, "car": desc, "kind": kind, "lang": lang, "s": None, "speed": 0.0, "soc": None,
             "wiper": "", "temp": None, "t": self.now, "slowSince": None, "stopSince": None, "brake": None, "active": set(),
             "demo": demo, "group": None, "holdSince": None, "gone": False, "st": None, "vs": None, "sirenAt": None,
             "inc": None, "joinT": self.now, "strongAt": None, "strongH": None,
             "on": False, "dest": None, "bt": [], "yieldAt": None,   # on·dest·bt: 긴급차량(kind "ev") 출동 여부·목적지·최근 위치, yieldAt: 시연 차가 비킨 시각
             "units": "km", "limit": None, "skew": None}             # units: 거리 단위(join), limit: 순정 내비 제한속도 km/h, skew: 시계 오차(초, 없으면 None)
        self.cars.append(c)
        return c

    def km_text(self, lang, m):
        """보기를 만드는 차의 지역 단위로(view 가 cur_units 를 정한다)"""
        return dist_text(lang, m, self.cur_units)

    def _pid(self, c, mid):
        """밖으로 내보내는 차 id: 나에게는 내 id, 남의 차는 보기용 이름표(pub) — 남의 id로 위치·보고를 보낼 수 없게"""
        return c["id"] if c["id"] == mid else c["pub"]

    def _expiry(self, h):
        """허브가 이 위험을 지우는 시각 — 더 들은 소식이 없을 때(clock 의 만료 규칙과 같다). 해제 전까지 남는 종류(STICKY)는
        보고한 차가 모두 GONE_SEC 동안 조용해지는 때, 그 밖은 마지막 보고(또는 해제) + 종류별 TTL"""
        if h["type"] in STICKY and h["cleared"] is None and h["reporters"]:
            seen = [max(c["t"], at) for c, at in ((self.car(r), at) for r, at in h["reporters"].items()) if c is not None]
            return max(seen) + GONE_SEC if seen else self.now
        return (h["cleared"] if h["cleared"] is not None else h["last"]) + TTL[h["type"]]

    @staticmethod
    def _official_expiry(o):
        """공식 돌발이 지워지는 시각: endTime 과 마지막으로 받은 뒤 OFFICIAL_TTL 중 이른 쪽"""
        ttl = o["t"] + OFFICIAL_TTL
        return ttl if o["end"] is None else min(o["end"], ttl)

    @staticmethod
    def _denm(item, detected, expires, reach):
        """DENM(ETSI EN 302 637-3) 관리 컨테이너에 대응하는 필드를 위험 항목에 더한다(51 §10, 40 A-24).
        detectionTime = 가장 최근 감지 시각 t, validityDuration = 그때부터 만료까지 초(표준과 같이 detectionTime 기준),
        eventPosition = 경로상 거리 + 그 자리 위경도, relevanceDistance = 허브가 이 위험을 알리는 반경의 열거 이름"""
        item["detectionTime"] = ms(detected)
        item["validityDuration"] = max(0, min(DENM_VALIDITY_MAX, rnd(expires - detected)))
        item["eventPosition"] = {"s": item["s"], "lat": item["pos"][0], "lon": item["pos"][1]}
        item["relevanceDistance"] = relevance(reach)

    def _alive(self, cid, at):
        """보고한 차가 아직 도로에 있다: 마지막 상태나 그 보고가 GONE_SEC 안"""
        c = self.car(cid)
        return c is not None and self.now - max(c["t"], at) < GONE_SEC

    def _purge(self):
        """차가 꽉 찼을 때만: GONE_SEC 넘게 소식 없는 차를 도로·그룹에서 뺀다. 아무도 남지 않은 그룹은 코드와 함께 지운다"""
        gone = {c["id"] for c in self.cars if self.now - c["t"] >= GONE_SEC}
        if not gone:
            return
        self.cars = [c for c in self.cars if c["id"] not in gone]
        for cid in gone:
            self.tries.pop(cid, None)
        for gid, g in list(self.groups.items()):
            g["members"] = [m for m in g["members"] if m not in gone]
            for m in gone:
                g["answers"].pop(m, None)
            if not g["members"]:
                self._drop_group(gid)
            elif g["journey"]["ride"] in gone:
                g["journey"]["ride"] = g["members"][0]

    def _drop_group(self, gid):
        g = self.groups.pop(gid)
        if self.codes.get(g["code"]) == gid:
            del self.codes[g["code"]]
        for c in self.cars:
            if c["group"] == gid:
                c["group"] = None

    def clock(self, body):
        """요청 t 로 허브 시계를 앞으로만 옮긴다. 유한한 시각만 받는다(inf 를 한 번 받으면 이후 모든 정상 시각이 "과거"가 되어 허브가 멈춘다 — 앱과 같다).
        시계 오차 가드(ADR-43): 허브는 자기 시계가 없고 차들의 t 만 믿는다. 그래서 t 를 '허브 now + 그 뒤 실제 경과(단조 시계)'와 견줘
        CLOCK_SKEW_SEC 넘게 어긋나면 그 t 로 시계를 옮기지 않고(창은 허브 시각 = 정상 차들이 정한 수신 시각 기준) 그 차(me)의 보기에 clockSkew(초)를 준다.
        기대값 자체로 옮기지 않는 까닭: 실제 경과(ms)가 허브 시각에 섞여 두 엔진의 보기(detectionTime·age)가 갈린다.
        기준점(anchor)은 요청마다 (허브 now, 실제 시각)으로 다시 잡는다 — 정상 시계·논리 시각 대본(1 s 씩)은 전과 같이 받는다"""
        t = body.get("t")
        if t is None or not math.isfinite(float(t)):
            return
        t = float(t)
        real = time.monotonic()
        c = self.car(body.get("me"))
        if self.anchor is not None and self.clock_guard:
            expect = self.anchor[0] + (real - self.anchor[1])
            skew = t - expect
            if abs(skew) > CLOCK_SKEW_SEC:
                if c:
                    c["skew"] = rnd(skew)
                t = None                                 # 이 t 로는 시계를 옮기지 않는다
            elif c:
                c["skew"] = None
        elif c:
            c["skew"] = None
        if t is not None and t > self.now:
            self._advance(t)
        self.anchor = (self.now, real)

    # ---- 도로 링크
    def join_road(self, body):
        self.clock(body)
        c = self._new_car(clean(body.get("name") or "", NAME_MAX), clean(body.get("car") or "", CAR_MAX),
                          clean(body.get("kind") or "", KIND_MAX) or "pleos", lang_of(body.get("lang")))
        if c:
            c["units"] = units_of(body.get("units"))
        return c

    def state(self, body):
        self.clock(body)
        c = self.car(body.get("me"))
        if not c:
            return
        if body.get("s") is not None:
            c["s"] = float(body["s"])
        elif body.get("lat") is not None and body.get("lon") is not None:
            c["s"] = project(xy(float(body["lat"]), float(body["lon"])))
        if body.get("speed") is not None:
            c["speed"] = float(body["speed"])
        for k in ("soc", "temp"):
            if body.get(k) is not None:
                c[k] = body[k]
        if body.get("wiper") is not None:
            c["wiper"] = str(body["wiper"])
        if "limit" in body:                              # 순정 내비 현재 도로 제한속도(km/h). 0 이하·LIMIT_MAX 초과·숫자 아님 = 모름
            lim = body["limit"]
            c["limit"] = int(lim) if isinstance(lim, (int, float)) and not isinstance(lim, bool) and 0 < lim <= LIMIT_MAX else None
        if c["s"] is not None:                           # 경로 위 실제 이동 속도(시연은 압축된 거리 기준) — 긴급차량과 가까워지는 속도에 쓴다
            if c["st"] and self.now > c["st"][0]:
                c["vs"] = (c["s"] - c["st"][1]) / (self.now - c["st"][0])
            c["st"] = (self.now, c["s"])
        prev_s = c["st"][1] if c["st"] else None
        c["t"] = self.now
        if c["kind"] == "ev":                            # 긴급차량 비컨: 출동 여부·목적지만 받고 정체·사고 판단에는 넣지 않는다
            if isinstance(body.get("on"), bool):
                c["on"] = body["on"]
            if "dest_s" in body:
                d = body["dest_s"]
                c["dest"] = float(d) if isinstance(d, (int, float)) and not isinstance(d, bool) else None
            self._beacon(c)
            return
        inc = c["inc"]
        if inc and "COMM_LOSS" in inc["ev"]:              # 다시 보고한다 = 통신이 돌아왔다
            del inc["ev"]["COMM_LOSS"]
        self._passing(c, prev_s)
        self._derive(c)
        for g in self.groups.values():
            if c["id"] in g["members"]:
                self._journey(g)

    def event(self, body):
        self.clock(body)
        c = self.car(body.get("me"))
        if c:
            self._event_body = body
            # 이벤트에 실린 그 순간의 위치·속도(차가 보내면)를 먼저 반영 — 마지막 상태 보고 자리에 찍히지 않게. 앱 엔진(LinkHub.kt)과 같은 규칙
            if body.get("s") is not None:
                c["s"] = float(body["s"])
            if body.get("speed") is not None:
                c["speed"] = float(body["speed"])
            self._event(c, str(body.get("type", "")), str(body.get("value", "")))

    def _derive(self, c):
        """속도 흐름에서 정체·사고 의심을 만든다(차는 급제동·날씨만 보낸다)"""
        if c["s"] is None:
            return
        now, v = self.now, c["speed"]
        if v < STOP_MS and self._rest_near(c["s"]):     # 휴게소에 세운 차(충전·휴식)는 정체·사고 의심의 근거가 아니다
            for typ in ("CONGESTION", "INCIDENT"):
                if typ in c["active"]:
                    self._clear(c, typ)
            c["slowSince"] = c["stopSince"] = None
            return
        if v < SLOW_MS:
            c["slowSince"] = now if c["slowSince"] is None else c["slowSince"]
            if now - c["slowSince"] >= SLOW_HOLD and "CONGESTION" not in c["active"]:
                self._report(c, "CONGESTION", f"{rnd(v * 3.6)}km/h")
        elif v > FAST_MS:
            c["slowSince"] = None
            if "CONGESTION" in c["active"]:
                self._clear(c, "CONGESTION")
        if v < STOP_MS:
            c["stopSince"] = now if c["stopSince"] is None else c["stopSince"]
            inc = c["inc"]
            if (inc and not inc["closed"] and "STOP" not in inc["ev"] and now - c["stopSince"] >= INCIDENT_HOLD
                    and abs(c["s"] - inc["s0"]) <= INC_NEAR):
                self._evidence(c, "STOP")                # 사건(급제동·급조향·충돌) 뒤 300 m 안 30 s 정차
        else:
            c["stopSince"] = None
            if v > FAST_MS:
                if "INCIDENT" in c["active"]:
                    self._clear(c, "INCIDENT")
                if c["inc"]:
                    c["inc"]["closed"] = True             # 다시 달린다 = 창을 닫는다

    # ---- 사고 판단: 근거 창
    def _evidence(self, c, tag):
        """근거 하나를 차의 사건 창에 더하고 판단한다. 창은 첫 근거부터 60 s·300 m"""
        now, s = self.now, c["s"]
        inc = c["inc"]
        if inc and (inc["closed"] or now - inc["t0"] > INC_WINDOW or abs(s - inc["s0"]) > INC_NEAR):
            inc = None
        if inc is None:
            inc = c["inc"] = {"s0": s, "t0": now, "ev": {}, "closed": False, "reported": False, "lossV": None}
        inc["ev"].setdefault(tag, now)
        self._judge(c)

    def _judge(self, c):
        inc = c["inc"]
        if not inc or inc["closed"]:
            return
        score = sum(INC_POINTS[t] for t in inc["ev"])
        if score >= INC_MIN and any(t in inc["ev"] for t in INC_HARD):
            h = None
            if not inc["reported"]:
                inc["reported"] = True
                h = self._report(c, "INCIDENT", "score", inc["s0"])
            h = h or next((x for x in self.hazards if x["type"] == "INCIDENT" and c["id"] in x["reporters"] and abs(x["s"] - inc["s0"]) <= INC_NEAR), None)
            if h is not None:
                h.setdefault("ev", {})[c["id"]] = sorted(inc["ev"], key=INC_ORDER.index)
                h.setdefault("passed", set()).discard(c["id"])   # 지나가던 차가 보고 차가 되면 '통과'에서 뺀다
                h.setdefault("score", {})[c["id"]] = score

    def _impact_ok(self, body):
        """차가 보낸 10 Hz 표본으로 충돌을 같은 규칙으로 다시 본다. 표본이 없으면 믿는다"""
        samples = body.get("samples") if body else None
        if not samples:
            return True
        pts = [(float(p[0]), float(p[1])) for p in samples]
        for i in range(1, len(pts)):
            ti, vi = pts[i]
            for k in range(i - 1, -1, -1):
                tk, vk = pts[k]
                dt = ti - tk
                if dt > IMPACT_DT_MAX:
                    break
                if dt >= IMPACT_DT_MIN and vk - vi >= IMPACT_DV and (vk - vi) / dt >= IMPACT_A:
                    tail = [v for (t, v) in pts if ti < t <= ti + IMPACT_HOLD]
                    if tail and all(v < 0.5 * vk for v in tail):
                        return True
                    break
        return False

    def _scan_comm_loss(self):
        """충돌을 보고한 차가 그 뒤 15 s 안의 보고를 끝으로 8 s 넘게 조용하면 '통신 끊김'(사고로 인한)"""
        for c in self.cars:
            inc = c["inc"]
            if not inc or inc["closed"] or "IMPACT" not in inc["ev"] or "COMM_LOSS" in inc["ev"]:
                continue
            if c["t"] <= inc["t0"] + COMM_AFTER and self.now - c["t"] >= COMM_LOSS and not self._in_tunnel(c["s"]):
                inc["ev"]["COMM_LOSS"] = self.now
                inc["lossV"] = c["speed"]
                self._judge(c)

    def _passing(self, c, prev_s):
        """보고하지 않은 차가 사고 의심 지점을 60 km/h 넘게 지나가면 '통과'로 센다 → 3대면 해제, 1~2대면 일부 차로 통행"""
        if prev_s is None or c["s"] is None or c["speed"] <= FAST_MS:
            return
        for h in self.hazards:
            if h["type"] != "INCIDENT" or not h["reporters"] or c["id"] in h["reporters"]:
                continue
            if prev_s < h["s"] <= c["s"] or abs(c["s"] - h["s"]) <= INC_NEAR:
                h.setdefault("passed", set()).add(c["id"])
                if len(h["passed"]) >= CLEAR_PASS and not any(self.car(r) and self.car(r)["speed"] < STOP_MS and abs((self.car(r)["s"] or -9e9) - h["s"]) <= INC_NEAR for r in h["reporters"]):
                    h["reporters"].clear()
                    h["cleared"] = self.now

    def respond(self, body):
        """운전자 응답: ok=true → 사고 아님(창 닫고 내 보고 거둠), ok=false·timeout → 응답 없음 근거"""
        self.clock(body)
        c = self.car(body.get("me"))
        if not c or not c["inc"]:
            return
        if body.get("ok") is True:
            c["inc"]["closed"] = True
            if c["inc"]["reported"]:
                self._clear(c, "INCIDENT")
        else:
            self._evidence(c, "NO_RESPONSE")

    def post_charger_status(self, body):
        """충전기 공식 상태를 받는다 {t, stations:[{statId, chargers:[{id, stat}]}]}. 키를 가진 서버(시연은 PC 스크립트 fetch_ev_status.py)가 올린다 — 앱에는 공공데이터 키를 넣지 않는다"""
        self.clock(body)
        for st in (body.get("stations") or [])[:200]:
            if not isinstance(st, dict):
                continue
            sid = str(st.get("statId") or "")[:16]
            ch = st.get("chargers")
            if not isinstance(ch, list) or not sid:
                continue
            m = {}
            for c in ch[:99]:
                if not isinstance(c, dict):
                    continue
                try:
                    v = int(str(c.get("stat")))
                except ValueError:
                    v = 9
                m[str(c.get("id") or "")[:4]] = v
            self.chg_official[sid] = {"t": self.now, "chargers": m}

    def _chg_off(self, rest_s):
        """휴게소(s) 충전기의 공식 운영중지·점검중 — 없거나(모두 되거나 받은 게 없거나 30분 지남) None"""
        rows = [self.chg_official[i] for i in CHG_STAT_IDS.get(float(rest_s), []) if i in self.chg_official]
        rows = [r for r in rows if self.now - r["t"] <= CHG_OFFICIAL_TTL]
        if not rows:
            return None
        st = [v for r in rows for v in r["chargers"].values()]
        halt, check = st.count(4), st.count(5)
        if halt + check == 0:
            return None
        return {"total": len(st), "down": halt + check, "halt": halt, "check": check, "t": max(r["t"] for r in rows)}

    def _chg_kind(self, lang, o):
        if o["check"] == 0:
            return L(lang, "운영중지", "out of service")
        if o["halt"] == 0:
            return L(lang, "점검중", "under maintenance")
        return L(lang, "운영중지·점검중", "out of service or under maintenance")

    def _chg_off_json(self, lang, o):
        return {"total": o["total"], "down": o["down"], "halt": o["halt"], "check": o["check"], "kind": self._chg_kind(lang, o)}

    def _chg_off_sentence(self, lang, ahead, rn, o):
        """차 보고 없이 공식 상태만: '전방 Xkm {휴게소} 충전기 10대 중 2대 점검중(공식 정보). 나머지 8대를 이용하세요.'"""
        where = L(lang, f"전방 {self.km_text(lang, ahead)}", f"{self.km_text(lang, ahead)} ahead")
        kind = self._chg_kind(lang, o)
        act = (L(lang, "이 휴게소 충전이 어렵습니다. 다음 충전소를 확인하세요.", "Charging there may not be possible. Check the next charging station.") if o["down"] >= o["total"]
               else L(lang, f"나머지 {o['total'] - o['down']}대를 이용하세요.", f"Use the other {o['total'] - o['down']}."))
        cnt = (L(lang, f"충전기 {o['total']}대 모두 {kind}", f"all {o['total']} chargers at {rn} {kind}") if o["down"] >= o["total"]
               else L(lang, f"충전기 {o['total']}대 중 {o['down']}대 {kind}", f"{o['down']} of {o['total']} chargers at {rn} {kind}"))
        return L(lang, f"{where} {rn} {cnt}(공식 정보). {act}", f"{where}, {cnt} (official). {act}")

    def post_official(self, body):
        """차가 올린 순정 내비 돌발 정보(ACCIDENT·ROAD_DAMAGE·DISASTER만): 경로 위 s 로 투영해 두고(같은 종류 300 m 안은 하나), endTime 또는 30분 뒤 지운다"""
        self.clock(body)
        c = self.car(body.get("me"))
        if not c:
            return
        for e in body.get("events") or []:
            typ = str(e.get("type", ""))
            if typ not in OFFICIAL_TYPES:
                continue
            if e.get("s") is not None:
                s, d = float(e["s"]), 0.0
            elif e.get("lat") is not None and e.get("lon") is not None:
                s, d = project_d(xy(float(e["lat"]), float(e["lon"])))
            else:
                continue
            if d > OFFICIAL_OFFROUTE:
                continue                                  # 경로 밖(다른 도로)의 돌발은 버린다
            end = float(e["end"]) if e.get("end") is not None else None
            desc = clean(str(e.get("desc") or ""), DESC_MAX)
            o = next((o for o in self.official if o["type"] == typ and abs(o["s"] - s) <= OFFICIAL_MERGE), None)
            if o:
                o["t"], o["end"], o["desc"] = self.now, end, desc or o["desc"]
            else:
                self.seq += 1
                self.official.append({"id": f"o{self.seq}", "type": typ, "s": s, "end": end, "desc": desc, "t": self.now, "first": self.now, "by": c["id"]})

    def _in_tunnel(self, s):
        return s is not None and any(z["kind"] == "tunnel" and z["s0"] - TUNNEL_MARGIN <= s <= z["s1"] + TUNNEL_MARGIN for z in ZONES)

    def _zone_at(self, s):
        """s 가 들어간 사고 다발 구간(±300 m)"""
        return next((z for z in ZONES if z["kind"] == "accident" and z["s0"] - ZONE_NEAR <= s <= z["s1"] + ZONE_NEAR), None)

    def _zones_view(self, lang, me, my_s):
        """내 앞(10 km 안)과 지금 안에 있는 구역. 말은 교량 결빙(외기 4 °C 이하, 1.5 km 앞)만 — 다발 구간은 지도·사고 의심 문장 맥락·위험성으로"""
        if my_s is None:
            return []
        try:
            temp = float(me["temp"]) if me and me["temp"] is not None else None
        except (TypeError, ValueError):
            temp = None
        out = []
        for z in ZONES:
            if z["s1"] < my_s or z["s0"] - my_s > ALERT_RANGE:
                continue
            ahead = z["s0"] - my_s
            name = z["name"] if lang == "ko" else z["nameEn"]
            item = {"id": z["id"], "kind": z["kind"], "s0": z["s0"], "s1": z["s1"], "ahead": rnd(ahead), "inside": z["s0"] <= my_s <= z["s1"],
                    "label": L(lang, "사고 다발 구간", "Accident-prone section") if z["kind"] == "accident" else name}
            if z["kind"] == "accident":                    # 다발 구간은 지도에만(말 줄이기 10-11 — 통계라 지금 할 일이 없다)
                item.update({"name": name, "count": z["count"], "deaths": z["deaths"], "years": z["years"]})
            elif z["kind"] == "bridge" and 0 < ahead <= ZONE_SAY and temp is not None and temp <= ICE_TEMP:
                item["say"] = L(lang, f"전방 {self.km_text(lang, ahead)} {name} 결빙 주의. 서행하세요.",
                                f"{self.km_text(lang, ahead)} ahead, {name}: watch for ice. Drive slowly.")
            out.append(item)
        return out

    def _risk(self, me, my_s, hazards, ahead):
        """환경·도로 위험성: 앞 3 km 확정 사고 의심·정체 꼬리 +3, 결빙(외기 ≤ 4 °C 이고 비·새벽·교량 1 km, 또는 확정 결빙 보고) +2(≤ 0 °C 면 +3),
        사고 다발 구간 안·1 km 앞 +2, 비(내 와이퍼 연속·앞 3 km 확정 폭우) +2, 터널 1 km +1, 야간 +1, 1 km 안 낙하물·통행 불가 +1"""
        if my_s is None:
            return None
        try:
            temp = float(me["temp"]) if me and me["temp"] is not None else None
        except (TypeError, ValueError):
            temp = None
        near = lambda h, lo, hi: h.get("confirmed") and h.get("ahead") is not None and lo < h["ahead"] <= hi
        zone_near = lambda kind: any(z["kind"] == kind and z["s1"] >= my_s and z["s0"] - my_s <= RISK_NEAR for z in ZONES)
        hour = ((self.now + KST) % 86400) / 3600
        rain = bool(me and me["wiper"].startswith("CONTINUOUS")) or any(h["type"] == "HEAVY_RAIN" and near(h, -500, RISK_AHEAD) for h in hazards)
        items = []
        cands = [(h["ahead"], "incident" if h["type"] == "INCIDENT" else "jam") for h in hazards if h["type"] in ("INCIDENT", "CONGESTION") and near(h, 0, RISK_AHEAD)]
        adv = ahead.get("advice") if ahead else None
        if adv and adv["dist"] <= RISK_AHEAD:
            cands.append((adv["dist"], "jam"))
        if cands:
            d, kind = min(cands)
            items.append({"tag": "AHEAD", "pts": RISK_PTS["AHEAD"], "ahead": d, "kind": kind})
        icy = any(h["type"] == "ICING" and near(h, -500, RISK_AHEAD) for h in hazards)
        if icy or (temp is not None and temp <= ICE_TEMP and (rain or hour < 7 or zone_near("bridge"))):
            items.append({"tag": "ICE", "pts": RISK_PTS["ICE_HARD" if temp is not None and temp <= 0 else "ICE"]})
        if zone_near("accident"):
            items.append({"tag": "ZONE", "pts": RISK_PTS["ZONE"]})
        if rain:
            items.append({"tag": "RAIN", "pts": RISK_PTS["RAIN"]})
        if zone_near("tunnel"):
            items.append({"tag": "TUNNEL", "pts": RISK_PTS["TUNNEL"]})
        if hour >= 20 or hour < 6:
            items.append({"tag": "NIGHT", "pts": RISK_PTS["NIGHT"]})
        if any(h["type"] in ("DEBRIS", "BLOCKED") and near(h, 0, RISK_NEAR) for h in hazards):
            items.append({"tag": "DEBRIS", "pts": RISK_PTS["DEBRIS"]})
        items.sort(key=lambda x: (-x["pts"], RISK_ORDER.index(x["tag"])))
        score = min(10, sum(x["pts"] for x in items))
        return {"score": score, "level": 2 if score >= RISK_HIGH else 1 if score >= RISK_CAUTION else 0, "items": items}

    def _official_near(self, s):
        """s 에서 2 km 안의 공식 돌발(가장 가까운 것)"""
        return min((o for o in self.official if abs(o["s"] - s) <= OFFICIAL_NEAR), key=lambda o: abs(o["s"] - s), default=None)

    def _official_item(self, lang, o):
        return {"type": o["type"], "kind": L(lang, OFFICIAL_KO[o["type"]], OFFICIAL_EN[o["type"]]), "desc": o["desc"], "s": rnd(o["s"]),
                "end": o["end"], "age": rnd(self.now - o["first"])}

    def _strong(self, cid, h):
        """모르는 차 1대 확정: 점수 ≥ 6 이고 (응답 없음·에어백) 또는 (충돌+통신 끊김이고 끊기기 전 정지), 세션 2분↑, 30분에 한 번"""
        c = self.car(cid)
        if not c:
            return False
        ev = h.get("ev", {}).get(cid, [])
        stopped_loss = "IMPACT" in ev and "COMM_LOSS" in ev and c["inc"] and c["inc"].get("lossV") is not None and c["inc"]["lossV"] < STOP_MS
        if not stopped_loss and (h.get("score", {}).get(cid, 0) < INC_STRONG or not ("NO_RESPONSE" in ev or "AIRBAG" in ev)):
            return False
        if self.now - c["joinT"] < STRONG_SESSION:
            return False
        if c["strongH"] == h["id"]:
            return True
        if c["strongAt"] is not None and self.now - c["strongAt"] < STRONG_GAP:
            return False
        c["strongAt"], c["strongH"] = self.now, h["id"]
        return True

    def _evidence_phrase(self, lang, tags):
        """근거 둘까지: '급제동 후 충돌', '충돌, 응답 없음'"""
        tags = [t for t in INC_ORDER if t in tags][:2]
        if not tags:
            return L(lang, "급제동 후 정차", "stopped after hard braking")
        names = [L(lang, INC_KO[t], INC_EN[t]) for t in tags]
        if len(names) == 1:
            return names[0]
        seq = tags[0] in ("SWERVE", "HARD_BRAKE", "IMPACT") and tags[1] in ("IMPACT", "STOP", "AIRBAG")
        return L(lang, f"{names[0]} 후 {names[1]}" if seq else f"{names[0]}, {names[1]}", f"{names[0]} then {names[1]}" if seq else f"{names[0]}, {names[1]}")

    def _event(self, c, typ, value):
        if c["s"] is None or not typ or c["kind"] == "ev":
            return
        if typ == "YIELD":
            self._yield(c)
            return
        raw = typ
        typ = EVENT_TYPE.get(typ, typ)
        if typ.endswith("_CLEARED"):
            self._clear(c, typ[:-8])
            return
        if typ == "HARD_BRAKE":
            c["brake"] = (self.now, c["s"])
        if raw == "IMPACT" and not self._impact_ok(getattr(self, "_event_body", None)):
            raw = typ = "HARD_BRAKE"                      # 허브 재검증 실패(한 표본 튐 등) → 급제동으로 낮춘다
        if raw in INC_POINTS:
            self._evidence(c, raw)                        # 급제동·급조향·충돌·에어백은 사고 판단의 근거
        if raw in ("IMPACT", "AIRBAG"):
            return                                        # 그 자체는 위험 종류가 아니다
        body = getattr(self, "_event_body", None) or {}
        if raw == "CHARGE_SUCCESS":
            self._charge_success(c, c["s"])
            return
        if typ in CHARGER:
            # 설문·자리 이동은 실패한 자리(from)로 휴게소를 찾는다(차가 조금 움직였거나 떠난 뒤 말로 신고해도 같은 휴게소)
            at = float(body["from"]) if typ == "CHARGER_FAULT" and body.get("from") is not None else c["s"]
            r = self._charger_rest(at)
            if r:
                h = self._report(c, typ, value, r["s"], r)
                if typ == "CHARGER_FAULT":
                    self._charge_note(h, c, raw, value, body, c["s"])
            return
        if typ in TTL:
            self._report(c, typ, value)

    def _charge_note(self, h, c, raw, value, b, s):
        """충전기 고장 위험에 이 차의 기록을 더한다: CHARGE_FAIL(꽂고 90초 충전 없음 + 운전자 '예' 또는 무응답), CHARGE_MOVED(실패 뒤 다른 자리에서 충전 —
        그 기기 고장의 강한 근거라 해제하지 않는다, 값 = 옮긴 m), CHARGE_REPORT(운전자 1분 설문: sym·place·unit·broken·alt, 모름은 빠짐)"""
        frm = float(b["from"]) if b.get("from") is not None else s
        n = h["notes"].setdefault(c["id"], {"spot": frm, "fail": False, "human": False, "moved": None,
                                            "sym": None, "place": None, "unit": None, "broken": None, "alt": None})
        if raw == "CHARGE_FAIL":
            n["fail"], n["spot"] = True, frm
        elif raw == "CHARGE_MOVED":
            try:
                mv = float(value)
            except ValueError:
                mv = abs(s - frm)
            n["fail"], n["spot"], n["moved"] = True, frm, mv
        elif raw == "CHARGE_REPORT":
            n["human"] = True
            if b.get("from") is not None:
                n["spot"] = frm
            for k, ok in (("sym", CHARGE_SYM), ("place", tuple(PLACE_KO)), ("broken", BROKEN), ("alt", ("yes", "no", "wait"))):
                v = b.get(k)
                if isinstance(v, str) and v in ok:
                    n[k] = v
            try:
                u = int(b.get("unit") or 0)
            except (TypeError, ValueError):
                u = 0
            if 1 <= u <= 99:
                n["unit"] = u

    def _charge_success(self, c, s):
        """다른 차가 이 휴게소에서 충전에 성공: 같은 자리(2.5 m 안)의 고장 기록은 거둔다(고쳐졌거나 그 차 문제), 다른 자리면 '다른 기기는 된다'의 근거"""
        r = self._charger_rest(s)
        if not r:
            return
        for h in self.hazards:
            if h["type"] == "CHARGER_FAULT" and h["reporters"] and abs(h["s"] - r["s"]) <= CHARGER_NEAR:
                same = [i for i, n in h["notes"].items() if i != c["id"] and abs(n["spot"] - s) <= CHARGE_SPOT_M]
                for i in same:
                    del h["notes"][i]
                    h["reporters"].pop(i, None)
                    o = self.car(i)
                    if o:
                        o["active"].discard("CHARGER_FAULT")
                if not same and c["id"] not in h["reporters"] and c["id"] not in h["okOther"]:
                    h["okOther"].append(c["id"])
                if not h["reporters"]:
                    h["cleared"] = self.now

    def _charge_info(self, h):
        ns = [n for i, n in h["notes"].items() if i in h["reporters"]]

        def top(xs, order):
            m = {x: xs.count(x) for x in order if x in xs}
            return max(m, key=m.get) if m else None
        br = [n["broken"] for n in ns if n["broken"]]
        return {"human": sum(1 for n in ns if n["human"]), "fail": sum(1 for n in ns if n["fail"]), "moved": sum(1 for n in ns if n["moved"] is not None),
                "other": len([i for i in h["okOther"] if i not in h["reporters"]]), "units": sorted({n["unit"] for n in ns if n["unit"]}),
                "place": top([n["place"] for n in ns if n["place"]], tuple(PLACE_KO)), "sym": top([n["sym"] for n in ns if n["sym"]], CHARGE_SYM),
                "broken": max(br, key=BROKEN.index) if br else None, "altYes": any(n["alt"] == "yes" for n in ns),
                "strong": any(n["human"] and n["moved"] is not None for n in ns)}

    def _charge_label(self, lang, ch):
        """사람 신고가 있으면 이름표에서 '의심'을 뗀다: '충전기 3번 고장 신고'"""
        if ch["units"]:
            return L(lang, f"충전기 {'·'.join(map(str, ch['units']))}번 고장 신고", f"Charger {', '.join(f'#{u}' for u in ch['units'])} reported broken")
        return L(lang, "충전기 고장 신고", "Charger reported broken")

    def _charge_sentence(self, lang, ahead, rest, named, anon, cars, ch, co=None):
        """충전기 고장 한 문장. 사람 신고가 있으면 '전방 Xkm {휴게소} 충전기 3번 고장 신고 2건(화면 꺼짐). 다른 기기는 사용할 수 있습니다.'
        없으면 전과 같이 '… 충전기 고장 의심. 차량 N대 충전 실패 확인. …'. '다른 기기는 된다'는 다른 자리에서 충전된 근거(자리 옮김·다른 차·설문 '예')가 있을 때만"""
        where = L(lang, f"전방 {self.km_text(lang, ahead)}", f"{self.km_text(lang, ahead)} ahead")
        rn = (rest["name"] if lang == "ko" else rest["nameEn"]) if rest else ""
        off_txt = L(lang, f" 공식 정보로도 {co['down']}대 {self._chg_kind(lang, co)}.", f" Official data: {co['down']} {self._chg_kind(lang, co)}.") if co else ""
        if named:
            who = L(lang, f"{named[0]} 차량 외 {anon}대" if anon else f"{named[0]} 차량",
                    f"{named[0]}'s car and {anon} more" if anon else f"{named[0]}'s car")
        else:
            who = L(lang, f"차량 {cars}대", f"{cars} cars")
        elsewhere = bool(ch["moved"] or ch["other"] or ch["altYes"])   # 같은 휴게소 다른 자리에서 충전됨(자리 옮김·다른 차·설문 '예') — '전부 고장'보다 앞선다
        if elsewhere:
            act = L(lang, "다른 기기는 사용할 수 있습니다.", "Other chargers there are working.")
        elif ch["broken"] == "all":
            act = L(lang, "이 휴게소 충전이 어렵습니다. 다음 충전소를 확인하세요.", "Charging there may not be possible. Check the next charging station.")
        elif co and co["down"] < co["total"]:                 # 공식 정보로 남은 대수를 안다
            act = L(lang, f"나머지 {co['total'] - co['down']}대를 이용하세요.", f"Use the other {co['total'] - co['down']}.")
        elif co:
            act = L(lang, "이 휴게소 충전이 어렵습니다. 다음 충전소를 확인하세요.", "Charging there may not be possible. Check the next charging station.")
        else:
            act = L(lang, "다음 충전소를 확인하세요.", "Check the next charging station.")
        if not ch["human"]:
            mv = L(lang, f", {ch['moved']}대는 다른 자리에서 충전됨", f"; {ch['moved']} charged at another spot") if ch["moved"] else ""
            return L(lang, f"{where} {rn} 충전기 고장 의심. {who} 충전 실패 확인{mv}.{off_txt} {act}", f"{where}, possible charger fault at {rn}. {who} failed to charge{mv}.{off_txt} {act}")
        units = ch["units"]
        unit_ko = f" {'·'.join(map(str, units))}번" if units else ""
        unit_en = (" " + ", ".join(f"#{u}" for u in units)) if units else ""
        place_ko = f" {PLACE_KO[ch['place']]}" if ch["place"] and not units else ""
        place_en = f" {PLACE_EN[ch['place']]}" if ch["place"] and not units else ""
        broken = ch["broken"] if ch["broken"] in ("2", "3") or (ch["broken"] == "all" and not elsewhere) else None   # '1대'는 신고 건수와 겹친다
        det_ko = [x for x in (SYM_KO.get(ch["sym"]), BROKEN_KO.get(broken)) if x]
        det_en = [x for x in (SYM_EN.get(ch["sym"]), BROKEN_EN.get(broken)) if x]
        hn = ch["human"]
        mv = L(lang, f" {ch['moved']}대는 다른 자리에서 충전됨.", f" {ch['moved']} charged at another spot.") if ch["moved"] else ""
        return L(lang, f"{where} {rn}{place_ko} 충전기{unit_ko} 고장 신고 {hn}건{'(' + ', '.join(det_ko) + ')' if det_ko else ''}.{mv}{off_txt} {act}",
                 f"{where}, charger{unit_en} at {rn}{place_en} reported out of order ({hn} report{'s' if hn > 1 else ''}{': ' + ', '.join(det_en) if det_en else ''}).{mv}{off_txt} {act}")

    def _rest_here(self, lang, s):
        """차 위치 500m 안의 휴게소 이름(앱이 휴게소 정차 중 [충전기 고장 신고] 버튼을 띄운다) — 없으면 None"""
        r = self._charger_rest(s) if s is not None else None
        return (r["name"] if lang == "ko" else r["nameEn"]) if r else None

    def _charger_rest(self, s):
        """충전소 반경 안의 휴게소: 충전소 좌표(evStations)가 있으면 그 s 에서 STATION_NEAR 안, 없으면 휴게소 s 에서 CHARGER_NEAR 안 — 없으면 None.
        충전 보고·신고·충전 성공·보기 restHere 가 쓴다(정체·사고 제외용 휴게소 판정은 _rest_near 그대로)"""
        def ok(r):
            st = EV_STATIONS.get(float(r["s"]))
            return any(abs(x - s) <= STATION_NEAR for x in st) if st else abs(r["s"] - s) <= CHARGER_NEAR
        return min((r for r in REST if r["kind"] == "services" and ok(r)), key=lambda r: abs(r["s"] - s), default=None)

    def _rest_near(self, s):
        """차 위치 500m 안의 휴게소(충전기가 있는 곳) — 없으면 None"""
        return min((r for r in REST if r["kind"] == "services" and abs(r["s"] - s) <= CHARGER_NEAR), key=lambda r: abs(r["s"] - s), default=None)

    def _report(self, c, typ, value, s=None, rest=None):
        now = self.now
        s = c["s"] if s is None else s
        if typ not in ONE_SHOT:
            c["active"].add(typ)
        self.pulses.append({"t": r1(now), "s": rnd(s), "type": typ, "car": c["id"], "pub": c["pub"]})
        del self.pulses[:-40]
        for h in self.hazards:
            if h["type"] == typ and abs((self._ev_pos(h)[0] if typ == "SIREN" else h["s"]) - s) <= MERGE.get(typ, MERGE_M):
                if typ == "SIREN" and c["id"] not in h["reporters"]:   # 이 차가 처음 들었다 = 긴급차량이 여기 가까이 왔다
                    h["track"].append((now, s))
                    h["s"] = s
                if typ == "SIREN":
                    h["cleared"] = None                   # 비컨이 꺼진 위험도 마이크 보고가 다시 살린다
                h["reporters"][c["id"]] = now
                h["last"], h["value"] = now, value
                return h
        self.seq += 1
        self.hazards.append({"id": f"h{self.seq}", "type": typ, "s": s, "reporters": {c["id"]: now}, "first": now,
                             "rest": rest and {"name": rest["name"], "nameEn": rest["nameEn"]}, "notes": {}, "okOther": [],
                             "last": now, "value": value, "cleared": None, "track": [(now, s)], "beacon": None, "yields": {}})
        g = self.groups.get(c["group"]) if c["group"] else None
        if g and c["kind"] != "anon":
            self._glog(g, f"{c['name']} 차: {TYPE_KO[typ]}", f"{c['name']}: {TYPE_EN[typ]}")
        return self.hazards[-1]

    def _clear(self, c, typ):
        c["active"].discard(typ)
        for h in self.hazards:
            if h["type"] == typ and c["id"] in h["reporters"]:
                del h["reporters"][c["id"]]
                h.get("notes", {}).pop(c["id"], None)
                if not h["reporters"]:
                    h["cleared"] = self.now

    def _siren(self, h):
        """긴급차량의 지금 위치(짐작)와 경로 위 속도. 차들이 처음 들은 곳이 앞으로 옮겨 가는 속도로 잰다(모르면 None)"""
        tr = [p for p in h["track"] if self.now - p[0] <= SIREN_TRACK]
        if len(tr) < 2 or tr[-1][0] - tr[0][0] < SIREN_MIN_DT:
            return h["s"], None
        v = (tr[-1][1] - tr[0][1]) / (tr[-1][0] - tr[0][0])
        return (h["s"] + v * min(self.now - tr[-1][0], SIREN_EXTRAP) if v > 0 else h["s"]), v

    # ---- 긴급차량 위치 신호(비컨)·길 터 주기 물결
    def _ev(self, h):
        """이 위험에 묶인 비컨 차가 살아 있으면(출동 중·위치 있음·15초 안 소식) 그 차, 아니면 None"""
        c = self.car(h["beacon"]) if h["beacon"] else None
        return c if c and c["on"] and c["s"] is not None and self.now - c["t"] <= EV_STALE else None

    def _beacon_v(self, c):
        """비컨의 경로 위 속도: 최근 10초 위치의 처음과 끝(3초 넘게 떨어져야)"""
        tr = [p for p in c["bt"] if self.now - p[0] <= EV_TRACK]
        if len(tr) < 2 or tr[-1][0] - tr[0][0] < SIREN_MIN_DT:
            return None
        return (tr[-1][1] - tr[0][1]) / (tr[-1][0] - tr[0][0])

    def _wave_pts(self, pts):
        """YIELD 점(t, s, v, 차) 목록 → 물결이면 (지금 짐작 위치, 물결 속도), 아니면 None. 서로 다른 차 2대 이상, 처음과 끝이 3초 넘게,
        물결 속도가 그 차들의 경로 위 속도 평균보다 5 m/s 넘게 빠를 때"""
        pts = sorted(pts, key=lambda p: (p[0], p[1], p[3]))   # 같은 시각이면 위치 순(차 id 는 무작위라 순서를 정하는 데 쓰지 않는다)
        if len(pts) < YIELD_MIN or pts[-1][0] - pts[0][0] < SIREN_MIN_DT:
            return None
        v = (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])
        traffic = sum(p[2] for p in pts) / len(pts)
        if v <= traffic + YIELD_FAST:
            return None
        return pts[-1][1] + v * min(self.now - pts[-1][0], SIREN_EXTRAP), v

    def _yields_live(self, h):
        return [(t, s, v, cid) for cid, (t, s, v) in h["yields"].items() if self.now - t <= YIELD_WINDOW]

    def _wave(self, h):
        return self._wave_pts(self._yields_live(h))

    def _ev_pos(self, h):
        """긴급차량 위치·경로 위 속도: 비컨 > 마이크(처음 들은 곳의 이동) > 길 터 주기 물결. 비컨·물결이 없으면 전과 같다(_siren)"""
        c = self._ev(h)
        if c:
            return c["s"], self._beacon_v(c)
        s, v = self._siren(h)
        if v is None:
            w = self._wave(h)
            if w:
                return w
        return s, v

    def _beacon(self, c):
        """비컨 상태가 올 때마다: 출동 중이면 이 차에 묶인 SIREN 위험을 찾거나(3 km 안의 비컨 없는 사이렌 위험에 붙이거나) 새로 만든다. 출동 끝이면 떼어 낸다"""
        now = self.now
        if c["s"] is not None:
            c["bt"] = [p for p in c["bt"] if now - p[0] <= EV_TRACK] + [(now, c["s"])]
        h = next((x for x in self.hazards if x["type"] == "SIREN" and x["beacon"] == c["id"]), None)
        if not c["on"] or c["s"] is None:
            if h:
                h["beacon"] = None
                if not h["reporters"] and not self._yields_live(h):
                    h["cleared"] = now
            return
        if h is None:
            h = next((x for x in self.hazards if x["type"] == "SIREN" and x["beacon"] is None
                      and abs(self._ev_pos(x)[0] - c["s"]) <= MERGE["SIREN"]), None)
            if h is None:
                self.seq += 1
                h = {"id": f"h{self.seq}", "type": "SIREN", "s": c["s"], "reporters": {}, "first": now, "rest": None, "notes": {}, "okOther": [],
                     "last": now, "value": "beacon", "cleared": None, "track": [], "beacon": None, "yields": {}}
                self.hazards.append(h)
            h["beacon"] = c["id"]
        h["last"], h["cleared"] = now, None

    def _yield(self, c):
        """YIELD(이 차가 급히 줄이며 오른쪽으로 비켰다): 3 km 안의 사이렌 위험이 있으면 근거로 붙이고, 없으면 모아 두었다가 물결이 되면 위험을 만든다"""
        now, s = self.now, c["s"]
        v = c["vs"] if c["vs"] is not None else c["speed"]
        h = next((x for x in self.hazards if x["type"] == "SIREN" and abs(self._ev_pos(x)[0] - s) <= MERGE["SIREN"]), None)
        if h:
            h["yields"][c["id"]] = (now, s, v)
            h["last"], h["cleared"] = now, None
            return
        self.yields = [y for y in self.yields if now - y[0] <= YIELD_WINDOW and y[3] != c["id"]] + [(now, s, v, c["id"])]
        near = [y for y in self.yields if abs(y[1] - s) <= MERGE["SIREN"]]
        if self._wave_pts(near) is None:
            return
        self.seq += 1
        last = max(near, key=lambda p: (p[0], p[1], p[3]))
        self.hazards.append({"id": f"h{self.seq}", "type": "SIREN", "s": last[1], "reporters": {}, "first": now, "rest": None, "notes": {}, "okOther": [],
                             "last": now, "value": "yield", "cleared": None, "track": [], "beacon": None,
                             "yields": {y[3]: (y[0], y[1], y[2]) for y in near}})
        self.yields = [y for y in self.yields if y not in near]

    # ---- 시연 도로: 1초 단위로 가상 차를 움직인다(요청 간격과 무관하게 같은 결과)
    def _world_speed(self, c, k):
        rel = c["s"] - self.demo["s0"]
        if c["demo"]["kind"] == "crash" and k < CRASH_END:
            return 0.0
        if JAM_TAIL <= rel <= JAM_HEAD and k < JAM_END:
            return JAM_MS
        return c["demo"]["free"]

    def _step(self, k):
        d = self.demo
        self.now = d["t0"] + k
        for c in [c for c in self.cars if c["demo"] and not c["gone"] and c["demo"]["kind"] != "ev"]:   # 시연 구급차(비컨)는 _ambulance 가 움직인다
            if k == 1 and c["demo"]["kind"] == "crash":
                self._event(c, "HARD_BRAKE", "crash")
            prev_rel = c["s"] - d["s0"]
            v = self._world_speed(c, k)
            c["s"] += v * DEMO_SCALE
            c["speed"], c["t"], c["vs"] = v, self.now, v * DEMO_SCALE   # vs: 경로 위 속도(길 터 주기 물결의 교통 흐름)
            rel = c["s"] - d["s0"]
            in_jam = JAM_TAIL <= rel <= JAM_HEAD and k < JAM_END
            was_jam = JAM_TAIL <= prev_rel <= JAM_HEAD
            if in_jam and not was_jam and c["demo"]["kind"] != "crash":
                c["speed"] = JAM_MS                      # 정체 꼬리에 닿으면 바로 정체 속도(앞에 닿은 차 몇 대는 급제동)
                if d["entries"] < BRAKE_ENTRIES:
                    d["entries"] += 1
                    self._event(c, "HARD_BRAKE", "jam tail")
            rain = RAIN_FROM <= rel <= RAIN_TO
            if rain != c["wiper"].startswith("CONTINUOUS"):
                c["wiper"] = "CONTINUOUS_3" if rain else "OFF"
                self._event(c, "HEAVY_RAIN" if rain else "HEAVY_RAIN_CLEARED", c["wiper"])
            if c["demo"]["kind"] != "crash":
                if prev_rel < DEBRIS_S <= rel:                           # 낙하물 지점을 지나며 핸들 급회피
                    self._event(c, "SWERVE", "steer")
                if DOWNHILL_FROM <= rel <= DOWNHILL_TO:                   # 긴 내리막: 브레이크를 계속 밟음
                    c["holdSince"] = self.now if c["holdSince"] is None else c["holdSince"]
                    if self.now - c["holdSince"] >= BRAKE_HOLD_SEC and c["holdSince"] > 0:
                        c["holdSince"] = -1.0                            # 한 번만 보고
                        self._event(c, "BRAKE_HOLD", f"{BRAKE_HOLD_SEC}s")
                else:
                    c["holdSince"] = None
                tunnel = TUNNEL_FROM <= rel <= TUNNEL_TO
                if tunnel != c.get("tunnel", False):
                    c["tunnel"] = tunnel
                    self._event(c, "RECIRC_ON" if tunnel else "RECIRC_OFF", "recirc")
                if prev_rel < TURNBACK_S <= rel:                         # 침수: 되돌아간다(도로에서 빠진다)
                    self._event(c, "TURNBACK", "reverse")
                    c["gone"], c["speed"] = True, 0.0
                    continue
            self._derive(c)
        self._ambulance(k)

    def _ambulance(self, k):
        """구급차: 정체 꼬리 뒤에서 나타나 사고 지점으로. 근거는 시연 호출의 ems 로 고른다(기본 셋 다):
        beacon = 구급차가 kind "ev" 차로 위치 신호를 보낸다(목적지 = 사고 지점), mic = 사이렌이 들리는 Tago 차가 5초마다 보고(차 안 마이크),
        yield = 구급차가 150 m 뒤로 다가온 Tago 차가 한 번 비킨다(YIELD)"""
        d = self.demo
        ems = d["ems"]
        if k == AMB_K:
            d["amb"] = {"s": d["s0"] + AMB_OFF, "on": True, "car": None}
            if "beacon" in ems:
                ev = self._new_car("", "", "ev", "ko", demo={"kind": "ev", "free": AMB_MS})
                if ev:
                    ev["s"], ev["speed"], ev["on"], ev["dest"] = d["s0"] + AMB_OFF, AMB_MS, True, d["s0"] + AMB_STOP
                    d["amb"]["car"] = ev["id"]
                    self._beacon(ev)
            for off, free in AMB_WITNESS:
                c = self._new_car("", "", "anon", "ko", demo={"kind": "anon", "free": free})
                if c:
                    c["s"], c["speed"] = d["s0"] + AMB_OFF + off, free
            return
        a = d["amb"]
        if not a or not a["on"]:
            return
        rel = a["s"] - d["s0"]
        v = AMB_JAM_MS if JAM_TAIL <= rel <= JAM_HEAD and k < JAM_END else AMB_MS
        a["s"] += v * DEMO_SCALE
        ev = self.car(a["car"]) if a["car"] else None
        if a["s"] - d["s0"] >= AMB_STOP:
            a["s"], a["on"] = d["s0"] + AMB_STOP, False                 # 사고 지점 도착: 사이렌을 끈다
            if ev:
                ev["s"], ev["speed"], ev["on"], ev["t"] = a["s"], 0.0, False, self.now   # 출동 끝(비컨도 끈다)
                self._beacon(ev)
            return
        if ev:
            ev["s"], ev["speed"], ev["t"] = a["s"], v, self.now
            self._beacon(ev)
        if "mic" in ems:
            for c in self.cars:
                if (c["demo"] and not c["gone"] and c["demo"]["kind"] not in ("crash", "ev") and abs(c["s"] - a["s"]) <= HEAR_M
                        and (c["sirenAt"] is None or self.now - c["sirenAt"] >= SIREN_EVERY)):
                    c["sirenAt"] = self.now
                    self._event(c, "SIREN", "mic")
        if "yield" in ems:
            for c in self.cars:
                if (c["demo"] and not c["gone"] and c["demo"]["kind"] not in ("crash", "ev") and c["yieldAt"] is None
                        and 0 < c["s"] - a["s"] <= YIELD_NEAR):
                    c["yieldAt"] = self.now
                    self._event(c, "YIELD", "demo")

    def _advance(self, t):
        d = self.demo
        if d:
            kmax = int(math.floor(t - d["t0"]))
            if kmax - d["k"] > MAX_STEPS:                 # 시계가 크게 뛰면(다른 시계의 요청 등) 그만큼 돌리지 않고 건너뛴다
                d["k"] = kmax - MAX_STEPS
            while d["k"] < kmax:
                d["k"] += 1
                self._step(d["k"])
        self.now = t
        keep = []
        for h in self.hazards:
            if h["type"] in STICKY and h["cleared"] is None and h["reporters"]:
                # 해제 신호 없이 사라진 차(앱 종료·통신 끊김)의 보고는 거둔다 — 보고한 차가 모두 사라지면 위험도 지운다
                for cid in [r for r, at in h["reporters"].items() if not self._alive(r, at)]:
                    del h["reporters"][cid]
                    c = self.car(cid)
                    if c:
                        c["active"].discard(h["type"])     # 다시 소식이 오면 새로 보고할 수 있게
                if not h["reporters"]:
                    continue
            end = h["cleared"] if h["cleared"] is not None else h["last"]
            if t - end < TTL[h["type"]] or (h["cleared"] is None and h["type"] in STICKY and h["reporters"]):
                keep.append(h)
        self.hazards = keep
        for o in [o for o in self.official if (o["end"] is not None and t >= o["end"]) or t - o["t"] >= OFFICIAL_TTL]:
            self.official.remove(o)
            if o["end"] is not None and t >= o["end"]:   # 공식 해제(endTime): 교차 확인됐던 사고 의심도 거둔다
                for h in self.hazards:
                    if h["type"] == "INCIDENT" and h["reporters"] and abs(h["s"] - o["s"]) <= OFFICIAL_NEAR:
                        for r in list(h["reporters"]):
                            c = self.car(r)
                            if c:
                                c["active"].discard("INCIDENT")
                                if c["inc"]:
                                    c["inc"]["closed"] = True
                        h["reporters"].clear()
                        h["cleared"] = t
        for code in [k for k, gid in self.codes.items() if gid not in self.groups or t - self.groups[gid]["codeAt"] >= CODE_TTL]:
            del self.codes[code]                         # 30분 지난 참가 코드는 닫는다
        for g in self.groups.values():                   # 시연 차(가족)도 움직이므로 시계가 갈 때마다 여정을 맞춘다
            self._journey(g)

    def demo_road(self, body):
        self.clock(body)
        if self.demo:
            return
        me = self.car(body.get("me"))
        s0 = me["s"] if me and me["s"] is not None else 18000.0
        ems = body.get("ems")
        self.demo = {"t0": self.now, "s0": s0, "k": 0, "entries": 0, "amb": None,
                     "ems": set(EMS_ALL) if not isinstance(ems, str) or ems in ("", "all") else {p for p in re.split(r"[,+ ]", ems) if p in EMS_ALL}}
        for kind, off, free in DEMO_CARS:
            c = self._new_car("", "", "anon", "ko", demo={"kind": kind, "free": free})
            if c:
                c["s"], c["speed"] = s0 + off, free

    # ---- 가족 그룹(선택)
    def _glog(self, g, ko, en):
        g["log"].append({"t": r1(self.now), "ko": ko, "en": en})
        del g["log"][:-30]

    def create_group(self, body):
        self.clock(body)
        c = self.car(body.get("me"))
        if not c:
            return None
        # 그룹은 GROUP_MAX개까지(시연은 한두 개면 된다) — 넘치면 가장 오래된 그룹과 코드를 지운다. 100번 뽑아도 비지 않으면 포기한다(무한 루프 방지)
        while len(self.groups) >= GROUP_MAX:
            self._drop_group(next(iter(self.groups)))
        for _ in range(100):
            gid = self._id(6)
            if gid not in self.groups:
                break
        for _ in range(100):
            code = self._id(4, "0123456789")
            if code not in self.codes:
                break
        if gid in self.groups or code in self.codes:
            return None
        g = {"id": gid, "code": code, "codeAt": self.now, "wrong": 0, "members": [c["id"]], "rest": None, "answers": {}, "log": [],
             "demo": False, "journey": {"ride": c["id"], "acts": [], "seq": 0, "planned": None, "changed": None, "stepsBy": ""}}
        self.groups[gid], self.codes[code] = g, gid
        c["group"] = gid
        name, desc = clean(body.get("name") or "", NAME_MAX), clean(body.get("car") or "", CAR_MAX)
        if name:
            c["name"] = name
        if desc:
            c["car"] = desc
        self._glog(g, f"{c['name']} 님이 그룹을 만들었어요", f"{c['name']} started the group")
        return g

    def _code_ok(self, g):
        return self.codes.get(g["code"]) == g["id"] and self.now - g["codeAt"] < CODE_TTL

    def lock_left(self, body):
        """코드 합류 잠금이 풀리기까지 남은 초(올림, 1 이상) — join_group 과 같은 칸(차 id, 없으면 휴대폰 공용 칸)"""
        me = self.car(body.get("me"))
        tr = self.tries.get(me["id"] if me else "")
        return max(1, math.ceil(tr["until"] - self.now)) if tr else int(JOIN_LOCK)

    def join_group(self, body):
        """코드로 합류. 돌려주는 값: (그룹, 차) 또는 (None, 까닭 "code"·"locked"·"full")"""
        self.clock(body)
        me = self.car(body.get("me"))
        key = me["id"] if me else ""                     # 차 id 없는 참가(휴대폰 웹)는 한 칸을 같이 쓴다(아무 id나 지어내 칸을 늘리지 못하게)
        tr = self.tries.get(key)
        if tr and self.now < tr["until"]:
            return None, "locked"
        gid = self.codes.get(str(body.get("code", "")))
        g = self.groups.get(gid) if gid else None
        if not g or not self._code_ok(g):
            tr = self.tries.setdefault(key, {"n": 0, "until": 0.0})
            tr["n"] += 1
            if tr["n"] >= JOIN_TRIES:
                tr["n"], tr["until"] = 0, self.now + JOIN_LOCK
            for x in self.groups.values():               # 틀린 시도는 살아 있는 모든 코드의 몫으로 센다 → 코드 하나에 쓸 수 있는 시도 수가 정해진다
                if self.codes.get(x["code"]) == x["id"]:
                    x["wrong"] += 1
                    if x["wrong"] >= CODE_WRONG_MAX:
                        del self.codes[x["code"]]        # 너무 많이 틀렸다 → 이 코드는 닫는다(이미 합류한 사람은 그대로)
            return None, "code"
        c = me or self._new_car(clean(body.get("name") or "", NAME_MAX) or "?", clean(body.get("car") or "", CAR_MAX),
                                ("web" if (k := clean(body.get("kind") or "", KIND_MAX)) in ("", "ev") else k),   # 긴급차량(ev)은 토큰을 보는 /api/road/join 으로만(앱과 같다)
                                lang_of(body.get("lang")))
        if not c:
            return None, "full"
        self.tries.pop(key, None)
        name = clean(body.get("name") or "", NAME_MAX)
        if name:
            c["name"] = name
        c["group"] = gid
        if c["id"] not in g["members"]:
            g["members"].append(c["id"])
        self._glog(g, f"{c['name']} 님이 합류했어요", f"{c['name']} joined")
        return g, c

    def demo_group(self, g, body):
        self.clock(body)
        if g["demo"]:
            return
        if not self.demo:
            self.demo_road(body)
        g["demo"] = True
        d = self.demo
        me = self.car(body.get("me"))
        lang = me["lang"] if me else "ko"
        for ko, en, desc, desc_en, off, free, soc in DEMO_FAMILY:
            c = self._new_car(ko if lang == "ko" else en, desc if lang == "ko" else desc_en, "pleos", lang, demo={"kind": "family", "free": free})
            if not c:
                continue
            c["s"], c["speed"], c["soc"], c["group"] = d["s0"] + off + free * DEMO_SCALE * d["k"], free, soc, g["id"]
            g["members"].append(c["id"])
            self._glog(g, f"{ko} 님이 합류했어요", f"{en} joined")

    def rest(self, g, body):
        self.clock(body)
        c = self.car(body.get("me"))
        group = [x for x in (self.car(i) for i in g["members"]) if x and x["s"] is not None]
        if not c or not group:
            return
        front = max(x["s"] for x in group)
        nxt = next((r for r in REST if r["kind"] == "services" and r["s"] >= front + REST_AHEAD), None)
        g["answers"] = {}
        for a in g["journey"]["acts"]:
            if a["type"] == "rest" and a["state"] == "proposed":
                a["state"] = "cancelled"                      # 새 제안이 앞 제안을 대신한다
        if not nxt:
            g["rest"] = {"by": c["id"], "none": True}
            return
        g["rest"] = {"by": c["id"], "name": nxt["name"], "nameEn": nxt["nameEn"], "s": nxt["s"], "lat": nxt["lat"], "lon": nxt["lon"]}
        g["answers"][c["id"]] = True
        for x in group:
            if x["demo"]:
                g["answers"][x["id"]] = True                 # 시연 일행은 바로 "좋아요"
        self._act(g, "rest", "rest", nxt["name"], c["name"], "lead_1km", {"name": nxt["name"], "nameEn": nxt["nameEn"], "s": nxt["s"]})
        self._glog(g, f"{c['name']} 님 제안: 다같이 {nxt['name']}", f"{c['name']} suggests: everyone stop at {nxt['nameEn']}")
        self._journey(g)

    def rest_answer(self, g, body):
        self.clock(body)
        if g["rest"] and not g["rest"].get("none") and self._member(g, body):   # 일행만 답한다(아무 id나 쌓이지 않게)
            g["answers"][body["me"]] = bool(body.get("yes"))

    # ---- 여정: 할 일(act) 공통 처리
    def _act(self, g, typ, kind, label, by, basis, place=None):
        j = g["journey"]
        j["seq"] += 1
        a = {"id": f"a{j['seq']}", "type": typ, "kind": kind, "label": label, "state": "proposed" if typ == "rest" else "pending",
             "by": by, "basis": basis, "place": place, "how": None, "doneBy": "", "at": None}
        j["acts"].append(a)
        return a

    def _done(self, a, how, who):
        a["state"], a["how"], a["doneBy"], a["at"] = "done", how, who, r1(self.now)

    def _steps(self, g):
        return [a for a in g["journey"]["acts"] if a["type"] == "step" and a["state"] != "cancelled"]

    def _rest_target(self, g, c):
        """쉬어 갈 곳(장소 조건): 일행이 정한 휴게소, 없으면 타고 있는 차 앞의 다음 휴게소"""
        R = g["rest"]
        if R and not R.get("none"):
            return {"name": R["name"], "nameEn": R["nameEn"], "s": R["s"], "basis": "agreed"}
        if not c or c["s"] is None:
            return None
        r = next((r for r in REST if r["kind"] == "services" and r["s"] > c["s"]), None)
        return {"name": r["name"], "nameEn": r["nameEn"], "s": r["s"], "basis": "next"} if r else None

    def _journey(self, g):
        """차 관측으로 끝나는 할 일만 끝낸다: 정한 휴게소에 일행 차가 섰다 / 타고 있는 차가 출발·휴게소 정차·도착했다.
        사람이 하는 일(task)은 건드리지 않는다(차가 섰다고 화장실에 다녀온 것은 아니다)"""
        j = g["journey"]
        for a in j["acts"]:
            if a["type"] == "rest" and a["state"] == "proposed":
                x = next((x for x in (self.car(i) for i in g["members"]) if x and x["s"] is not None and x["speed"] < STOP_MS
                          and abs(x["s"] - a["place"]["s"]) <= NEAR_STOP), None)
                if x:
                    self._done(a, "vehicle", x["name"])
        c = self.car(j["ride"])
        if not c or c["s"] is None:
            return
        target = self._rest_target(g, c)
        steps = self._steps(g)
        for a in steps:
            if a["state"] == "done":
                continue
            k = a["kind"]
            ok = ((k == "board" and c["speed"] >= MOVE_MS)
                  or (k == "rest" and target is not None and c["speed"] < STOP_MS and abs(target["s"] - c["s"]) <= NEAR_STOP)
                  or (k == "arrive" and c["speed"] < STOP_MS and c["s"] >= LENGTH - ARRIVE_NEAR))
            if not ok:
                break
            self._done(a, "vehicle", c["name"])
        # 쉬어 갈 곳이 바뀌면 알린다(휴게소 카드가 남아 있을 때) — 누군가 '알겠어요'를 누를 때까지 남긴다
        if target and any(a["kind"] == "rest" and a["state"] != "done" for a in steps):
            if j["planned"] is None:
                j["planned"] = target
            elif j["planned"]["name"] != target["name"] and (j["changed"] is None or j["changed"]["to"]["name"] != target["name"]):
                j["changed"] = {"from": j["planned"], "to": target}

    def _member(self, g, body):
        c = self.car(body.get("me"))
        return c if c and c["id"] in g["members"] else None

    def set_steps(self, g, body):
        """다음 한 단계 카드 정하기(보호자). 알 수 없는 종류는 버리고, 글자는 24자까지. 새로 정하면 앞 카드는 취소된다"""
        self.clock(body)
        c = self._member(g, body)
        if not c or not isinstance(body.get("steps"), list):
            return
        steps = []
        for s in body["steps"][:50]:                     # 걸러 낸 뒤 6장까지(잘못된 카드가 앞의 자리를 차지하지 않게)
            if isinstance(s, dict) and s.get("kind") in STEP_KINDS:
                label = str(s.get("label") or "").strip()[:STEP_LABEL_MAX]
                if label:
                    steps.append((s["kind"], label))
            if len(steps) == STEP_MAX:
                break
        j = g["journey"]
        for a in self._steps(g):
            a["state"] = "cancelled"
        for kind, label in steps:
            self._act(g, "step", kind, label, c["name"], None)
        j["stepsBy"], j["planned"], j["changed"] = c["name"], None, None
        self._glog(g, f"{c['name']} 님이 다음 단계 카드 {len(steps)}장을 정했어요", f"{c['name']} set {len(steps)} next-step cards")
        self._journey(g)

    def step_done(self, g, body):
        """카드 하나를 '했어요'(사람 확인) 또는 되돌리기"""
        self.clock(body)
        c = self._member(g, body)
        i = body.get("i")
        steps = self._steps(g)
        if not c or isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(steps):
            return
        a = steps[i]
        if body.get("done", True):
            self._done(a, "person", c["name"])
            self._glog(g, f"{c['name']}: {a['label']} 했어요", f"{c['name']}: done — {a['label']}")
        else:
            a["state"], a["how"], a["doneBy"], a["at"] = "pending", None, "", None

    def journey_ride(self, g, body):
        """동승자가 타고 있는 차(사람의 선택). 카드의 차 관측은 이 차를 따른다"""
        self.clock(body)
        c = self._member(g, body)
        ride = body.get("ride")                          # 보기에 나온 id(남의 차는 pub) 또는 내 id
        r = next((x for x in (self.car(i) for i in g["members"]) if x and ride in (x["id"], x["pub"])), None)
        if not c or not r:
            return
        j = g["journey"]
        j["ride"], j["planned"], j["changed"] = r["id"], None, None
        self._glog(g, f"{c['name']}: {r['name']} 차에 타요", f"{c['name']}: riding in {r['name']}'s car")
        self._journey(g)

    def journey_ack(self, g, body):
        """'쉬는 곳이 바뀌었어요'를 확인했다"""
        self.clock(body)
        j = g["journey"]
        if self._member(g, body) and j["changed"]:
            j["planned"], j["changed"] = j["changed"]["to"], None

    # ---- 보기(차 한 대 기준)
    def view(self, mid):
        self._scan_comm_loss()
        me = self.car(mid)
        lang = me["lang"] if me else "ko"
        self.cur_units = me["units"] if me else "km"
        my_s = me["s"] if me and me["s"] is not None else None
        my_v = me["speed"] if me else 0.0
        g = self.groups.get(me["group"]) if me and me["group"] else None
        mine = set(g["members"]) if g else set()
        # 긴급차량 비컨(kind "ev")은 길벗 차가 아니다: 주변 차 수·앞길 미리보기에 넣지 않는다
        others = [c for c in self.cars if c["id"] != mid and c["s"] is not None and self.now - c["t"] <= ACTIVE_SEC and not c["gone"] and c["kind"] != "ev"]
        nearby = 0 if my_s is None else len([c for c in others if abs(c["s"] - my_s) <= ALERT_RANGE])
        hazards = []
        for h in self.hazards:
            siren = h["type"] == "SIREN"
            reps = sorted(h["reporters"])
            evc = wave = None
            ny = 0
            if siren:
                evc, wave, ny = self._ev(h), self._wave(h), len(self._yields_live(h))
                if evc is None and not reps and not ny:
                    continue                             # 비컨이 꺼졌고 마이크·비킴 근거도 없다
                if evc is not None and evc["id"] == mid:
                    continue                             # 구급차 자신에게는 알리지 않는다
                if reps == [mid] and evc is None and wave is None:
                    continue                             # 나만 들은 사이렌(비컨·물결 없이)은 나에게 안 알린다
            else:
                if not h["reporters"] and h["cleared"] is not None:
                    continue
                if reps == [mid]:
                    continue                             # 나만 보고한 것은 나에게 안 알린다
            hs, hv = self._ev_pos(h) if siren else (h["s"], None)
            ahead = None if my_s is None else hs - my_s
            named = [self.car(r)["name"] for r in (g["members"] if g else []) if r in h["reporters"] and r != mid]   # 일행 합류 순서(차 id는 무작위라 id 순서는 뜻이 없다)
            anon = len([r for r in reps if r not in mine and r != mid])
            inc_score = max(h.get("score", {}).values(), default=0) if h["type"] == "INCIDENT" else 0
            strong = h["type"] == "INCIDENT" and any(self._strong(r, h) for r in reps)
            off = self._official_near(h["s"]) if h["type"] == "INCIDENT" else None   # 공식 돌발 ±2 km = 공식 확인
            ch = self._charge_info(h) if h["type"] == "CHARGER_FAULT" else None
            # 충전기 고장: 다른 차 2대(사람 신고·차 실패 보고 섞여도) 또는 한 차가 신고하고 다른 자리에서는 충전됨(차는 멀쩡, 그 기기 고장) = 확정
            confirmed = bool(named) or len(reps) >= ANON_CONFIRM or strong or off is not None or bool(ch and ch["strong"]) or (h["type"] == "CHARGER_FAULT" and self._chg_off(h["s"]) is not None)
            if siren:                                    # 비컨은 바로 확정, 물결은 3대 또는 마이크와 함께
                confirmed = evc is not None or confirmed or (wave is not None and (ny >= YIELD_CONFIRM or len(reps) >= 1))
            level = 2 if ((len(reps) >= 3 and h["type"] in LEVEL_UP) or inc_score >= INC_STRONG or strong or off is not None) else 1
            item = {"id": h["id"], "type": h["type"], "label": TYPE_KO[h["type"]] if lang == "ko" else TYPE_EN[h["type"]], "s": rnd(hs), "pos": point_at(hs),
                    "ahead": None if ahead is None else rnd(ahead), "by": named, "anon": anon, "cars": len(reps),
                    "confirmed": confirmed, "level": level, "age": rnd(self.now - h["first"])}
            if h["type"] == "INCIDENT":
                tags = [t for t in INC_ORDER if any(t in v for v in h.get("ev", {}).values())]
                item["evidence"], item["score"] = tags, inc_score
                item["partial"] = 0 < len(h.get("passed", ())) < CLEAR_PASS
                item["queueWarn"] = True                 # 교통 막힘 주의(DENM dangerousEndOfQueue 27)
                item["official"] = self._official_item(lang, off) if off else None
                zn = self._zone_at(h["s"])
                item["zone"] = zn["id"] if zn else None
                if off:                                  # 공식 확인이면 이름표도 '의심'을 뗀다
                    item["label"] = L(lang, f"{OFFICIAL_KO[off['type']]}(도로 정보 확인)", f"{OFFICIAL_EN[off['type']]} (road authority)")
            if ch:
                item["charger"] = {k: ch[k] for k in ("human", "fail", "moved", "other", "units", "place", "sym", "broken", "altYes")}
                if ch["human"]:
                    item["label"] = self._charge_label(lang, ch)
                co = self._chg_off(h["s"])
                if co:
                    item["chargerOfficial"] = self._chg_off_json(lang, co)
            if h["type"] in CAUSE_CODE:
                item["causeCode"] = CAUSE_CODE[h["type"]]
            item["informationQuality"] = 7 if off else min(7, inc_score + len(reps))
            self._denm(item, h["last"], self._expiry(h), (EV_RANGE if evc is not None else SIREN_RANGE) if siren else ALERT_RANGE)
            if siren:
                # 뒤에서 다가오는 긴급차량만(반대 차로·지나간 차는 말하지 않는다). 방향을 알기 전에는 화면에만
                yonly = evc is None and not reps and wave is not None
                mv = EV_MOVE if evc is not None else 0.0      # 비컨은 GPS 흔들림만큼 여유를 둔다
                item["oncoming"] = hv is not None and hv < -mv
                behind = None if ahead is None else -ahead
                closing = None if hv is None or me is None else hv - (me["vs"] if me["vs"] is not None else my_v)
                eta = behind / closing if behind is not None and closing is not None and closing > 1 and behind > 0 else None
                item["eta"] = None if eta is None else rnd(eta)
                item["evidence"] = [x for x, ok in (("beacon", evc is not None), ("mic", bool(reps)), ("yield", wave is not None)) if ok]
                item["beacon"], item["yielded"], item["yieldOnly"] = evc is not None, ny, yonly
                dest = evc["dest"] if evc is not None else None
                item["dest"] = None if dest is None else rnd(dest - hs)   # 구급차가 목적지까지 남은 거리(예상 경로)
                on_path = dest is None or (my_s is not None and my_s <= dest + EV_DEST_MARGIN)
                item["onPath"] = on_path
                if evc is not None:
                    item["label"] = L(lang, "구급차(위치 신호)", "Ambulance (position beacon)")
                    item["informationQuality"] = 7
                elif yonly:
                    item["label"] = L(lang, "긴급차량 추정", "Possible emergency vehicle")
                    item["informationQuality"] = min(7, ny)
                elif ny:
                    item["informationQuality"] = min(7, len(reps) + ny)
                rng = EV_RANGE if evc is not None else SIREN_RANGE
                if behind is not None and 0 < behind <= rng:
                    item["level"] = 2 if behind <= SIREN_NEAR else 1
                    if confirmed and hv is not None and hv > mv and on_path and (evc is None or (closing is not None and closing > 0)):
                        item["say"] = (self._ev_sentence(lang, behind, eta) if evc is not None else
                                       self._yield_sentence(lang, behind) if yonly else
                                       self._siren_sentence(lang, behind, named, anon, len(reps), eta))
                hazards.append(item)
                continue
            # 폭우는 따로 말하지 않는다: '비 예보'(ahead.rain)가 같은 내용을 미리 말한다
            if ahead is not None and 0 < ahead <= ALERT_RANGE and confirmed and (h["type"] != "HEAVY_RAIN" or named):
                wet = h["type"] == "BLOCKED" and any(x["type"] == "HEAVY_RAIN" and len(x["reporters"]) >= ANON_CONFIRM
                                                     and abs(x["s"] - h["s"]) <= RAIN_NEAR for x in self.hazards)
                item["say"] = (self._charge_sentence(lang, ahead, h.get("rest"), named, anon, len(reps), ch, self._chg_off(h["s"])) if ch else
                               self._sentence(lang, h["type"], ahead, named, anon, len(reps), wet, h.get("rest"), h["value"],
                                              item.get("evidence"), level, item.get("partial", False), off,
                                              self._zone_at(h["s"]) if h["type"] == "INCIDENT" else None))
                if wet:
                    item["flood"] = True
            if h.get("rest"):
                item["rest"] = h["rest"]["name"] if lang == "ko" else h["rest"]["nameEn"]
            hazards.append(item)
        for r in REST:                               # 차 보고가 없는 휴게소의 충전기 공식 운영중지·점검중: 충전기 고장처럼 안내(10 km 안에서 말함)
            if r["kind"] != "services":
                continue
            co = self._chg_off(r["s"])
            if not co or any(h["type"] == "CHARGER_FAULT" and h["reporters"] and abs(h["s"] - r["s"]) <= CHARGER_NEAR for h in self.hazards):
                continue
            ahead = None if my_s is None else r["s"] - my_s
            rn = r["name"] if lang == "ko" else r["nameEn"]
            kind = self._chg_kind(lang, co)
            item = {"id": f"chg{rnd(r['s'])}", "type": "CHARGER_FAULT", "label": L(lang, f"충전기 {co['down']}대 {kind}(공식)", f"{co['down']} chargers {kind} (official)"),
                    "s": rnd(r["s"]), "pos": point_at(r["s"]), "ahead": None if ahead is None else rnd(ahead), "by": [], "anon": 0, "cars": 0,
                    "confirmed": True, "level": 1, "age": rnd(self.now - co["t"]), "rest": rn, "chargerOfficial": self._chg_off_json(lang, co), "informationQuality": 7}
            self._denm(item, co["t"], co["t"] + CHG_OFFICIAL_TTL, ALERT_RANGE)
            if ahead is not None and 0 < ahead <= ALERT_RANGE:
                item["say"] = self._chg_off_sentence(lang, ahead, rn, co)
            hazards.append(item)
        for o in self.official:                      # 사고 의심이 없는 공식 돌발: 화면에만(순정 내비가 이미 말한다)
            if any(h["type"] == "INCIDENT" and h["reporters"] and abs(h["s"] - o["s"]) <= OFFICIAL_NEAR for h in self.hazards):
                continue
            ahead = None if my_s is None else o["s"] - my_s
            kind = L(lang, OFFICIAL_KO[o["type"]], OFFICIAL_EN[o["type"]])
            item = {"id": o["id"], "type": "OFFICIAL", "label": L(lang, f"도로 정보: {kind}", f"Road info: {kind}"), "s": rnd(o["s"]), "pos": point_at(o["s"]),
                    "ahead": None if ahead is None else rnd(ahead), "by": [], "anon": 0, "cars": 0, "confirmed": True, "level": 1,
                    "age": rnd(self.now - o["first"]), "official": self._official_item(lang, o), "causeCode": OFFICIAL_CAUSE[o["type"]], "informationQuality": 7}
            self._denm(item, o["t"], self._official_expiry(o), ALERT_RANGE)
            hazards.append(item)
        hazards.sort(key=lambda h: (h["ahead"] if h["ahead"] is not None else math.inf, h["id"]))
        spoken = []
        for h in sorted((h for h in hazards if "say" in h), key=lambda h: (PRIORITY[h["type"]], h["ahead"], h["id"])):
            if any(abs(h["s"] - o["s"]) <= MERGE_M for o in spoken):
                del h["say"]                             # 같은 곳의 덜 중요한 위험은 화면에만
            else:
                spoken.append(h)
        ahead = self._ahead(lang, my_s, my_v, others, hazards, me["limit"] if me else None) if my_s is not None else None
        rest_next = None
        if my_s is not None:
            r = next((r for r in REST if r["s"] > my_s), None)
            if r:
                rest_next = {"name": r["name"] if lang == "ko" else r["nameEn"], "kind": r["kind"], "dist": rnd(r["s"] - my_s),
                             "charger": self._charger_at(r)}
        group = self._group_view(g, mid, lang, my_s) if g else None
        risk = self._risk(me, my_s, hazards, ahead)
        out = {"me": mid, "lang": lang, "now": r1(self.now), "s": None if my_s is None else rnd(my_s), "routeLength": rnd(LENGTH), "risk": risk,
               "nearby": nearby, "hazards": hazards, "zones": self._zones_view(lang, me, my_s), "ahead": ahead, "restNext": rest_next, "restHere": self._rest_here(lang, my_s), "group": group,
               "brief": self._brief(lang, nearby, group, rest_next), "demo": self.demo is not None,
               "clockSkew": me["skew"] if me else None, "units": self.cur_units}   # clockSkew: 내 시계 오차(초, 없으면 null) — 앱은 기록만
        if me and me["kind"] == "ev":
            out["ev"] = self._ev_view(me, others)
        return out

    def _ev_view(self, c, others):
        """구급차 휴대폰 화면: 출동 여부·목적지까지 남은 거리·지금 알리는 차 수(뒤 5 km 안 같은 방향·목적지 앞)·마이크로 들은 차·비킨 차"""
        h = next((x for x in self.hazards if x["type"] == "SIREN" and x["beacon"] == c["id"]), None)
        live = h is not None and self._ev(h) is not None
        v = self._beacon_v(c) if live else None
        told = 0
        if live and v is not None and v > EV_MOVE:
            told = len([x for x in others if 0 < x["s"] - c["s"] <= EV_RANGE
                        and (c["dest"] is None or x["s"] <= c["dest"] + EV_DEST_MARGIN)
                        and v - (x["vs"] if x["vs"] is not None else x["speed"]) > 0])
        return {"on": c["on"], "live": live, "dest": None if c["dest"] is None else rnd(c["dest"]),
                "toDest": None if c["dest"] is None or c["s"] is None else rnd(c["dest"] - c["s"]),
                "v": None if v is None else r1(v), "told": told, "heard": len(h["reporters"]) if live else 0,
                "yielded": len(self._yields_live(h)) if live else 0}

    def _zone_limit(self, s):
        """경로 파일 구역의 제한속도(zones[].limit, km/h) 중 s 를 품은 것의 최소 — 지금은 자료가 없어 늘 None(build_zones.py ZONE_LIMITS)"""
        lims = [z["limit"] for z in ZONES if z.get("limit") and z["s0"] <= s <= z["s1"]]
        return min(lims) if lims else None

    def _ahead(self, lang, my_s, my_v, others, hazards, limit=None):
        """앞길 미리보기: 500m 칸마다 앞차들의 평균 속도·와이퍼·위험. 첫 정체 칸이면 권장 속도(제한속도가 더 낮으면 그 값까지), 첫 비 칸이면 비 예보"""
        bins = []
        for i in range(BINS):
            lo, hi = my_s + i * BIN_M, my_s + (i + 1) * BIN_M
            cs = [c for c in others if lo < c["s"] <= hi]
            hz = sorted({h["type"] for h in hazards if h["confirmed"] and lo < h["s"] <= hi}, key=lambda t: PRIORITY[t])
            bins.append({"cars": len(cs), "kmh": rnd(sum(c["speed"] for c in cs) / len(cs) * 3.6) if cs else None,
                         "rain": len([c for c in cs if c["wiper"].startswith("CONTINUOUS")]), "hz": hz})
        advice = None
        my_kmh = my_v * 3.6
        for i, b in enumerate(bins):
            if b["cars"] >= 2 and b["kmh"] is not None and b["kmh"] < JAM_KMH:
                d = i * BIN_M
                adv10 = ADVISE_KMH        # 일률 80: 따르는 차와 안 따르는 차의 속도 차를 키우지 않게
                lim = self._zone_limit(my_s + d) or limit   # 제한속도(ADR-44): 꼬리가 든 구역의 값이 먼저, 없으면 차가 보낸 순정 내비 값
                if lim and lim < adv10:
                    adv10 = lim
                advice = {"dist": rnd(d), "jamS": rnd(my_s + d), "jamKmh": b["kmh"], "adviseKmh": adv10}
                if d >= BIN_M and my_kmh >= adv10 + 8:
                    advice["say"] = L(lang, f"전방 {self.km_text(lang, d)} 정체 시작. 지금부터 시속 {adv10}까지 서서히 줄이세요.",
                                      f"Slow traffic in {self.km_text(lang, d)}. Ease off to {adv10} km/h now.")
                break
        # 비 예보: 앞쪽에서 와이퍼를 켠 차가 2대 이상 확인된 지점(폭우 위험) — 하늘 대신 앞차들로
        rain = None
        wet = [h for h in hazards if h["type"] == "HEAVY_RAIN" and h["confirmed"] and h["ahead"] is not None and 0 < h["ahead"] <= ALERT_RANGE]
        if wet:
            h = min(wet, key=lambda h: (h["ahead"], h["id"]))
            eta = h["ahead"] / max(my_v, 8.3)
            m = max(1, rnd(eta / 60))
            rain = {"dist": h["ahead"], "eta": rnd(eta), "cars": h["cars"], "id": h["id"],
                    "say": L(lang, f"약 {m}분 후 강우 예상. 전방 차량 {h['cars']}대 와이퍼 작동 중.",
                             f"Rain expected in about {m} min. {h['cars']} cars ahead have wipers on.")}
        return {"bin": rnd(BIN_M), "bins": bins, "advice": advice, "rain": rain}

    def _group_view(self, g, mid, lang, my_s):
        members = []
        for cid in g["members"]:
            x = self.car(cid)
            gap = None if (my_s is None or x["s"] is None) else x["s"] - my_s
            members.append({"id": self._pid(x, mid), "name": x["name"], "car": x["car"], "kind": x["kind"], "me": x["id"] == mid,
                            "s": None if x["s"] is None else rnd(x["s"]), "pos": None if x["s"] is None else point_at(x["s"]),
                            "gap": None if gap is None else rnd(gap), "gapMin": None if gap is None else rnd(abs(gap) / CRUISE_MS / 60),
                            "speedKmh": rnd(x["speed"] * 3.6), "soc": x["soc"],
                            "status": "stopped" if x["speed"] < STOP_MS else "slow" if x["speed"] < SLOW_MS else "moving"})
        rest = None
        R = g["rest"]
        if R:
            if R.get("none"):
                rest = {"none": True, "say": L(lang, "전방에 일행이 함께 들를 휴게소가 없습니다.", "No rest area ahead for the group.")}
            else:
                nm = R["name"] if lang == "ko" else R["nameEn"]
                by = self.car(R["by"])
                d = None if my_s is None else rnd(R["s"] - my_s)
                rest = {"name": nm, "s": R["s"], "pos": [R["lat"], R["lon"]], "dist": d, "by": by["name"] if by else "",
                        "mine": R["by"] == mid, "answered": mid in g["answers"],
                        "yes": [self.car(i)["name"] for i in g["members"] if g["answers"].get(i)],
                        "pending": [self.car(i)["name"] for i in g["members"] if i not in g["answers"]]}
                where = "" if d is None else L(lang, f" {self.km_text(lang, d)} 전방.", f", {self.km_text(lang, d)} ahead")
                rest["say"] = (L(lang, f"{nm} 경유 요청을 일행에게 보냈습니다.{where}", f"Sent the group a request to stop at {nm}{where}.") if R["by"] == mid
                               else L(lang, f"{rest['by']} 님이 {nm} 경유를 제안했습니다.{where} 경유할까요?",
                                      f"{rest['by']} suggests a stop at {nm}{where}. Stop there?"))
        j = g["journey"]
        return {"id": g["id"], "code": g["code"] if self._code_ok(g) else None, "members": members, "rest": rest,
                "steps": [{"kind": a["kind"], "label": a["label"], "done": a["state"] == "done", "how": a["how"], "doneBy": a["doneBy"]}
                          for a in self._steps(g)],
                "stepsBy": j["stepsBy"], "journey": self._journey_view(g, lang, mid), "log": [L(lang, x["ko"], x["en"]) for x in g["log"][-8:]]}

    def _journey_view(self, g, lang, mid):
        """여정 보기: 차량 관측(observed) · 장소 조건(place) · 할 일(acts: 서비스 판단의 근거, 사람의 선택, 끝난 방법) · 바뀐 계획(changed)"""
        j = g["journey"]
        ride = self.car(j["ride"])
        target = self._rest_target(g, ride)
        nm = lambda p: p["name"] if lang == "ko" else p["nameEn"]
        acts = []
        for a in j["acts"]:
            if a["state"] == "cancelled":
                continue
            st = a["state"]
            if a["type"] == "rest" and st == "proposed":     # 수락은 사람의 선택: 모두 답했으면 합의(agreed) 또는 갈림(split)
                pending = [i for i in g["members"] if i not in g["answers"]]
                st = "proposed" if pending else "agreed" if all(g["answers"][i] for i in g["members"]) else "split"
            acts.append({"id": a["id"], "type": a["type"], "kind": a["kind"], "label": nm(a["place"]) if a["place"] else a["label"],
                         "state": st, "by": a["by"], "basis": L(lang, *BASIS[a["basis"]]) if a["basis"] else "",
                         "how": a["how"], "doneBy": a["doneBy"], "at": a["at"]})
        has_s = ride is not None and ride["s"] is not None
        return {"ride": None if not ride else {"id": self._pid(ride, mid), "name": ride["name"]},
                "observed": None if not has_s else {"s": rnd(ride["s"]), "kmh": rnd(ride["speed"] * 3.6), "stopped": ride["speed"] < STOP_MS,
                                                    "age": r1(self.now - ride["t"])},
                "place": None if not target else {"name": nm(target), "s": rnd(target["s"]), "dist": rnd(target["s"] - ride["s"]) if has_s else None,
                                                  "basis": L(lang, *BASIS[target["basis"]])},
                "acts": acts,
                "changed": None if not j["changed"] else {"from": nm(j["changed"]["from"]), "to": nm(j["changed"]["to"])}}

    def _sentence(self, lang, typ, ahead, named, anon, cars, wet=False, rest=None, value="", evidence=None, level=1, partial=False, official=None, zone=None):
        """서비스 톤 한 문장: '전방 Xkm {무엇}. {누가} 확인. {행동}.' — 짧고 격식 있게(내비 안내체). 충전 위험은 휴게소 이름을 넣는다"""
        where = L(lang, f"전방 {self.km_text(lang, ahead)}", f"{self.km_text(lang, ahead)} ahead")
        if typ == "INCIDENT" and official:                # 공식 확인: '의심'을 떼고 짧게
            kind = L(lang, OFFICIAL_KO[official["type"]], OFFICIAL_EN[official["type"]])
            return L(lang, f"{where} {kind} 구간(도로 정보 확인). 서행하세요.", f"{where}, {kind} confirmed by road authority. Drive slowly.")
        rn = (rest["name"] if lang == "ko" else rest["nameEn"]) if rest else ""
        mins = value if value.isdigit() else "?"
        if named:
            who = L(lang, f"{named[0]} 차량 외 {anon}대" if anon else f"{named[0]} 차량",
                    f"{named[0]}'s car and {anon} more" if anon else f"{named[0]}'s car")
        else:
            who = L(lang, f"차량 {cars}대", f"{cars} cars")
        what = {"HARD_BRAKE": L(lang, "급제동 구간", "hard braking"), "CONGESTION": L(lang, "정체 구간", "slow traffic"),
                "INCIDENT": L(lang, "사고 다발 구간, 사고 의심", "accident-prone section, possible crash") if zone else L(lang, "사고 의심 구간", "possible crash"),
                "HEAVY_RAIN": L(lang, "폭우 구간", "heavy rain"),
                "ICING": L(lang, "결빙 주의 구간", "possible ice"),
                "BLOCKED": L(lang, "침수 의심 구간" if wet else "통행 불가 의심 구간", "possible flooding" if wet else "possible road block"),
                "DEBRIS": L(lang, "낙하물 의심 구간", "possible debris"), "SMOKE": L(lang, "연기 의심 구간", "possible smoke"),
                "DOWNHILL": L(lang, "긴 내리막 구간", "long downhill"),
                "CHARGER_FAULT": L(lang, f"{rn} 충전기 고장 의심", f"possible charger fault at {rn}"),
                "CHARGER_WAIT": L(lang, f"{rn} 충전 대기", f"charging queue at {rn}")}[typ]
        how = {"HARD_BRAKE": L(lang, "급제동", "braked hard"), "CONGESTION": L(lang, "서행", "slowed down"),
               "INCIDENT": self._evidence_phrase(lang, evidence or []), "HEAVY_RAIN": L(lang, "와이퍼 작동", "wipers on"),
               "ICING": L(lang, "감속", "slowing"), "BLOCKED": L(lang, "회차", "turned back"), "DEBRIS": L(lang, "급조향", "swerved"),
               "SMOKE": L(lang, "내기순환 전환", "switched to recirculation"), "DOWNHILL": L(lang, "장시간 제동", "long braking"),
               "CHARGER_FAULT": L(lang, "충전 실패", "failed to charge"), "CHARGER_WAIT": L(lang, f"{mins}분 대기", f"waited {mins} min")}[typ]
        act = {"HARD_BRAKE": L(lang, "감속하세요.", "Slow down."), "CONGESTION": L(lang, "감속하세요.", "Slow down."),
               "INCIDENT": (L(lang, "일부 차로 통행 중. 서행하세요.", "Some lanes open. Drive slowly.") if partial
                            else L(lang, "교통 막힘 주의, 서행하세요.", "Expect a queue — drive slowly.") if level >= 2
                            else L(lang, "교통 막힘 주의, 감속 후 차로를 확인하세요.", "Expect a queue — slow down and check your lane.")),
               "HEAVY_RAIN": L(lang, "차간거리를 유지하세요.", "Keep your distance."), "ICING": L(lang, "서행하세요.", "Drive slowly."),
               "BLOCKED": L(lang, "우회로를 확인하세요.", "Check for a detour."), "DEBRIS": L(lang, "차로를 확인하세요.", "Check your lane."),
               "SMOKE": L(lang, "창문을 닫으세요.", "Close the windows."), "DOWNHILL": L(lang, "회생제동을 사용하세요.", "Use regenerative braking."),
               "CHARGER_FAULT": L(lang, "다음 충전소를 확인하세요.", "Check the next charging station."),
               "CHARGER_WAIT": L(lang, "충전 계획을 확인하세요.", "Check your charging plan.")}[typ]
        return L(lang, f"{where} {what}. {who} {how} 확인. {act}", f"{where}, {what}. {who} {how}. {act}")

    def _siren_sentence(self, lang, behind, named, anon, cars, eta):
        """긴급차량 한 문장: '후방 Xkm 긴급차량 접근 중. {누가} 사이렌 감지 확인. (약 N초 후 통과 예상.) 진로를 양보하세요.'(도로교통법 제29조)
        500m 안(두 번째 안내)은 짧게: '후방 500m 긴급차량 근접. 진로를 양보하세요.'"""
        if behind <= SIREN_NEAR:
            return L(lang, f"후방 {self.km_text(lang, behind)} 긴급차량 근접. 진로를 양보하세요.",
                     f"Emergency vehicle {self.km_text(lang, behind)} behind. Make way now.")
        if named:
            who = L(lang, f"{named[0]} 차량 외 {anon}대" if anon else f"{named[0]} 차량",
                    f"{named[0]}'s car and {anon} more" if anon else f"{named[0]}'s car")
        else:
            who = L(lang, f"차량 {cars}대", f"{cars} cars")
        when = ""
        if eta is not None and eta <= SIREN_ETA_MAX:
            sec = max(10, rnd(eta / 10) * 10)
            when = L(lang, f" 약 {sec}초 후 통과 예상.", f" Passing in about {sec} s.")
        return L(lang, f"후방 {self.km_text(lang, behind)} 긴급차량 접근 중. {who} 사이렌 감지 확인.{when} 진로를 양보하세요.",
                 f"Emergency vehicle {self.km_text(lang, behind)} behind. {who} heard a siren.{when} Make way.")

    def _ev_sentence(self, lang, behind, eta):
        """구급차 위치 신호: '후방 1.2km 구급차 접근 중(구급차 위치 신호). 약 40초 후 통과 예상. 진로를 양보하세요.' 500m 안은 짧게.
        통과 예상은 90초 안이면 초(10초 단위), 10분 안이면 분"""
        if behind <= SIREN_NEAR:
            return L(lang, f"후방 {self.km_text(lang, behind)} 구급차 근접. 진로를 양보하세요.", f"Ambulance {self.km_text(lang, behind)} behind. Make way now.")
        when = ""
        if eta is not None and eta <= SIREN_ETA_MAX:
            sec = max(10, rnd(eta / 10) * 10)
            when = L(lang, f" 약 {sec}초 후 통과 예상.", f" Passing in about {sec} s.")
        elif eta is not None and eta <= EV_ETA_MIN_MAX:
            m = max(2, rnd(eta / 60))
            when = L(lang, f" 약 {m}분 후 통과 예상.", f" Passing in about {m} min.")
        return L(lang, f"후방 {self.km_text(lang, behind)} 구급차 접근 중(구급차 위치 신호).{when} 진로를 양보하세요.",
                 f"Ambulance {self.km_text(lang, behind)} behind and approaching (position beacon).{when} Make way.")

    def _yield_sentence(self, lang, behind):
        """길 터 주기 물결만: '후방 1.2km 긴급차량 추정(뒤쪽 차들이 길을 비켜 주는 중). 진로를 양보하세요.' — 위치는 짐작이라 '추정'"""
        if behind <= SIREN_NEAR:
            return L(lang, f"후방 {self.km_text(lang, behind)} 긴급차량 근접 추정. 진로를 양보하세요.", f"Possible emergency vehicle {self.km_text(lang, behind)} behind. Make way now.")
        return L(lang, f"후방 {self.km_text(lang, behind)} 긴급차량 추정(뒤쪽 차들이 길을 비켜 주는 중). 진로를 양보하세요.",
                 f"Possible emergency vehicle {self.km_text(lang, behind)} behind (cars behind you are making way). Make way.")

    def _charger_at(self, r):
        """휴게소의 충전기 상태: 살아 있는 충전기 고장 보고가 있으면 'fault', 충전 대기 보고가 있으면 'wait', 없으면 None"""
        for typ, tag in (("CHARGER_FAULT", "fault"), ("CHARGER_WAIT", "wait")):
            if any(h["type"] == typ and h["reporters"] and abs(h["s"] - r["s"]) <= CHARGER_NEAR for h in self.hazards):
                return tag
        return None

    def _brief(self, lang, nearby, group, rest_next):
        """연결 브리핑 한 문장: 주변 Tago 차 수(+그룹 일행 위치) + 다음 휴게소(+충전기 고장·대기 보고)"""
        parts = [L(lang, f"주변 길벗 차량 {nearby}대 연결", f"Linked with {nearby} Gilbeot cars")]
        if group:
            for x in group["members"]:
                if x["me"] or x["gap"] is None:
                    continue
                d = self.km_text(lang, abs(x["gap"]))
                parts.append(L(lang, f"{x['name']} {d} {'앞' if x['gap'] > 0 else '뒤'}", f"{x['name']} {d} {'ahead' if x['gap'] > 0 else 'behind'}"))
        out = ", ".join(parts)
        if rest_next:
            out += L(lang, f". 다음 휴게소 {rest_next['name']}, {self.km_text(lang, rest_next['dist'])}",
                     f". Next stop {rest_next['name']}, {self.km_text(lang, rest_next['dist'])}")
            ch = rest_next.get("charger")
            if ch:
                out += L(lang, " (충전기 고장 의심 보고 있음)" if ch == "fault" else " (충전 대기 보고 있음)",
                         " (charger fault reported)" if ch == "fault" else " (charging queue reported)")
        return out + "."

    # ---- 관제 화면(3D): 도로 위 모든 차(익명)·위험·최근 신호
    def world(self, mid=None):
        me = self.car(mid)
        g = self.groups.get(me["group"]) if me and me["group"] else None
        mine = set(g["members"]) if g else set()
        amb = self.demo["amb"] if self.demo else None
        cars = [{"id": self._pid(c, mid), "s": rnd(c["s"]), "kmh": rnd(c["speed"] * 3.6), "rain": c["wiper"].startswith("CONTINUOUS"),
                 "me": c["id"] == mid, "name": c["name"] if c["id"] in mine else "", "stopped": c["speed"] < STOP_MS,
                 "yield": bool(amb and amb["on"] and 0 <= c["s"] - amb["s"] <= YIELD_M)}
                for c in self.cars if c["s"] is not None and self.now - c["t"] <= ACTIVE_SEC and not c["gone"] and c["kind"] != "ev"]
        hz = []
        for h in self.hazards:
            if h["type"] == "SIREN":
                evc = self._ev(h)
                if evc is None and not h["reporters"] and not self._yields_live(h):
                    continue
                hz.append({"id": h["id"], "type": "SIREN", "s": rnd(self._ev_pos(h)[0]), "cars": len(h["reporters"]),
                           "confirmed": evc is not None or len(h["reporters"]) >= ANON_CONFIRM, "beacon": evc is not None})
            elif h["reporters"]:
                hz.append({"id": h["id"], "type": h["type"], "s": rnd(h["s"]), "cars": len(h["reporters"]), "confirmed": len(h["reporters"]) >= ANON_CONFIRM})
        hz += [{"id": o["id"], "type": "OFFICIAL", "s": rnd(o["s"]), "cars": 0, "confirmed": True} for o in self.official]
        ems = [{"s": rnd(amb["s"]), "on": amb["on"], "beacon": amb["car"] is not None}] if amb else []   # 시연 구급차(Tago 차가 아니다 — 관제 화면에만)
        ems += [{"s": rnd(c["s"]), "on": True, "beacon": True} for c in self.cars   # 구급차 휴대폰(비컨)이 출동 중
                if c["kind"] == "ev" and not c["demo"] and c["on"] and c["s"] is not None and self.now - c["t"] <= EV_STALE]
        return {"now": r1(self.now), "cars": cars, "hazards": hz,
                "pulses": [{"t": p["t"], "s": p["s"], "type": p["type"], "car": p["car"] if p["car"] == mid else p["pub"]}
                           for p in self.pulses if self.now - p["t"] <= PULSE_SEC],
                "ems": ems, "s0": None if not self.demo else rnd(self.demo["s0"]), "scale": DEMO_SCALE}


HUB = Hub()
LOCK = Lock()
LINK_HTML = HERE / "link.html"
WORLD_HTML = HERE / "world.html"
AMB_HTML = HERE / "ambulance.html"               # 구급차 휴대폰(위치 신호): /ambulance?token=…


def route_info():
    return {"name": ROUTE_FILE["name"], "nameEn": ROUTE_FILE["nameEn"], "route": ROUTE_FILE["route"], "length": rnd(LENGTH),
            "restAreas": REST, "zones": ZONES, "sources": ROUTE_FILE["sources"]}


def handle(method, path, query, body):
    """두 서버(PC·앱 내장)가 같은 경로 규칙을 쓴다: /api/road/…(도로 링크), /api/link/…(가족 그룹). 모든 응답에 api 버전을 싣는다"""
    code, obj = _dispatch(method, path, query, body)
    obj = {"api": API, **obj}
    if code >= 400 and "error" in obj:                   # RFC 9457: instance = 정규화한 요청 경로(앱과 같게 빈 조각을 뺀다)
        obj = problem(code, obj, method, "/" + "/".join(p for p in path.split("/") if p))
    return code, obj


def _dispatch(method, path, query, body):
    parts = [p for p in path.split("/") if p]
    with LOCK:
        if method == "GET" and parts in (["api", "road", "route"], ["api", "link", "route"]):
            return 200, route_info()
        if parts[:2] == ["api", "road"]:
            act = parts[2] if len(parts) > 2 else ""
            sch = REQ_SCHEMA.get(f"{method} {act}")
            if sch:                                       # 도로 링크 1~9: 어긋난 요청은 허브 상태를 바꾸지 않고 400
                e = schema_error(SCHEMAS[sch], query if method == "GET" else body)
                if e:
                    return 400, {"error": "schema", "field": e[0], "rule": e[1]}
            if method == "GET" and act in ("", "world"):
                if query.get("t"):
                    HUB.clock({"t": query["t"], "me": query.get("me")})
                return 200, (HUB.view(query.get("me")) if act == "" else HUB.world(query.get("me")))
            if method == "POST" and act == "reset":
                HUB.reset(body.get("clockGuard") is not False)   # {"clockGuard": false} = 논리 시각 대본(시계 오차 가드 끔)
                return 200, {"ok": True}
            if method == "POST" and act == "join":
                # 긴급차량(kind "ev")은 토큰이 맞아야 들어온다(아무 차나 구급차 위치 신호를 내지 못하게)
                if clean(body.get("kind") or "", KIND_MAX) == "ev" and not hmac.compare_digest(str(body.get("token") or ""), HUB.ev_token):
                    return 403, {"error": "token"}
                c = HUB.join_road(body)
                return (200, {"me": c["id"], "view": HUB.view(c["id"])}) if c else (503, {"error": "full"})
            fn = {"state": HUB.state, "event": HUB.event, "demo": HUB.demo_road, "respond": HUB.respond, "official": HUB.post_official, "chargerstatus": HUB.post_charger_status}.get(act)
            if method == "POST" and fn:
                fn(body)
                return 200, HUB.view(body.get("me"))
        if parts[:2] == ["api", "link"]:
            if method == "POST" and parts[2:] == ["group"]:
                g = HUB.create_group(body)
                return (200, {"group": g["id"], "code": g["code"], "view": HUB.view(body.get("me"))}) if g else (404, {"error": "car"})
            if method == "POST" and parts[2:] == ["join"]:
                g, c = HUB.join_group(body)
                if not g:
                    if c == "locked":                    # 잠긴 채 남은 초 → 본문 retryAfter · 헤더 Retry-After
                        return 429, {"error": c, "retryAfter": HUB.lock_left(body)}
                    return {"full": 503}.get(c, 404), {"error": c}
                return 200, {"group": g["id"], "code": g["code"], "me": c["id"], "view": HUB.view(c["id"])}
            if len(parts) >= 3 and parts[2] in HUB.groups:
                g = HUB.groups[parts[2]]
                act = "/".join(parts[3:])
                if method == "GET" and act == "":
                    if query.get("t"):
                        HUB.clock({"t": query["t"], "me": query.get("me")})
                    return 200, HUB.view(query.get("me"))
                fn = {"demo": HUB.demo_group, "rest": HUB.rest, "rest/answer": HUB.rest_answer, "steps": HUB.set_steps,
                      "steps/done": HUB.step_done, "journey/ride": HUB.journey_ride, "journey/ack": HUB.journey_ack}.get(act)
                if method == "POST" and fn:
                    fn(g, body)
                    return 200, HUB.view(body.get("me"))
        return 404, {"error": "not found"}


def _reject_constant(name):
    raise ValueError(f"숫자 {name} 은 받지 않는다")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj, ctype=None):
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        for k, v in ({"Content-Type": ctype} if ctype else response_headers(code, obj)).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/world"):
            return self._send(200, WORLD_HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/ambulance"):
            return self._send(200, AMB_HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/models/"):                 # 3D 차 모델(Kenney Car Kit, CC0) — 앱 내장 서버와 같은 경로
            name = u.path[len("/models/"):]
            if re.fullmatch(r"[a-z0-9-]+\.glb", name) and (HERE / "models" / name).exists():
                return self._send(200, (HERE / "models" / name).read_bytes(), "model/gltf-binary")
            if re.fullmatch(r"Textures/[a-z0-9-]+\.png", name) and (HERE / "models" / name).exists():   # 모델 공용 텍스처
                return self._send(200, (HERE / "models" / name).read_bytes(), "image/png")
            return self._send(404, {"error": "not found"})
        if u.path.startswith("/link"):
            return self._send(200, LINK_HTML.read_bytes(), "text/html; charset=utf-8")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self._send(*handle("GET", u.path, q, {}))

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            # NaN·Infinity 숫자는 거절(앱 org.json 과 같은 400 — 시각에 Infinity 가 들어가면 허브가 멈춘다)
            body = json.loads(self.rfile.read(n) or b"{}", parse_constant=_reject_constant) if n else {}
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "json"})
        self._send(*handle("POST", u.path, {}, body))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Tago 도로 링크 서버 :{PORT} · {ROUTE_FILE['name']} {LENGTH / 1000:.1f}km · 휴게소 {len(REST)}곳", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
