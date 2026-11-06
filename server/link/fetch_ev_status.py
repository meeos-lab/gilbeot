"""휴게소 충전기 공식 상태를 공공데이터로 받아 허브(/api/road/chargerstatus)에 올린다.

출처: 한국환경공단_전기자동차 충전소 정보(공공데이터포털 15076352, getChargerInfo 의 stat·statUpdDt) — 공공누리 제1유형(출처표시).
상태 코드(OpenAPI 활용가이드 v1.25 3.2절): 0 알수없음 1 통신이상 2 충전대기 3 충전중 4 운영중지 5 점검중 6 예약중 9 상태미확인. 허브는 4·5 만 '안 됨'으로 센다.
키: pleos-meeos/local.properties 의 DATA_GO_KR_KEY. 앱(APK)에는 키를 넣지 않는다 — 실제 서비스에서는 키를 가진 서버가 이 일을 한다.
대상: 경로 파일 evStations 의 충전소(fetch_ev_stations.py 가 넣은 휴게소 충전소 9곳).

사용: python fetch_ev_status.py                          # 받아서 요약만
      python fetch_ev_status.py --post http://127.0.0.1:8791   # 앱 내장 허브(adb forward tcp:8791 tcp:8790)에 올린다
      python fetch_ev_status.py --post URL --demo-down 27119:2  # 시연: 그 휴게소 충전기 앞 2대를 점검중(5)으로 바꿔 올린다(공식 데이터 아님 — 화면 시험용)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_ev_stations as F                      # noqa: E402  키 읽기·요청 함수 재사용(키 값은 출력하지 않는다)

ZCODES = ("11", "41", "44")


def main(argv):
    post = argv[argv.index("--post") + 1] if "--post" in argv else None
    demo = argv[argv.index("--demo-down") + 1] if "--demo-down" in argv else None
    route = json.loads((HERE / "gyeongbu_route.json").read_text(encoding="utf-8"))
    ev = route.get("evStations", [])
    want = {e["statId"]: e for e in ev}
    if not want:
        sys.exit("경로 파일에 evStations 가 없다 — fetch_ev_stations.py 먼저")
    k = F.key()
    got = {}
    for z in ZCODES:
        page, seen, total = 1, 0, None
        while total is None or seen < total:
            total, items = F.fetch(k, z, page, extra={"kindDetail": "C001"})   # 충전소 구분 상세 C001 = 고속도로 휴게소(활용가이드 3.6절)
            seen += len(items)
            for it in items:
                if it.get("statId") in want:
                    try:
                        st = int(it.get("stat") or 9)
                    except ValueError:
                        st = 9
                    got.setdefault(it["statId"], {})[it.get("chgerId", "")] = (st, it.get("statUpdDt", ""))
            if not items or len(got) == len(want):
                break
            page += 1
        if len(got) == len(want):
            break
    stations = []
    for sid, e in want.items():
        ch = got.get(sid, {})
        print(f"  {e['restName']}: {e['name']} — " + (", ".join(f"{cid}:{st}" for cid, (st, _) in sorted(ch.items())) or "상태 없음"))
        if ch:
            stations.append({"statId": sid, "chargers": [{"id": cid, "stat": st} for cid, (st, _) in sorted(ch.items())]})
    if demo:
        rest_s, n = demo.split(":")
        left = int(n)
        for st in stations:
            if want[st["statId"]]["rest"] == float(rest_s):
                for c in st["chargers"]:
                    if left > 0:
                        c["stat"], left = 5, left - 1
        print(f"  시연: 휴게소 s {rest_s} 충전기 {n}대를 점검중(5)으로 바꿈")
    if post:
        body = json.dumps({"t": time.time(), "stations": stations}).encode()
        req = urllib.request.Request(post.rstrip("/") + "/api/road/chargerstatus", data=body, method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
        print(f"올림: 충전소 {len(stations)}곳 → {post}")


if __name__ == "__main__":
    main(sys.argv[1:])
