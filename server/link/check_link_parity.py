"""도로 링크 엔진 일치 확인: PC 서버(link_server.py)와 앱 내장 서버(LinkHub.kt)에 같은 요청을 보내고 결과를 비교한다.

사용: python check_link_parity.py http://127.0.0.1:8788 http://127.0.0.1:8791 [ko|en]
도로 링크는 서버 전체가 하나의 도로라 시작할 때 /api/road/reset으로 비운다. 그룹 id·코드(무작위)는 비교에서 뺀다.
"""
import json
import sys
import urllib.request


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def norm(o):
    if isinstance(o, dict):
        return {k: norm(v) for k, v in o.items() if k not in ("group", "code", "id", "me", "car", "now", "t") or isinstance(v, (dict, list))}
    if isinstance(o, list):
        return [norm(x) for x in o]
    if isinstance(o, float) and o == int(o):
        return int(o)
    return o


def run(base, lang):
    """대본: 내 차(나)가 도로 링크에 들어가 시연 도로를 부르고, 가족 그룹(삼촌·이모)+휴대폰 참가자(고모)를 더한 뒤 170초 주행"""
    out = []
    call(base, "POST", "/api/road/reset", {})
    T0 = 1000.0
    r = call(base, "POST", "/api/road/join", {"name": "아빠" if lang == "ko" else "Dad", "car": "그랜저", "t": T0, "lang": lang})
    me = r["me"]
    out.append(("join", r["view"]))
    s = 18000.0
    out.append(("state0", call(base, "POST", "/api/road/state", {"me": me, "t": T0, "s": s, "speed": 25, "soc": 72})))
    out.append(("demo", call(base, "POST", "/api/road/demo", {"me": me, "t": T0})))
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
        if k == 150:                                     # 충전이 시작됐다 → 고장 의심 해제, 대기 보고는 남는다
            out.append(("charge ok", call(base, "POST", "/api/road/event", {"me": me, "t": t, "s": 27119, "speed": 0, "type": "CHARGE_OK", "value": "charging"})))
            out.append(("charge web2", call(base, "GET", f"/api/road?me={web}&t={t + 1}")))
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
    return out


def main(a, b, lang="ko"):
    ra, rb = run(a, lang), run(b, lang)
    bad = 0
    for (na, va), (_, vb) in zip(ra, rb):
        if norm(va) != norm(vb):
            bad += 1
            if bad <= 3:
                da, db = json.dumps(norm(va), ensure_ascii=False, sort_keys=True), json.dumps(norm(vb), ensure_ascii=False, sort_keys=True)
                i = next((k for k in range(min(len(da), len(db))) if da[k] != db[k]), 0)
                print(f"[{na}] 다름 @{i}\n  PC : …{da[max(0, i - 150):i + 150]}\n  앱 : …{db[max(0, i - 150):i + 150]}")
    print(f"road {lang}: {len(ra) - bad}/{len(ra)} 일치")


if __name__ == "__main__":
    main(*sys.argv[1:])
