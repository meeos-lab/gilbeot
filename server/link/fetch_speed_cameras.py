"""제한속도·단속 표지(11-15 사용자 "이런식으로도 표기되게해줄 수 있나 제한속도" → "네, 만들어" · "공공데이터 있잖아"): 공식 단속카메라 자료를 받아 CSV 로 고정한다.

출처: 경찰청 「전국무인교통단속카메라표준데이터」(공공데이터포털 표준데이터 OpenAPI tn_pubr_public_unmanned_traffic_camera_api)
  — 카메라마다 위치(위도·경도)·단속구분·제한속도·도로노선명·도로노선방향·설치장소·데이터기준일자
키: 환경변수 DATA_GO_KR_KEY → pleos-meeos/local.properties 의 DATA_GO_KR_KEY. 값은 출력·기록하지 않는다(오류 문구에 키가 섞이지 않게 URL 도 출력하지 않는다).
결과: speed_cameras.csv(시연 경로 둘레 상자 안의 고속도로 카메라, 원본 항목 그대로) — build_cameras.py 의 입력. 기준일은 자료의 데이터기준일자와 받은 날(DATA_SOURCES.md).

사용: python -X utf8 fetch_speed_cameras.py [--probe]   (--probe: 첫 쪽만 불러 항목 이름과 세 줄만 보여 준다)
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPS = HERE.parent.parent / "local.properties"
URL = "https://api.data.go.kr/openapi/tn_pubr_public_unmanned_traffic_camera_api"
OUT = HERE / "speed_cameras.csv"
ROWS = 1000
PAD = 0.01          # 경로 둘레 상자 여유(도, 약 1 km)


def key():
    v = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if v:
        return v
    if PROPS.is_file():
        for line in PROPS.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATA_GO_KR_KEY"):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    sys.exit("DATA_GO_KR_KEY 가 없다(환경변수 또는 local.properties)")


def call(k, page):
    sk = k if "%" in k else urllib.parse.quote(k, safe="")
    url = f"{URL}?serviceKey={sk}&" + urllib.parse.urlencode({"pageNo": page, "numOfRows": ROWS, "type": "json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if attempt == 2: return None, None, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            if attempt == 2: return None, None, type(e).__name__
        time.sleep(2)
    try:
        j = json.loads(body)
    except json.JSONDecodeError:
        return None, None, "JSON 아님(" + body[:80].replace(k, "…") + ")"
    resp = j.get("response", j)   # 이 표준데이터 API 는 response 껍데기 없이 header·body 를 바로 준다(11-15 실측)
    head = resp.get("header", {})
    if str(head.get("resultCode", "00")) not in ("00", "0"):
        return None, None, f"결과 코드 {head.get('resultCode')} {head.get('resultMsg')}"
    b = resp.get("body", {})
    items = b.get("items", [])
    if isinstance(items, dict): items = items.get("item", [])
    if isinstance(items, dict): items = [items]
    return items, int(b.get("totalCount", 0) or 0), None


def main(argv):
    k = key()
    route = json.loads((HERE / "gyeongbu_route.json").read_text(encoding="utf-8"))["route"]
    la0, la1 = min(p[0] for p in route) - PAD, max(p[0] for p in route) + PAD
    lo0, lo1 = min(p[1] for p in route) - PAD, max(p[1] for p in route) + PAD
    items, total, err = call(k, 1)
    if err: sys.exit("첫 쪽 실패: " + err)
    if "--probe" in argv:
        print("총", total, "건 · 항목:", list(items[0].keys()) if items else None)
        for it in items[:3]: print({kk: it.get(kk) for kk in list(it.keys())[:22]})
        return
    keep, page = [], 1
    while True:
        for it in items:
            try: la, lo = float(it.get("latitude") or 0), float(it.get("longitude") or 0)
            except ValueError: continue
            hw = (it.get("roadKnd") or "").strip() == "고속국도" or "경부" in (it.get("roadRouteNm") or "")
            if la0 <= la <= la1 and lo0 <= lo <= lo1 and hw: keep.append(it)   # 고속도로 행만(시내 카메라는 build_cameras 가 어차피 뺀다)
        print(f"쪽 {page}: {len(items)}건 받음, 상자 안 누적 {len(keep)}", flush=True)
        if page * ROWS >= total or not items: break
        page += 1
        items, _, err = call(k, page)
        if err: sys.exit(f"쪽 {page} 실패: " + err)
        time.sleep(0.3)
    cols = sorted({c for it in keep for c in it})
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(keep)
    print(f"총 {total}건 중 시연 경로 상자 안 {len(keep)}건 → {OUT.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
