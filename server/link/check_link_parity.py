"""도로 링크 엔진 일치 확인: PC 서버(link_server.py)와 앱 내장 서버(LinkHub.kt)에 같은 요청을 보내고 결과를 비교한다.

사용: python check_link_parity.py http://127.0.0.1:8788 http://127.0.0.1:8791 [ko|en]
도로 링크는 서버 전체가 하나의 도로라 시작할 때 /api/road/reset으로 비운다. 그룹 id·코드(무작위)는 비교에서 뺀다.
대본 셋: run(기존 — 시연 구급차는 마이크만 ems "mic"), run_ev(긴급차량 비컨·예상 경로·길 터 주기 물결, 시연 ems "all"·"yield" 와 직접 보고),
run_schema(요청 스키마 거절 400 {error:"schema", field, rule}·거절 뒤 상태 불변·받아야 하는 경계). 모든 응답의 api 버전과 위험의 DENM 필드도 비교된다
run_skew(시계 오차 가드: 30 s 넘게 틀린 t 는 창에 쓰지 않고 clockSkew 로 알림), run_limit(권고 속도를 차가 보낸 제한속도로 상한),
run_units(어바인 units "mi" → 영어 거리 글 ft·mi), run_ride(동승 — 위치 없는 휴대폰 참가자는 탄 차 기준, ADR-47),
run_detour(최소 우회 안내 FR-G-36 — 막힘 확정 10 km 안·다음 나들목 1 km 이상·처리 종료 + 300 s 해제),
run_rest(휴게소 제외는 경로에서 옆으로 30 m 벗어난 정지만 · 해제 뒤 재보고는 해제 표시를 지움, 11-08).
네 번째 인자 ignore=키,키 는 비교에서 그 키를 뺀다(바꾸기 전 PC ↔ 새 앱 대조에서 더한 필드만 빼고 볼 때).
"""
import json
import sys
import urllib.error
import urllib.request

ROUTE_PT = tuple(json.loads(open(__import__("pathlib").Path(__file__).with_name("gyeongbu_route.json"), encoding="utf-8").read())["route"][20])   # 경로 꼭짓점(위경도) — offRoute 대본
EV_TOKEN = "meeos-ev-demo"   # 두 엔진의 시연 기본 토큰(link_server.EV_TOKEN, LinkHub.EV_TOKEN)
IGNORE = set()               # 비교에서 뺄 응답 키(ignore=… 인자)


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:          # 403(토큰)·404 등도 본문과 상태 코드를 비교한다
        return {"status": e.code, **json.loads(e.read() or b"{}")}


def norm(o):
    # 무작위 값: 그룹·코드·id·차 이름표·시각, 우회 배정 assign(무작위 차 id 의 해시 추첨 — run_detour 가 dnorm 으로 규칙을 따로 검사)
    if isinstance(o, dict):
        return {k: norm(v) for k, v in o.items() if (k not in ("group", "code", "id", "me", "car", "now", "t", "assign") or isinstance(v, (dict, list))) and k not in IGNORE}
    if isinstance(o, list):
        return [norm(x) for x in o]
    if isinstance(o, float) and o == int(o):
        return int(o)
    return o


