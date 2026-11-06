"""검증 V3 후보 사고 고르기: ITS 돌발 이력(차단 차로·처리 시간)과 도로공사 사고 상세현황(이정)을 맞춰, 모형 구간(신갈JC~기흥IC)의
사고를 방향·시간대별로 뽑는다(사전 고정 docs/sim-preregistration.md 'V3'·'V3b' — 후보 목록은 결과를 보기 전에 만든다).

  python -X utf8 v3_candidates.py       → data/v3_candidates.csv, results/v3_candidates.md
규칙(결과를 보기 전에 정함):
- ITS: 경부선, 교통사고, 본선 차단 차로 1~2개(갓길·진출입로만이면 제외), 종료 시각 있음, 처리 시간 10~180분.
- 방향: ITS roadDrcType 는 도로공사 자료의 '방향'과 반대다(사고 DB 760건과 ±10분 시각 맞춤에서 '부산'↔'서울 방향' 198건, '서울'↔'부산 방향' 239건,
  같은 표기 43건; 재현 사고일의 속도 저하도 CZS 쪽). 그래서 ITS '서울 방향' = 부산행(하행, CZS 콘존, 교통량 '기점' 방향),
  ITS '부산 방향' = 서울행(상행, CZE 콘존, 교통량 '종점' 방향).
- 시간대: 아침 06:00~09:30(교통량 07~09시 실측, 06·10시는 09시 값), 저녁 17:30~20:30(18~20시 실측, 17·21시는 18·20시 값). 교통량은
  data/commute_volume_20251231.csv(한국도로공사 상시 교통량조사, 기흥~수원신갈).
- 위치: ITS 좌표가 모형 구간(신갈JC 37.2832N~기흥IC 37.2217N, 경도 127.08~127.12) 안이면 이정을 위도로 보간한다(신갈JC 394.96 km @37.2832,
  수원신갈IC 392.28 @37.2701, 기흥IC 387.19 @37.2217; OSM Nominatim 좌표). 도로공사 사고 기록(경부선·같은 방향·이정 387.19~394.96)과
  시각 ±30분 안에서 맞으면 그 이정을 우선한다(표시 'accident').
- 재현 검증(6.1절)에 이미 쓴 사고 4건은 '기존' 으로 표시하고 검증용에서 뺀다. 콘존 속도 자료(2022-12~2026-01)가 있는 날만.
"""
import csv
import datetime as dt
from pathlib import Path

HERE = Path(__file__).parent
ITS = HERE / "data" / "its_gyeongbu_accidents.csv"
ACC = HERE / "data" / "accidents" / "accidents_2023_2025.csv"
OUT = HERE / "data" / "v3_candidates.csv"
MD = HERE / "results" / "v3_candidates.md"
FMT = "%Y-%m-%d %H:%M:%S"
KM_LO, KM_HI = 387.19, 394.96
BOX = (37.2217, 37.2832, 127.08, 127.12)
ANCH = [(37.2217, 387.19), (37.2701, 392.28), (37.2832, 394.96)]   # (위도, km)
USED = {"2023-07-04", "2023-11-03", "2025-01-09", "2025-04-14"}
DIRS = {"서울 방향": ("부산행", "부산"), "부산 방향": ("서울행", "서울")}   # ITS 표기 → (진행 방향, 사고 DB 표기)
WINDOWS = {"morning": (dt.time(6, 0), dt.time(9, 30)), "evening": (dt.time(17, 30), dt.time(20, 30))}


def km_from_lat(y):
    for (y0, k0), (y1, k1) in zip(ANCH, ANCH[1:]):
        if y0 <= y <= y1:
            return round(k0 + (k1 - k0) * (y - y0) / (y1 - y0), 2)
    return None


def main():
    acc = []
    with ACC.open(encoding="cp949") as f:
        for r in csv.DictReader(f):
            if r["노선명"] == "경부선" and r["방향"] in ("부산", "서울"):
                try:
                    km = float(r["사고발생이정"])
                except ValueError:
                    continue
                if KM_LO <= km <= KM_HI:
                    acc.append({"t": dt.datetime.strptime(r["사고일자"] + " " + r["사고시각"], "%Y-%m-%d %H:%M"), "km": km, "dir": r["방향"], "hurt": r["부상"], "cause": r["원인"]})
    rows = []
    with ITS.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["direction"] not in DIRS or not r["end"] or int(r["n_lanes"]) not in (1, 2) or int(r["ramp"]):
                continue
            travel, dbdir = DIRS[r["direction"]]
            t = dt.datetime.strptime(r["start"], FMT)
            window = next((w for w, (a, b) in WINDOWS.items() if a <= t.time() <= b), None)
            if window is None:
                continue
            dur = float(r["dur_min"]) if r["dur_min"] else None
            if dur is None or not (10 <= dur <= 180):
                continue
            x, y = float(r["x"]), float(r["y"])
            inbox = BOX[0] <= y <= BOX[1] and BOX[2] <= x <= BOX[3]
            match = [a for a in acc if a["dir"] == dbdir and abs((a["t"] - t).total_seconds()) <= 1800]
            if not inbox and not match:
                continue
            km = match[0]["km"] if match else (km_from_lat(y) if inbox else None)
            if km is None:
                continue
            rows.append({"day": t.date().isoformat(), "time": t.strftime("%H:%M"), "dir": travel, "window": window, "start": r["start"], "end": r["end"], "dur_min": dur,
                         "lanes": r["lanes"], "n_lanes": r["n_lanes"], "shoulder": r["shoulder"], "km": km, "km_source": "accident" if match else "coord(lat)",
                         "x": x, "y": y, "in_box": int(inbox), "hurt": match[0]["hurt"] if match else "", "cause": match[0]["cause"] if match else "",
                         "message": r["message"], "used_before": int(t.date().isoformat() in USED and travel == "부산행")})
    rows.sort(key=lambda r: (r["dir"], r["window"], r["start"]))
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["day"]); w.writeheader(); w.writerows(rows)
    new = [r for r in rows if not r["used_before"]]
    cnt = {(d, w): sum(1 for r in new if r["dir"] == d and r["window"] == w) for d in ("부산행", "서울행") for w in ("morning", "evening")}
    L = [f"# 검증 V3 후보 사고(모형 구간 신갈JC~기흥IC, 본선 1~2차로 차단, 종료 시각 있음, 처리 10~180분)", "",
         f"- 후보 {len(rows)}건, 기존 재현 사고 제외 {len(new)}건: " + ", ".join(f"{d} {w} {n}" for (d, w), n in cnt.items()) + f". 사고 기록과 맞은 것 {sum(1 for r in rows if r['km_source']=='accident')}건.", "",
         "| 방향 | 시간대 | 날짜 | 시각 | 처리(분) | 차단 차로 | 이정 km | 출처 | 부상 | 내용 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['dir']} | {r['window']} | {r['day']}{' (기존)' if r['used_before'] else ''} | {r['time']} | {r['dur_min']:.0f} | {r['lanes']} | {r['km']} | {r['km_source']} | {r['hurt']} | {r['message'][:36]} |")
    MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