def run(base, lang):
    """대본: 내 차(나)가 도로 링크에 들어가 시연 도로를 부르고, 가족 그룹(삼촌·이모)+휴대폰 참가자(고모)를 더한 뒤 170초 주행"""
    out = []
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    T0 = 1000.0
    r = call(base, "POST", "/api/road/join", {"name": "아빠" if lang == "ko" else "Dad", "car": "그랜저", "t": T0, "lang": lang})
    me = r["me"]
    out.append(("join", r["view"]))
    s = 18000.0
    out.append(("state0", call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": s, "speed": 25, "soc": 72})))
    out.append(("demo", call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "mic"})))   # 구급차는 마이크 근거만(전과 같은 길)
    g = call(base, "POST", "/api/link/group", {"me": me, "t": T0 + 1})
    gid, code = g["group"], g["code"]
    out.append(("group", g["view"]))
    out.append(("family", call(base, "POST", f"/api/link/{gid}/demo", {"me": me, "t": T0 + 1})))
    j = call(base, "POST", "/api/link/join", {"code": code, "name": "고모", "car": "투싼", "kind": "web", "t": T0 + 2, "lang": lang})
    web = j["me"]
    out.append(("join web", j["view"]))
    v = 25.0
    for k in range(1, 171):
        t = T0 + k
        target = 25.0 if k < 18 else 20.0 if k < 30 else 8.0 if k < 60 else 4.0 if k < 150 else 22.0
        v = max(v - 1.5, min(v + 1.5, target))
        s += v * 4
        res = call(base, "POST", "/api/road/state", {"me": me, "t": t, "s": s, "speed": v, "soc": 72, "wiper": "OFF"}) if k <= 165 else call(base, "GET", f"/api/road?me={me}&t={t}")
        if k % 5 == 0 or k in (1, 14, 18, 31):
            out.append((f"t{k}", res))
        if k == 20:
            out.append(("web state", call(base, "POST", "/api/road/state", {"me": web, "t": t, "lat": 37.20, "lon": 127.10, "speed": 20})))
        if k == 12:
            out.append(("swerve", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "SWERVE", "value": "steer"})))
        if k == 40:
            out.append(("brake", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "HARD_BRAKE", "value": "test"})))
        if k == 50:
            out.append(("recirc on", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "RECIRC_ON", "value": "recirc"})))
        if k == 58:
            out.append(("recirc off", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "RECIRC_OFF", "value": "recirc"})))
        if k == 70:
            out.append(("brake hold", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "BRAKE_HOLD", "value": "20s"})))
        if k == 90:
            out.append(("turnback web", call(base, "POST", "/api/road/event", {"me": web, "t": t, "type": "TURNBACK", "value": "reverse"})))
        if k == 100:
            out.append(("rest", call(base, "POST", f"/api/link/{gid}/rest", {"me": me, "t": t})))
            out.append(("rest web", call(base, "GET", f"/api/link/{gid}?me={web}&t={t}")))
            out.append(("answer", call(base, "POST", f"/api/link/{gid}/rest/answer", {"me": web, "t": t, "yes": True})))
        if k == 102:                                     # 다음 한 단계 카드: 휴대폰 참가자(고모)가 정한다. 모르는 종류·빈 글·7장째는 버린다
            steps = [{"kind": "board", "label": "차에 타요"}, {"kind": "rest", "label": "  휴게소에서 쉬어요  "}, {"kind": "task", "label": "화장실 가요"},
                     {"kind": "fly", "label": "x"}, {"kind": "task", "label": ""}, {"kind": "task", "label": "간식 먹어요" * 4},
                     {"kind": "arrive", "label": "도착해요"}, {"kind": "task", "label": "할머니 만나요"}]
            out.append(("steps", call(base, "POST", f"/api/link/{gid}/steps", {"me": web, "t": t, "steps": steps})))
        if k == 110:
            out.append(("step done", call(base, "POST", f"/api/link/{gid}/steps/done", {"me": me, "t": t, "i": 2})))
            out.append(("step bad", call(base, "POST", f"/api/link/{gid}/steps/done", {"me": me, "t": t, "i": 9})))
        if k == 112:
            out.append(("step undo", call(base, "POST", f"/api/link/{gid}/steps/done", {"me": web, "t": t, "i": 2, "done": False})))
        if k == 114:                                     # 여정: 타는 차를 휴대폰 참가자 차로 바꿨다가(관측 차가 바뀐다) 다시 내 차로, 바뀐 계획 확인
            out.append(("ride web", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": web, "t": t, "ride": web})))
            out.append(("ride bad", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": web, "t": t, "ride": "c999"})))
        if k == 116:
            out.append(("ride me", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": web, "t": t, "ride": me})))
        if k == 118:
            out.append(("ack", call(base, "POST", f"/api/link/{gid}/journey/ack", {"me": me, "t": t})))
        if k in (125, 131):                              # 내 차 마이크가 사이렌을 들었다(시연 구급차와 따로) — 혼자 보고하면 나에게는 안 알린다
            out.append((f"siren me{k}", call(base, "POST", "/api/road/event", {"me": me, "t": t, "type": "SIREN", "value": "mic"})))
        if k == 129:
            out.append(("siren web", call(base, "POST", "/api/road/event", {"me": web, "t": t, "type": "SIREN", "value": "mic"})))
        if k == 140:                                     # 충전: 내 차가 기흥휴게소(s 27119)에서 7분 기다려 꽂았는데 90초 동안 충전이 안 됐다 → 일행(고모)에게
            out.append(("charge wait", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": 27119, "speed": 0, "type": "CHARGE_START", "value": "7"})))
            out.append(("charge fail", call(base, "POST", "/api/road/event", {"me": me, "t": t + 0.5, "s": 27119, "speed": 0, "type": "CHARGE_FAIL", "value": "90s"})))
            out.append(("charge far", call(base, "POST", "/api/road/event", {"me": me, "t": t + 0.6, "s": 40000, "speed": 0, "type": "CHARGE_FAIL", "value": "90s"})))   # 휴게소 500m 밖: 버린다
            out.append(("charge web", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
            out.append(("charge web group", call(base, "GET", f"/api/link/{gid}?me={web}&t={t + 1}")))
            s = 27119.0
        if k == 142:                                     # 운전자 1분 설문: 화면 꺼짐·3번·1대·다른 기기 충전 안 함 → 사람 신고(이름표 '충전기 3번 고장 신고')
            out.append(("charge report", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": 27119, "speed": 0, "type": "CHARGE_REPORT", "value": "survey",
                                                                               "sym": "screen_off", "place": "end", "unit": 3, "broken": "1", "alt": "no", "from": 27119})))
            out.append(("charge report web", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
            out.append(("charge here", call(base, "GET", f"/api/road?me={me}&t={t + 1}")))           # restHere = 기흥휴게소
        if k == 144:                                     # 모르는 차 ev2 가 같은 휴게소 다른 자리(7 m 옆)에서 충전 성공 → '다른 기기는 사용할 수 있습니다'
            ev2 = call(base, "POST", "/api/road/join", {"name": "ev2", "car": "ev2", "t": t, "lang": lang})["me"]
            out.append(("charge ok other", call(base, "POST", "/api/road/event", {"me": ev2, "t": t, "s": 27126, "speed": 0, "type": "CHARGE_SUCCESS", "value": "charging"})))
            out.append(("charge other web", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
        if k == 146:                                     # 모르는 차 ev3: 같은 3번 자리에서 실패 → 6 m 옮겨 충전(해제하지 않음, 다른 차 2대 = 확정), 설문은 모름만
            ev3 = call(base, "POST", "/api/road/join", {"name": "ev3", "car": "ev3", "t": t, "lang": lang})["me"]
            out.append(("charge fail ev3", call(base, "POST", "/api/road/event", {"me": ev3, "t": t, "s": 27119.5, "speed": 0, "type": "CHARGE_FAIL", "value": "90s"})))
            out.append(("charge moved ev3", call(base, "POST", "/api/road/event", {"me": ev3, "t": t + 0.5, "s": 27125.5, "speed": 0, "type": "CHARGE_MOVED", "value": "6", "from": 27119.5})))
            out.append(("charge report ev3", call(base, "POST", "/api/road/event", {"me": ev3, "t": t + 0.6, "s": 27125.5, "speed": 0, "type": "CHARGE_REPORT", "value": "survey",
                                                                                   "sym": "unknown", "unit": 0, "broken": "2", "from": 27119.5})))
            out.append(("charge moved web", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
            out.append(("charge moved world", call(base, "GET", f"/api/road/world?me={web}&t={t + 1}")))
        if k == 150:                                     # 충전이 시작됐다 → 고장 의심 해제, 대기 보고는 남는다
            out.append(("charge ok", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": 27119, "speed": 0, "type": "CHARGE_OK", "value": "charging"})))
            out.append(("charge web2", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
            # 또 다른 차 ev4 가 ev3 의 실패 자리(27119.5, 2.5 m 안)에서 충전 성공 → ev3 기록을 거둔다 → 남은 보고 없음 = 해제
            ev4 = call(base, "POST", "/api/road/join", {"name": "ev4", "car": "ev4", "t": t, "lang": lang})["me"]
            out.append(("charge ok same", call(base, "POST", "/api/road/event", {"me": ev4, "t": t + 1, "s": 27121, "speed": 0, "type": "CHARGE_SUCCESS", "value": "charging"})))
            out.append(("charge web3", call(base, "GET", f"/api/road?me={web}&t={t + 2}")))
            # 충전소 반경(evStations): 기흥휴게소 500 m 안이지만 휴게소 충전소(s 27032·27067)에서 100 m 밖(s 27250) — 실패 보고를 버리고 restHere 없음
            out.append(("charge station far", call(base, "POST", "/api/road/event", {"me": ev4, "t": t + 3, "s": 27250, "speed": 0, "type": "CHARGE_FAIL", "value": "90s"})))
            out.append(("charge station far web", call(base, "GET", f"/api/road?me={web}&t={t + 4}")))
            # 충전기 공식 상태(/api/road/chargerstatus, stat 4 운영중지·5 점검중): 기흥 충전소 둘 중 한 곳 8대 가운데 2대 점검중 → 차 보고 없이 '충전기 10대 중 2대 점검중(공식 정보)'
            gh = [e for e in json.loads(__import__("pathlib").Path(__file__).with_name("gyeongbu_route.json").read_text(encoding="utf-8")).get("evStations", []) if e["rest"] == 27119]
            if gh:
                st = [{"statId": e["statId"], "chargers": [{"id": c["id"], "stat": 5 if (i == 0 and j < 2) else 2} for j, c in enumerate(e["chargers"])]} for i, e in enumerate(gh)]
                out.append(("charge official", call(base, "POST", "/api/road/chargerstatus", {"t": t + 5, "stations": st})))
                out.append(("charge official web", call(base, "GET", f"/api/road?me={web}&t={t + 6}")))
                # 모르는 차 ev4 가 같은 휴게소 충전소 자리에서 실패 보고 → 차 보고 + 공식 정보 겹침 = 1대여도 확정, 문장에 '공식 정보로도 2대 점검중'
                out.append(("charge official+car", call(base, "POST", "/api/road/event", {"me": ev4, "t": t + 7, "s": 27067, "speed": 0, "type": "CHARGE_FAIL", "value": "90s"})))
                out.append(("charge official+car web", call(base, "GET", f"/api/road?me={web}&t={t + 8}")))
                # 전부 운영중지(stat 4) → '이 휴게소 충전이 어렵습니다'
                out.append(("charge official all", call(base, "POST", "/api/road/chargerstatus", {"t": t + 9, "stations": [{"statId": e["statId"], "chargers": [{"id": c["id"], "stat": 4} for c in e["chargers"]]} for e in gh]})))
                out.append(("charge official all web", call(base, "GET", f"/api/road?me={web}&t={t + 10}")))
        if k == 155:                                     # 사고 판단(설계 10판 시험 행렬): 뒷차 역할의 모르는 차 x 가 2분 전 합류, 내 차 뒤 1.5km
            x = call(base, "POST", "/api/road/join", {"name": "x", "car": "x", "t": t, "lang": lang})["me"]
            out.append(("inc join", call(base, "POST", "/api/road/state", {"me": x, "t": t, "s": s - 1500, "speed": 25})))
        if k == 160:                                     # 장면 9: 한 표본 튐(25→0→25) — 재검증 실패 → 급제동으로
            bad = [[-0.5 + 0.1 * i, 25.0] for i in range(5)] + [[0.0, 0.0], [0.1, 25.0], [0.2, 25.0], [0.3, 25.0], [0.4, 25.0], [0.5, 25.0]]
            out.append(("impact glitch", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": s, "speed": 25, "type": "IMPACT", "value": "glitch", "samples": bad})))
        if k == 165:                                     # 장면 3·5: 충돌(25→0.2) 뒤 보고 중단 → 통신 끊김 → 무응답
            good = [[-1.4 + 0.1 * i, 25.0] for i in range(10)] + [[-0.4, 2.0], [-0.3, 1.0], [-0.2, 0.5], [-0.1, 0.3], [0.0, 0.2]]
            out.append(("impact", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": s, "speed": 0.2, "type": "IMPACT", "value": "25→0.2", "samples": good})))
            v = 0.0
        if 166 <= k <= 170:
            out.append((f"inc x{k}", call(base, "POST", "/api/road/state", {"me": x, "t": t, "s": s - 1500 + (k - 155) * 100, "speed": 25})))
        if k in (30, 60, 75, 90, 160):
            out.append((f"world{k}", call(base, "GET", f"/api/road/world?me={me}&t={t}")))
    t = T0 + 171
    out.append(("inc view", call(base, "GET", f"/api/road?me={x}&t={t + 5}")))                                     # 충돌+통신 끊김(정지) → 1대 확정 2단계
    out.append(("no response", call(base, "POST", "/api/road/respond", {"me": me, "t": t + 30, "ok": None, "timeout": True})))
    out.append(("inc view2", call(base, "GET", f"/api/road?me={x}&t={t + 31}")))
    # 공식 확인(설계 10판 시험 14): 뒷차 x 의 순정 내비가 사고 지점 800m 앞 ACCIDENT(끝 t+34)를 준다 → 2단계 '공식 확인' 문장, 끝 시각이 지나면 사고 의심도 거둠.
    # 경로 밖 ROAD_DAMAGE(위경도, 1km 넘게 떨어짐)와 REPAIRING 은 버린다
    out.append(("official", call(base, "POST", "/api/road/official", {"me": x, "t": t + 31.5, "events": [
        {"type": "ACCIDENT", "s": s + 800, "end": t + 34, "desc": "2차로 추돌"}, {"type": "ROAD_DAMAGE", "lat": 37.0, "lon": 127.5, "desc": "far"},
        {"type": "REPAIRING", "s": s, "desc": "x"}]})))
    out.append(("official view", call(base, "GET", f"/api/road?me={x}&t={t + 33}")))
    out.append(("official world", call(base, "GET", f"/api/road/world?me={x}&t={t + 33}")))
    out.append(("official end", call(base, "GET", f"/api/road?me={x}&t={t + 35}")))                                # endTime 지남 → 사고 의심 거둠, 공식도 사라짐
    out.append(("ok", call(base, "POST", "/api/road/respond", {"me": me, "t": t + 36, "ok": True})))              # 장면 4: 괜찮아요 → 거둠
    out.append(("inc view3", call(base, "GET", f"/api/road?me={x}&t={t + 37}")))
    # 사고 의심이 없는 공식 돌발(내 차 3km 앞): 화면 항목만(say 없음). 같은 종류 300m 안은 하나로
    out.append(("official alone", call(base, "POST", "/api/road/official", {"me": me, "t": t + 38, "events": [
        {"type": "ACCIDENT", "s": s + 3000, "desc": "갓길 사고"}, {"type": "ACCIDENT", "s": s + 3100, "desc": "같은 사고"}, {"type": "DISASTER", "lat": 37.20, "lon": 127.10}]})))
    out.append(("official alone x", call(base, "GET", f"/api/road?me={x}&t={t + 39}")))
    # 구역(③): 새 차 z 가 다발 구간 앞 → 안내(같은 구간에 사고 의심이 있으면 생략, 사고 의심 문장에 맥락); 외기 -2 °C 로 교량(z2, s 28701~) 1 km 앞 → 결빙 주의
    t += 1900                                       # 공식 돌발(30분)이 만료된 뒤 — 앞 사례의 공식 재난이 터널 사례를 덮지 않게
    zc = call(base, "POST", "/api/road/join", {"name": "z", "car": "z", "t": t + 40, "lang": lang})["me"]
    out.append(("zone accident", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 41, "s": 29342, "speed": 25})))   # 경부동탄 다발 구간(z3) 1.2 km 앞, 사고 의심 없음 → 안내
    out.append(("zone bridge warm", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 42, "s": 27701, "speed": 25, "temp": 12})))
    out.append(("zone bridge ice", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 43, "s": 27701, "speed": 25, "temp": -2})))
    out.append(("zone inside", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 44, "s": 23000, "speed": 25})))
    # 터널(경부동탄터널 z4, s 30739~31947) 안에서 충돌 뒤 보고가 끊김 → 통신 끊김으로 세지 않는다. 다발 구간(z3) 맥락 문장
    tn = call(base, "POST", "/api/road/join", {"name": "tn", "car": "tn", "t": t + 45, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": tn, "t": t + 45, "s": 31000, "speed": 25})
    good = [[-1.4 + 0.1 * i, 25.0] for i in range(10)] + [[-0.4, 2.0], [-0.3, 1.0], [-0.2, 0.5], [-0.1, 0.3], [0.0, 0.2]]
    out.append(("tunnel impact", call(base, "POST", "/api/road/event", {"me": tn, "t": t + 46, "s": 31000, "speed": 0.2, "type": "IMPACT", "value": "25→0.2", "samples": good})))
    tn2 = call(base, "POST", "/api/road/join", {"name": "tn2", "car": "tn2", "t": t + 46, "lang": lang})["me"]   # 두 번째 차도 같은 자리에서 충돌 → 모르는 차 2대 = 확정
    call(base, "POST", "/api/road/state", {"me": tn2, "t": t + 46, "s": 31050, "speed": 25})
    out.append(("tunnel impact2", call(base, "POST", "/api/road/event", {"me": tn2, "t": t + 47, "s": 31050, "speed": 0.2, "type": "IMPACT", "value": "25→0.2", "samples": good})))
    out.append(("tunnel quiet", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 60, "s": 28500, "speed": 25})))   # 14 s 조용 — 터널이라 COMM_LOSS 없음
    # 사고 위험성(④): 비(와이퍼 연속)+영하 → 결빙 +3·비 +2, 경부동탄 다발 구간·터널 1 km 앞 +2·+1, 앞 3 km 사고 의심 +3 → 높음
    out.append(("risk rain ice", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 61, "s": 29700, "speed": 25, "wiper": "CONTINUOUS_3", "temp": -2})))
    out.append(("risk warm dry", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 62, "s": 29700, "speed": 25, "wiper": "OFF", "temp": 15})))
    t += 37000                                      # 한국 시각 밤 — 야간 +1, 앞 위험은 만료
    out.append(("risk night", call(base, "POST", "/api/road/state", {"me": zc, "t": t, "s": 60000, "speed": 25, "wiper": "OFF", "temp": 3})))
    out.append(("route", call(base, "GET", "/api/road/route")))
    # 11-06 입력 검증: 가족 코드로 kind "ev" 참가는 일반 차(web)로(토큰 없이 비컨이 되지 않게), 시각 Infinity 는 무시(허브가 멈추지 않게)
    g2 = call(base, "POST", "/api/link/group", {"me": zc, "t": t + 1})
    j2 = call(base, "POST", "/api/link/join", {"code": g2["code"], "name": "가짜 구급차", "kind": "ev", "t": t + 2, "lang": lang})
    out.append(("join ev via code", j2["view"]))
    out.append(("join ev world", call(base, "GET", f"/api/road/world?me={zc}&t={t + 2}")))
    out.append(("t inf", call(base, "POST", "/api/road/state", {"me": zc, "t": float("inf"), "s": 60100, "speed": 25}).get("status", 200)))   # 상태 코드만(오류 문구는 엔진마다 다르다)
    out.append(("after inf", call(base, "POST", "/api/road/state", {"me": zc, "t": t + 5, "s": 60200, "speed": 25})))
    return out


def drive(base, out, me, lang, T0, kmax, tag, every=5, extra=()):
    """run 과 같은 속도 대본으로 내 차를 kmax 초 달린다(시연 도로가 함께 돈다)"""
    s, v = 18000.0, 25.0
    for k in range(1, kmax + 1):
        t = T0 + k
        target = 25.0 if k < 18 else 20.0 if k < 30 else 8.0 if k < 60 else 4.0 if k < 150 else 22.0
        v = max(v - 1.5, min(v + 1.5, target))
        s += v * 4
        res = call(base, "POST", "/api/road/state", {"me": me, "t": t, "s": s, "speed": v, "wiper": "OFF"})
        if k % every == 0 or k in extra:
            out.append((f"{tag} t{k}", res))
        if k in (60, 75, 110):
            out.append((f"{tag} world{k}", call(base, "GET", f"/api/road/world?me={me}&t={t}")))


def run_ev(base, lang):
    """긴급차량: ① 시연 구급차가 비컨+마이크+비킴을 함께 낸다 ② 비킴만 ③ 구급차 휴대폰(비컨) 직접 — 토큰·예상 경로·멈춤·거꾸로·끔·끊김
    ④ YIELD 직접 — 물결 2대(미확정)·3대(확정)·느린 비킴(물결 아님)·물결+마이크 1대(확정)"""
    out = []
    T0 = 5000.0
    # ① 시연 ems all: 구급차가 50초에 정체 꼬리 뒤에서 나타나 사고 지점(목적지)으로. 위치 신호로 바로 알리고, 마이크·비킴이 근거로 붙는다
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    me = call(base, "POST", "/api/road/join", {"name": "아빠" if lang == "ko" else "Dad", "car": "그랜저", "t": T0, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 18000.0, "speed": 25})
    out.append(("all demo", call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "all"})))
    drive(base, out, me, lang, T0, 125, "all", 5, tuple(range(50, 58)) + (73, 74, 76, 78))
    # ② 시연 ems yield: 위치 신호·마이크 없이 비킴만 — 2대는 화면에만, 3대부터 확정
    T0 += 1000
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    me = call(base, "POST", "/api/road/join", {"name": "아빠" if lang == "ko" else "Dad", "car": "그랜저", "t": T0, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 18000.0, "speed": 25})
    out.append(("yield demo", call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "yield"})))
    drive(base, out, me, lang, T0, 100, "yield", 5, (66, 67, 68, 69, 71, 72, 73, 76, 77, 78))
    # ③ 구급차 휴대폰(비컨) 직접. A·B 는 앞, C 는 구급차 뒤, D 는 구급차 옆(마이크)
    T0 += 1000
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    ids = {}
    for name, s0 in (("A", 20000.0), ("B", 22500.0), ("C", 15000.0), ("D", 18100.0)):
        ids[name] = call(base, "POST", "/api/road/join", {"name": name, "car": name, "t": T0, "lang": lang})["me"]
    out.append(("ev bad token", call(base, "POST", "/api/road/join", {"kind": "ev", "token": "wrong", "t": T0, "lang": lang})))
    out.append(("ev no token", call(base, "POST", "/api/road/join", {"kind": "ev", "t": T0, "lang": lang})))
    ev = call(base, "POST", "/api/road/join", {"kind": "ev", "token": EV_TOKEN, "name": "구급차", "t": T0, "lang": lang})
    out.append(("ev join", ev["view"]))
    ev = ev["me"]
    pos = {"A": 20000.0, "B": 22500.0, "C": 15000.0, "D": 18100.0}

    def cars(t):
        for n in ("A", "B", "C", "D"):
            call(base, "POST", "/api/road/state", {"me": ids[n], "t": t, "s": pos[n], "speed": 20})

    def views(tag, t):
        for n in ("A", "B", "C"):
            out.append((f"{tag} {n}", call(base, "GET", f"/api/road?me={ids[n]}&t={t}")))
        out.append((f"{tag} ev", call(base, "GET", f"/api/road?me={ev}&t={t}")))

    t = T0
    es = 18000.0
    out.append(("ev off", call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 0, "on": False})))
    cars(t)
    views("off", t)
    # 출동 시작, 목적지 22000(B 는 목적지를 500 m 지남 → 예상 경로 밖). 구급차 경로 위 30 m/s, 앞차들 20 m/s
    for k in range(1, 9):
        t = T0 + k
        es += 30.0
        for n in pos:
            pos[n] += 20.0
        cars(t)
        out.append((f"ev on{k}", call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 30, "on": True, "dest_s": 22000})))
        if k in (1, 3, 4, 8):
            views(f"on{k}", t)
        if k == 5:                                   # 구급차 옆 D 의 마이크가 사이렌을 들었다 → 같은 위험의 근거(들은 차 1대)
            out.append(("ev mic D", call(base, "POST", "/api/road/event", {"me": ids["D"], "t": t, "s": pos["D"], "type": "SIREN", "value": "mic"})))
        if k == 6:                                   # 구급차 자신이 보낸 사건은 버린다
            out.append(("ev own event", call(base, "POST", "/api/road/event", {"me": ev, "t": t, "type": "YIELD", "value": "x"})))
    out.append(("ev world", call(base, "GET", f"/api/road/world?me={ids['A']}&t={t}")))
    # 목적지를 지운다(dest_s null) → B 에도 알린다(뒤 5 km 안)
    t += 1
    es += 30.0
    out.append(("ev no dest", call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 30, "on": True, "dest_s": None})))
    views("nodest", t)
    # 멈춤: 위치가 그대로(10초 창 안 속도 0) → 말하지 않는다
    for k in range(1, 12):
        t += 1
        call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 0, "on": True})
    views("stopped", t)
    # 거꾸로(반대 방향) → oncoming, 말하지 않는다
    for k in range(1, 6):
        t += 1
        es -= 30.0
        call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 30, "on": True})
    views("reverse", t)
    # 다시 앞으로 → 출동 끝(on false) → 마이크 근거만 남는다(들은 차 1대 = 미확정)
    for k in range(1, 6):
        t += 1
        es += 30.0
        call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 30, "on": True})
    views("again", t)
    t += 1
    out.append(("ev end", call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 0, "on": False})))
    views("ended", t)
    # 다시 출동 → 16초 소식 없음(끊김) → 꺼진 것으로 본다
    t += 1
    call(base, "POST", "/api/road/state", {"me": ev, "t": t, "s": es, "speed": 30, "on": True})
    views("resume", t)
    views("stale", t + 16)
    # 위도·경도로 보내는 비컨(휴대폰 GPS): 경로에 투영
    t += 20
    out.append(("ev gps", call(base, "POST", "/api/road/state", {"me": ev, "t": t, "lat": 37.20, "lon": 127.10, "speed": 25, "on": True})))
    # ④ YIELD 직접(비컨·마이크 없이)
    T0 = t + 100
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    y = {}
    for name, s0 in (("Y1", 30000.0), ("Y2", 30300.0), ("Y3", 30600.0), ("L", 32000.0), ("Z1", 40000.0), ("Z2", 40020.0),
                     ("W1", 50000.0), ("W2", 50400.0), ("W3", 50100.0), ("M", 51500.0)):
        y[name] = call(base, "POST", "/api/road/join", {"name": name, "car": name, "t": T0, "lang": lang})["me"]
        call(base, "POST", "/api/road/state", {"me": y[name], "t": T0, "s": s0 - 20, "speed": 20})
        call(base, "POST", "/api/road/state", {"me": y[name], "t": T0 + 1, "s": s0, "speed": 20})
    t = T0 + 1
    out.append(("y1", call(base, "POST", "/api/road/event", {"me": y["Y1"], "t": t, "s": 30000, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("y1 L", call(base, "GET", f"/api/road?me={y['L']}&t={t}")))
    out.append(("y2", call(base, "POST", "/api/road/event", {"me": y["Y2"], "t": t + 3, "s": 30300, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("y2 L", call(base, "GET", f"/api/road?me={y['L']}&t={t + 3}")))        # 2대: 화면에만(미확정)
    out.append(("y3", call(base, "POST", "/api/road/event", {"me": y["Y3"], "t": t + 6, "s": 30600, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("y3 L", call(base, "GET", f"/api/road?me={y['L']}&t={t + 6}")))        # 3대: 확정, 말한다
    out.append(("y3 world", call(base, "GET", f"/api/road/world?me={y['L']}&t={t + 6}")))
    # 느린 비킴(물결 속도 5 m/s ≤ 흐름 20 + 5): 위험을 만들지 않는다
    out.append(("z1", call(base, "POST", "/api/road/event", {"me": y["Z1"], "t": t + 7, "s": 40000, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("z2", call(base, "POST", "/api/road/event", {"me": y["Z2"], "t": t + 11, "s": 40020, "speed": 12, "type": "YIELD", "value": "right"})))
    # 물결 2대 + 마이크 1대 = 확정(마이크 문장)
    out.append(("w1", call(base, "POST", "/api/road/event", {"me": y["W1"], "t": t + 12, "s": 50000, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("w2", call(base, "POST", "/api/road/event", {"me": y["W2"], "t": t + 16, "s": 50400, "speed": 12, "type": "YIELD", "value": "right"})))
    out.append(("w2 M", call(base, "GET", f"/api/road?me={y['M']}&t={t + 16}")))
    out.append(("w3 mic", call(base, "POST", "/api/road/event", {"me": y["W3"], "t": t + 17, "s": 50100, "type": "SIREN", "value": "mic"})))
    out.append(("w3 M", call(base, "GET", f"/api/road?me={y['M']}&t={t + 17}")))
    out.append(("w end", call(base, "GET", f"/api/road?me={y['M']}&t={t + 80}")))       # 60초 창·30초 TTL 지남
    return out


def run_schema(base, lang):
    """요청 스키마(server/link/schema, 11-06): 어긋난 요청은 두 엔진 모두 400 {error:"schema", field, rule} 이고 허브 상태를 바꾸지 않는다.
    받아야 하는 경계(null 허용 필드, 코드 포인트로 센 글 길이, 빈 t)도 같이 본다. 본문이 객체가 아닌 경우는 상태 코드만(앱은 내장 서버가 먼저 거절)"""
    out = []
    T0 = 90000.0
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본(시간을 건너뜀) — 시계 오차 가드 끔(ADR-43)
    me = call(base, "POST", "/api/road/join", {"name": "S", "car": "S", "t": T0, "lang": lang})["me"]
    out.append(("ok state", call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 20000, "speed": 25, "wiper": "OFF"})))
    bad = [
        ("state no me", "/api/road/state", {"t": T0 + 1, "s": 1}),
        ("state me num", "/api/road/state", {"me": 5, "t": T0 + 1}),
        ("state speed str", "/api/road/state", {"me": me, "t": T0 + 1, "s": 30000, "speed": "fast"}),
        ("state speed bool", "/api/road/state", {"me": me, "t": T0 + 1, "s": 30000, "speed": True}),
        ("state lat 91", "/api/road/state", {"me": me, "t": T0 + 1, "lat": 91, "lon": 127}),
        ("state soc 120", "/api/road/state", {"me": me, "t": T0 + 1, "soc": 120}),
        ("state t neg", "/api/road/state", {"me": me, "t": -1, "s": 30000}),
        ("state t str", "/api/road/state", {"me": me, "t": "90001", "s": 30000}),
        ("event no type", "/api/road/event", {"me": me, "t": T0 + 1, "value": "x"}),
        ("event value null", "/api/road/event", {"me": me, "t": T0 + 1, "type": "HARD_BRAKE", "value": None}),
        ("event samples 21", "/api/road/event", {"me": me, "t": T0 + 1, "type": "IMPACT", "value": "x", "samples": [[0.0, 1.0]] * 21}),
        ("event sample str", "/api/road/event", {"me": me, "t": T0 + 1, "type": "IMPACT", "value": "x", "samples": [[0.1, 2.0], [0.2, "x"]]}),
        ("event sample short", "/api/road/event", {"me": me, "t": T0 + 1, "type": "IMPACT", "value": "x", "samples": [[0.1]]}),
        ("event unit 100", "/api/road/event", {"me": me, "t": T0 + 1, "type": "CHARGE_REPORT", "value": "survey", "unit": 100}),
        ("official no events", "/api/road/official", {"me": me, "t": T0 + 1}),
        ("official events obj", "/api/road/official", {"me": me, "t": T0 + 1, "events": {"type": "ACCIDENT"}}),
        ("official lat 200", "/api/road/official", {"me": me, "t": T0 + 1, "events": [{"type": "ACCIDENT", "s": 21000}, {"type": "ACCIDENT", "lat": 200, "lon": 127}]}),
        ("official no type", "/api/road/official", {"me": me, "t": T0 + 1, "events": [{"s": 21000}]}),
        ("respond ok str", "/api/road/respond", {"me": me, "t": T0 + 1, "ok": "yes"}),
        ("demo no me", "/api/road/demo", {"t": T0 + 1}),
        ("join kind num", "/api/road/join", {"t": T0 + 1, "kind": 5}),
        ("join name 201", "/api/road/join", {"t": T0 + 1, "name": "가" * 201}),
        ("join name 201 emoji", "/api/road/join", {"t": T0 + 1, "name": "\U0001F697" * 201}),
    ]
    for tag, path, body in bad:
        out.append((tag, call(base, "POST", path, body)))
    for tag, q in (("get t abc", "t=abc"), ("get t exp", "t=1e5"), ("get t neg", "t=-5"), ("get t nan", "t=nan"), ("get t underscore", "t=1_0")):
        out.append((tag, call(base, "GET", f"/api/road?me={me}&{q}")))
    out.append(("world t hex", call(base, "GET", f"/api/road/world?me={me}&t=0x1p3")))
    out.append(("reset list", call(base, "POST", "/api/road/reset", []).get("status", 200)))      # 상태 코드만(앱은 내장 서버 JSON 파싱이 먼저 400)
    # RFC 9457 오류 본문(type·title·status·detail·instance + 옛 error): 미정의 경로(끝 / 는 instance 에서 빠짐), 그룹 없는 차, 코드 5번 틀림 → 429 retryAfter
    out.append(("problem 404", call(base, "POST", "/api/road/teleport/", {"me": me, "t": T0 + 1})))
    out.append(("problem car", call(base, "POST", "/api/link/group", {"me": "c000000000000", "t": T0 + 1})))
    for i in range(5):
        out.append((f"problem code {i}", call(base, "POST", "/api/link/join", {"code": "0000", "name": "w", "kind": "web", "t": T0 + 1 + i * 0.25, "lang": lang})))
    out.append(("problem locked", call(base, "POST", "/api/link/join", {"code": "0000", "name": "w", "kind": "web", "t": T0 + 2.6, "lang": lang})))
    # 거절 뒤 허브 상태 그대로: 내 차는 처음 자리(20000)·시각 T0, 위험·차 수 변화 없음
    out.append(("after bad view", call(base, "GET", f"/api/road?me={me}")))
    out.append(("after bad world", call(base, "GET", f"/api/road/world?me={me}")))
    # 받아야 하는 경계: null 허용 필드, 이모지 200개(코드 포인트 200 · UTF-16 400), 빈 t
    out.append(("ok nulls", call(base, "POST", "/api/road/state", {"me": me, "t": T0 + 2, "s": None, "lat": None, "lon": None, "speed": None, "wiper": None,
                                                                     "temp": None, "soc": None, "on": None, "dest_s": None})))
    out.append(("ok neg speed", call(base, "POST", "/api/road/state", {"me": me, "t": T0 + 3, "s": 20010, "speed": -2.0})))
    out.append(("ok emoji 200", call(base, "POST", "/api/road/join", {"t": T0 + 4, "name": "\U0001F697" * 200, "lang": lang}).get("view", {}).get("nearby")))
    out.append(("ok empty t", call(base, "GET", f"/api/road?me={me}&t=")))
    out.append(("ok samples", call(base, "POST", "/api/road/event", {"me": me, "t": T0 + 5, "s": 20020, "speed": 0.2, "type": "IMPACT", "value": "25→0.2",
                                                                       "samples": [[-1.4 + 0.1 * i, 25.0] for i in range(10)] + [[-0.4, 2.0], [-0.3, 1.0], [-0.2, 0.5], [-0.1, 0.3], [0.0, 0.2]]})))
    return out


def run_skew(base, lang):
    """시계 오차 가드(ADR-43): 허브는 요청 t 를 '마지막으로 받은 t + 그 뒤 실제 경과'와 견줘 CLOCK_SKEW_SEC(30 s) 넘게 어긋나면
    그 t 로 시계를 옮기지 않고(창은 수신 시각 기준) 그 차의 보기에 clockSkew(초)를 준다. 정상 시계는 전과 같다"""
    out = []
    call(base, "POST", "/api/road/reset", {})
    T0 = 5000.0
    a = call(base, "POST", "/api/road/join", {"name": "A", "car": "x", "t": T0, "lang": lang})["me"]
    b = call(base, "POST", "/api/road/join", {"name": "B", "car": "y", "t": T0, "lang": lang})["me"]
    for k in range(1, 6):                                # 둘 다 정상(1 s 씩)
        call(base, "POST", "/api/road/state", {"me": a, "t": T0 + k, "s": 20000.0 + 25 * k, "speed": 25.0})
        r = call(base, "POST", "/api/road/state", {"me": b, "t": T0 + k, "s": 19000.0 + 25 * k, "speed": 25.0})
    out.append(("ok", r))                                # clockSkew 없음(null)
    # B 의 시계가 200 s 앞섬: 급제동 보고 — 허브 시계가 200 s 뛰지 않으니 A 가 보는 보고 나이(age)는 0 근처, B 의 보기엔 clockSkew ≈ 200
    out.append(("ahead 200", call(base, "POST", "/api/road/event", {"me": b, "t": T0 + 6 + 200, "type": "HARD_BRAKE", "value": "test", "s": 19150.0, "speed": 10.0})))
    out.append(("A sees", call(base, "POST", "/api/road/state", {"me": a, "t": T0 + 7, "s": 20175.0, "speed": 25.0})))
    out.append(("behind 100", call(base, "POST", "/api/road/state", {"me": b, "t": T0 + 8 - 100, "s": 19200.0, "speed": 20.0})))   # 뒤처진 시계도 표시
    out.append(("within 20", call(base, "POST", "/api/road/state", {"me": b, "t": T0 + 9 + 20, "s": 19225.0, "speed": 20.0})))    # 30 s 안은 전처럼 받는다(표시 없음)
    out.append(("A old t", call(base, "POST", "/api/road/state", {"me": a, "t": T0 + 10, "s": 20250.0, "speed": 25.0})))          # 과거 t 는 전처럼 무시(표시 없음)
    out.append(("GET skew", call(base, "GET", f"/api/road?me={a}&t={T0 + 10 + 500}")))                                             # GET 의 t 도 같은 가드
    out.append(("no t", call(base, "POST", "/api/road/state", {"me": a, "s": 20275.0, "speed": 25.0})))                              # t 없음 = 시계 그대로, 표시 유지
    out.append(("A ok again", call(base, "POST", "/api/road/state", {"me": a, "t": T0 + 31, "s": 20300.0, "speed": 25.0})))
    return out


def run_limit(base, lang):
    """권고 속도 상한(ADR-44): 차가 1 s 상태에 실은 제한속도(limit, 순정 내비)가 80 보다 낮으면 '시속 70까지', 높거나 없으면 전처럼 80"""
    out = []
    call(base, "POST", "/api/road/reset", {})
    T0 = 6000.0
    me = call(base, "POST", "/api/road/join", {"name": "아빠" if lang == "ko" else "Dad", "car": "그랜저", "t": T0, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 18000.0, "speed": 25.0, "limit": 70})
    call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "mic"})
    s, v = 18000.0, 25.0
    for k in range(1, 131):
        t = T0 + k
        target = 25.0 if k < 18 else 20.0 if k < 30 else 8.0 if k < 60 else 4.0 if k < 120 else 22.0
        v = max(v - 1.5, min(v + 1.5, target))
        s += v * 4
        lim = 70 if k < 40 else 100 if k < 60 else 0 if k < 80 else 70 if k < 100 else None   # 70 → 100(80 유지) → 0(모름) → 70 → 없음
        body = {"me": me, "t": t, "s": s, "speed": v, "wiper": "OFF"}
        if lim is not None:
            body["limit"] = lim
        res = call(base, "POST", "/api/road/state", body)
        if k % 5 == 0 or k in (1, 14, 18, 31):
            out.append((f"lim t{k}", {"ahead": res.get("ahead"), "hazards": res.get("hazards"), "brief": res.get("brief")}))
    out.append(("limit 250 rejected", call(base, "POST", "/api/road/state", {"me": me, "t": T0 + 131, "s": s, "speed": v, "limit": 250})))
    out.append(("limit -5 rejected", call(base, "POST", "/api/road/state", {"me": me, "t": T0 + 132, "s": s, "speed": v, "limit": -5})))
    return out


def run_units(base, lang):
    """지역 단위(ADR-45): join 의 units "mi"(어바인) → 영어 거리 글이 ft·mi, 한국어는 그대로. 모르는 값·없음은 km"""
    out = []
    call(base, "POST", "/api/road/reset", {})
    T0 = 7000.0
    r = call(base, "POST", "/api/road/join", {"name": "Dad", "car": "Tucson", "t": T0, "lang": lang, "units": "mi"})
    me = r["me"]
    out.append(("join mi", r["view"]))
    call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 18000.0, "speed": 25.0})
    call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "mic"})
    drive(base, out, me, lang, T0, 120, "mi", every=10, extra=(1, 14, 18, 31))
    r2 = call(base, "POST", "/api/road/join", {"name": "Aunt", "car": "Kona", "t": T0 + 121, "lang": lang, "units": "furlong"})
    out.append(("join bad units", r2["view"]))
    r3 = call(base, "POST", "/api/road/join", {"name": "Uncle", "car": "Santa Fe", "t": T0 + 122, "lang": lang})
    out.append(("join no units", r3["view"]))
    web = call(base, "POST", "/api/road/state", {"me": r2["me"], "t": T0 + 123, "s": 17000.0, "speed": 25.0})
    out.append(("km car sees", web))
    return out


def run_ride(base, lang):
    """동승(ADR-47): 위치 없는 휴대폰 참가자가 '같이 타요'로 합류하면 보기(위험 문장·앞길·휴게소)는 탄 차 기준, 말은 참가자 언어.
    따로 가는 참가자(위치 없음)는 문장 없음. 칩으로 자기 자신을 고르면 기준이 풀리고, 탄 차 소식이 끊기면 내 위치(없음)로 돌아간다"""
    out = []
    call(base, "POST", "/api/road/reset", {"clockGuard": False})
    T0 = 9000.0
    other = "en" if lang == "ko" else "ko"
    host = call(base, "POST", "/api/road/join", {"name": "아빠", "car": "그랜저", "t": T0, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": host, "t": T0, "s": 18000.0, "speed": 25.0})
    g = call(base, "POST", "/api/link/group", {"me": host, "t": T0 + 1})
    gid, code = g["group"], g["code"]
    rider = call(base, "POST", "/api/link/join", {"code": code, "name": "고모", "kind": "web", "ride": True, "t": T0 + 2, "lang": other})
    out.append(("join rider", rider["view"]))
    rid = rider["me"]
    sep = call(base, "POST", "/api/link/join", {"code": code, "name": "이모", "car": "쏘렌토", "kind": "web", "ride": False, "t": T0 + 3, "lang": lang})
    out.append(("join separate", sep["view"]))
    sid = sep["me"]
    bad = call(base, "POST", "/api/link/join", {"code": code, "name": "삼촌", "kind": "web", "ride": "yes", "t": T0 + 3.5, "lang": lang})   # 참·거짓이 아닌 값 = 따로
    out.append(("join ride str", bad["view"]))
    # 모르는 차 둘이 2 km 앞에서 피함 → 낙하물 확정(2대)
    a = call(base, "POST", "/api/road/join", {"name": "a", "car": "a", "t": T0 + 4, "lang": lang})["me"]
    b = call(base, "POST", "/api/road/join", {"name": "b", "car": "b", "t": T0 + 4, "lang": lang})["me"]
    for k, c in enumerate((a, b)):
        call(base, "POST", "/api/road/state", {"me": c, "t": T0 + 5, "s": 20000.0 + 40 * k, "speed": 25.0})
        out.append((f"swerve {k}", call(base, "POST", "/api/road/event", {"me": c, "t": T0 + 6 + k, "type": "SWERVE", "value": "steer"})))
    s = 18000.0
    for k in range(1, 13):
        t = T0 + 8 + k
        s += 25.0
        call(base, "POST", "/api/road/state", {"me": a, "t": t, "s": 20000.0 + 25 * k, "speed": 25.0})
        call(base, "POST", "/api/road/state", {"me": b, "t": t, "s": 20040.0 + 25 * k, "speed": 25.0})
        out.append((f"host t{k}", call(base, "POST", "/api/road/state", {"me": host, "t": t, "s": s, "speed": 25.0, "wiper": "CONTINUOUS_2", "temp": -1})))
        if k % 3 == 0:
            out.append((f"rider t{k}", call(base, "GET", f"/api/road?me={rid}&t={t}")))
            out.append((f"rider group t{k}", call(base, "GET", f"/api/link/{gid}?me={rid}&t={t}")))
            out.append((f"separate t{k}", call(base, "GET", f"/api/road?me={sid}&t={t}")))
        if k == 4:                                       # 탄 차 혼자 급제동 보고 → 그 차처럼 동승자에게도 말하지 않는다
            out.append(("host brake", call(base, "POST", "/api/road/event", {"me": host, "t": t, "type": "HARD_BRAKE", "value": "test"})))
            out.append(("rider after host brake", call(base, "GET", f"/api/road?me={rid}&t={t}")))
        if k == 7:                                       # 칩: 자기 자신을 고름 → 기준 풀림, 다시 탄 차를 고름
            out.append(("rider picks self", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": rid, "t": t, "ride": rid})))
            out.append(("rider picks host", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": rid, "t": t, "ride": host})))
            out.append(("separate picks host", call(base, "POST", f"/api/link/{gid}/journey/ride", {"me": sid, "t": t, "ride": host})))   # 따로 가던 참가자도 칩으로 동승이 된다
    t = T0 + 21
    out.append(("rider world", call(base, "GET", f"/api/road/world?me={rid}&t={t}")))
    out.append(("rider sends own s", call(base, "POST", "/api/road/state", {"me": rid, "t": t + 1, "s": 30000.0, "speed": 20.0})))   # 내 위치가 생기면 내 기준
    out.append(("separate host quiet", call(base, "GET", f"/api/road?me={sid}&t={t + 120}")))   # 탄 차 소식 끊김(ACTIVE 밖) → 내 위치 없음으로
    return out


def fnv1a32(text):
    """허브의 우회 배정 추첨과 같은 FNV-1a 32비트(link_server.fnv1a32 · LinkHub.fnv1a32)"""
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def dnorm(d, me):
    """보기 detour 의 assign 은 무작위 차 id 에 달려 두 허브 값이 다를 수 있다 — '해시 규칙대로 배정했나'(assignOk)로 바꿔 비교한다"""
    if not d:
        return d
    d = dict(d)
    want = "detour" if fnv1a32(f"{me}:{d['hazard']}") / 4294967296.0 < d["p"] else "stay"
    d["assignOk"] = d.pop("assign") == want
    return d


def run_detour(base, lang):
    """최소 우회 안내(FR-G-36, 11-08 통합 기준 = 시뮬레이션 detour_rules.py): ① 시연 도로 — 정체 확정 뒤 권고, 다음 나들목이 1 km 안이면 거둠
    ② 정체 직접 보고(2대 확정, s 26 km): 9 km 앞·다음 나들목 6.6 km → 권고 / 10.5 km 앞 → 없음 / 다음 나들목 0.9 km → 없음 /
       나들목을 지나 막힘 2 km 앞·다음 나들목이 막힘 뒤 → 없음(나가려면 막힘을 지나야 한다 — 시뮬 eligible 과 같다)
    ③ 충돌(IMPACT) 두 대 = 사고 의심 확정 → 사유 INCIDENT ④ 공식 돌발 종료(처리 종료) → 그 순간 사고 의심 해제라 그 막힘의 권고를 거둠
       (처리 종료 + 300 s 보다 먼저). 서 있는 두 차가 올린 정체는 별개 막힘이라 권고가 그 정체로 이어진다"""
    out = []
    nm = "아빠" if lang == "ko" else "Dad"
    T0 = 11000.0
    call(base, "POST", "/api/road/reset", {"clockGuard": False})   # 논리 시각 대본
    me = call(base, "POST", "/api/road/join", {"name": nm, "car": "그랜저", "t": T0, "lang": lang})["me"]
    call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": 18000.0, "speed": 25.0})
    call(base, "POST", "/api/road/demo", {"me": me, "t": T0, "ems": "mic"})
    s, v = 18000.0, 25.0
    for k in range(1, 121):
        target = 25.0 if k < 18 else 20.0 if k < 30 else 8.0 if k < 60 else 4.0
        v = max(v - 1.5, min(v + 1.5, target))
        s += v * 4
        res = call(base, "POST", "/api/road/state", {"me": me, "t": T0 + k, "s": s, "speed": v, "wiper": "OFF"})
        if k % 10 == 0 or k in (20, 21, 108, 109):
            out.append((f"demo t{k}", {"detour": dnorm(res.get("detour"), me), "s": res.get("s"), "offRoute": res.get("offRoute")}))
    # ② 정체 직접 보고
    T1 = 12000.0
    call(base, "POST", "/api/road/reset", {"clockGuard": False})
    me = call(base, "POST", "/api/road/join", {"name": nm, "car": "그랜저", "t": T1, "lang": lang})["me"]
    others = [call(base, "POST", "/api/road/join", {"name": f"x{i}", "car": "", "t": T1, "lang": lang})["me"] for i in range(2)]
    for i, o in enumerate(others):
        call(base, "POST", "/api/road/state", {"me": o, "t": T1 + 1, "s": 26000.0 + 30 * i, "speed": 3.0})
        call(base, "POST", "/api/road/event", {"me": o, "t": T1 + 1, "type": "CONGESTION", "value": "11km/h", "s": 26000.0 + 30 * i, "speed": 3.0})
    for k, ms in ((2, 17000.0), (3, 15500.0), (4, 22700.0), (5, 24000.0)):
        res = call(base, "POST", "/api/road/state", {"me": me, "t": T1 + k, "s": ms, "speed": 25.0})
        out.append((f"jam s{ms:.0f}", {"detour": dnorm(res.get("detour"), me), "hazards": [(h["id"], h["type"], h["ahead"], h["confirmed"]) for h in res.get("hazards", [])]}))
    # ⑤ 응답·이탈: detourAck 를 실으면 보기 ack 로 돌아오고(모르는 값은 버림), 위경도가 경로에서 1 km 넘게 떨어지면 offRoute true
    lat0, lon0 = ROUTE_PT
    for k, extra in ((6, {"detourAck": {"hazard": "h1", "ack": "maybe"}}), (7, {"detourAck": {"hazard": "h1", "ack": "accepted"}}),
                     (8, {"lat": lat0, "lon": lon0}), (9, {"lat": lat0, "lon": lon0 + 0.03}), (10, {"detourAck": {"hazard": "h1", "ack": "declined"}})):
        res = call(base, "POST", "/api/road/state", {"me": me, "t": T1 + k, "s": 17000.0, "speed": 25.0, **extra})
        out.append((f"ack/off t{k}", {"detour": dnorm(res.get("detour"), me), "offRoute": res.get("offRoute")}))
    # ③ 충돌 두 대 ④ 공식 종료 + 300 s
    T2 = 13000.0
    call(base, "POST", "/api/road/reset", {"clockGuard": False})
    me = call(base, "POST", "/api/road/join", {"name": nm, "car": "그랜저", "t": T2, "lang": lang})["me"]
    cs = []
    for i in range(2):                           # 한 대만으로는 확정이 아니다(ANON_CONFIRM 2) — 두 대째에서 확정
        c = call(base, "POST", "/api/road/join", {"name": f"y{i}", "car": "", "t": T2, "lang": lang})["me"]
        cs.append(c)
        call(base, "POST", "/api/road/state", {"me": c, "t": T2 + 1, "s": 26500.0 + 20 * i, "speed": 25.0})
        call(base, "POST", "/api/road/event", {"me": c, "t": T2 + 2, "type": "IMPACT", "value": "25.0→0.0 m/s", "s": 26500.0 + 20 * i, "speed": 0.0})
        call(base, "POST", "/api/road/state", {"me": c, "t": T2 + 3, "s": 26500.0 + 20 * i, "speed": 0.0})
    for k, ms in ((4, 20000.0), (5, 23000.0)):
        res = call(base, "POST", "/api/road/state", {"me": me, "t": T2 + k, "s": ms, "speed": 25.0})
        out.append((f"impact s{ms:.0f}", {"detour": dnorm(res.get("detour"), me), "hazards": [(h["id"], h["type"], h["ahead"], h["confirmed"]) for h in res.get("hazards", [])]}))
    call(base, "POST", "/api/road/official", {"me": cs[0], "t": T2 + 6, "events": [
        {"type": "ACCIDENT", "s": 26520.0, "start": T2, "end": T2 + 20, "desc": "사고 처리"}]})
    for k in (8, 19, 21, 30, 321):               # 종료 T2+20: 그 전에는 사고 의심(h1) 기준, 뒤에는 서 있는 차들의 정체 기준
        for i, c in enumerate(cs):
            call(base, "POST", "/api/road/state", {"me": c, "t": T2 + k, "s": 26500.0 + 20 * i, "speed": 0.0})
        res = call(base, "POST", "/api/road/state", {"me": me, "t": T2 + k, "s": 20000.0, "speed": 0.0})
        out.append((f"procEnd t{k}", {"detour": dnorm(res.get("detour"), me), "hazards": [(h["id"], h["type"], h["ahead"], h["confirmed"]) for h in res.get("hazards", [])]}))
    return out


def run_rest(base, lang):
    """휴게소 제외(11-08 수정)·해제 뒤 재보고: ① 기흥휴게소(s 27119) 100 m 앞 본선 위(위경도 = 경로 위 점) 충돌 두 대가 멈춰도 사고 의심 유지
    ② 같은 자리지만 위경도가 경로에서 옆으로 약 70 m(휴게소 주차장) — 사고 의심을 지운다 ③ 위경도 없이 offRoute false(본선) → 유지, 아무것도 없음 → 이전처럼 지움
    ④ 정체 두 대 → 둘 다 다시 달려 해제 → 120 s 안 재보고 → 해제 표시가 지워져 해제 + TTL 뒤에도 남는다"""
    import link_server as ls                     # 경로 위 점(위경도)만 빌린다 — 허브 상태와는 무관
    out = []
    nm = "아빠" if lang == "ko" else "Dad"
    rest_s = 27119.0

    def crash(T, latlon=None, hint=None):
        call(base, "POST", "/api/road/reset", {"clockGuard": False})
        me = call(base, "POST", "/api/road/join", {"name": nm, "car": "그랜저", "t": T, "lang": lang})["me"]
        call(base, "POST", "/api/road/state", {"me": me, "t": T, "s": rest_s - 6000, "speed": 25.0})
        cs = []
        for i in range(2):
            c = call(base, "POST", "/api/road/join", {"name": f"r{i}", "car": "", "t": T, "lang": lang})["me"]
            cs.append(c)
            sx = rest_s + 100 + 20 * i
            body = {"me": c, "t": T + 1, "s": sx, "speed": 25.0}
            call(base, "POST", "/api/road/state", body)
            call(base, "POST", "/api/road/event", {"me": c, "t": T + 2, "type": "IMPACT", "value": "25.0→0.0 m/s", "s": sx, "speed": 0.0})
        for k in (3, 20, 45):
            for i, c in enumerate(cs):
                sx = rest_s + 100 + 20 * i
                body = {"me": c, "t": T + k, "s": sx, "speed": 0.0}
                if latlon:
                    lat, lon = latlon(sx)
                    body.update({"lat": lat, "lon": lon})
                if hint is not None:
                    body["offRoute"] = hint
                call(base, "POST", "/api/road/state", body)
        v = call(base, "POST", "/api/road/state", {"me": me, "t": T + 46, "s": rest_s - 6000, "speed": 25.0})
        return [(h["id"], h["type"], h["ahead"], h["confirmed"]) for h in v.get("hazards", [])]

    on = lambda sx: tuple(ls.point_at(sx))
    side = lambda sx: (ls.point_at(sx)[0], ls.point_at(sx)[1] + 0.0008)   # 경로(남북)에서 동쪽으로 약 70 m
    out.append(("rest mainline crash", crash(14000.0, on)))
    out.append(("rest parking crash", crash(14500.0, side)))
    out.append(("rest no latlon offRoute false", crash(15000.0, None, False)))
    out.append(("rest no latlon offRoute true", crash(15250.0, None, True)))
    out.append(("rest no latlon (old rule)", crash(15500.0)))
    # ④ 해제 뒤 재보고
    T = 16000.0
    call(base, "POST", "/api/road/reset", {"clockGuard": False})
    me = call(base, "POST", "/api/road/join", {"name": nm, "car": "그랜저", "t": T, "lang": lang})["me"]
    cs = [call(base, "POST", "/api/road/join", {"name": f"q{i}", "car": "", "t": T, "lang": lang})["me"] for i in range(2)]
    for i, c in enumerate(cs):
        call(base, "POST", "/api/road/state", {"me": c, "t": T + 1, "s": 22000.0 + 30 * i, "speed": 3.0})
        call(base, "POST", "/api/road/event", {"me": c, "t": T + 1, "type": "CONGESTION", "value": "11km/h", "s": 22000.0 + 30 * i, "speed": 3.0})
    for i, c in enumerate(cs):                   # 둘 다 다시 달린다 → 해제(cleared)
        call(base, "POST", "/api/road/state", {"me": c, "t": T + 10, "s": 22100.0 + 30 * i, "speed": 25.0})
    for i, c in enumerate(cs):                   # 60 s 뒤 다시 막힘 — 같은 위험에 합쳐진다
        call(base, "POST", "/api/road/state", {"me": c, "t": T + 70, "s": 22100.0 + 30 * i, "speed": 3.0})
        call(base, "POST", "/api/road/event", {"me": c, "t": T + 70, "type": "CONGESTION", "value": "11km/h", "s": 22100.0 + 30 * i, "speed": 3.0})
    for k in (71, 140, 200):                     # 해제(T+10) + TTL 120 = T+130 을 지나도 남아야 한다
        for i, c in enumerate(cs):
            call(base, "POST", "/api/road/state", {"me": c, "t": T + k, "s": 22100.0 + 30 * i, "speed": 3.0})
        v = call(base, "POST", "/api/road/state", {"me": me, "t": T + k, "s": 17000.0, "speed": 25.0})
        out.append((f"re-report t{k}", [(h["id"], h["type"], h["ahead"], h["confirmed"]) for h in v.get("hazards", [])]))
    return out


def compare(ra, rb, tag):
    bad = 0
    for (na, va), (_, vb) in zip(ra, rb):
        if norm(va) != norm(vb):
            bad += 1
            if bad <= 3:
                da, db = json.dumps(norm(va), ensure_ascii=False, sort_keys=True), json.dumps(norm(vb), ensure_ascii=False, sort_keys=True)
                i = next((k for k in range(min(len(da), len(db))) if da[k] != db[k]), 0)
                print(f"[{na}] 다름 @{i}\n  PC : …{da[max(0, i - 150):i + 150]}\n  앱 : …{db[max(0, i - 150):i + 150]}")
    if len(ra) != len(rb):
        bad += abs(len(ra) - len(rb))
    print(f"{tag}: {len(ra) - bad}/{len(ra)} 일치")
    return bad


def main(a, b, lang="ko", ignore=""):
    IGNORE.update(k for k in ignore.removeprefix("ignore=").split(",") if k)
    compare(run(a, lang), run(b, lang), f"road {lang}")
    compare(run_ev(a, lang), run_ev(b, lang), f"ev {lang}")
    compare(run_schema(a, lang), run_schema(b, lang), f"schema {lang}")
    compare(run_skew(a, lang), run_skew(b, lang), f"skew {lang}")
    compare(run_limit(a, lang), run_limit(b, lang), f"limit {lang}")
    compare(run_units(a, lang), run_units(b, lang), f"units {lang}")
    compare(run_ride(a, lang), run_ride(b, lang), f"ride {lang}")
    compare(run_detour(a, lang), run_detour(b, lang), f"detour {lang}")
    compare(run_rest(a, lang), run_rest(b, lang), f"rest {lang}")


if __name__ == "__main__":
    main(*sys.argv[1:])
