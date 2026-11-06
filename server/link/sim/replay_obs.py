"""실측: 사고일의 콘존·시간대 평균 속도와 평소(앞뒤 4주 같은 요일 같은 시각) 비교 → data/obs.json

자료: 한국도로공사 '노선별 방향별 일별 1시간 구간통행속도'(data.ex.co.kr VDS C6), data/vds/vds_YYYYMM.csv(cp949).
하행 = 콘존 ID 0010CZS***. 일반 차로(차로유형 1)만. 속도 0.00 은 결측으로 뺀다.
사고: 도로공사 고속도로 교통사고 상세현황(공공데이터포털 15145192)에서 고른 아침 출근 시간 하행 사고.
"""
import csv
import datetime as dt
import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent
VDS = HERE / "data" / "vds"
# 콘존(하행) 이정: 위키백과 경부고속도로 나들목 표, 서울TG 는 OSM 요금소를 경로에 투영해 신갈JC 에서 7.7 km(판교IC 로 검산 0.1 km 안)
ZONES = {"0010CZS470": ("판교IC-서울TG", 406.94, 402.6), "0010CZS460": ("서울TG-신갈JC", 402.6, 394.96),
         "0010CZS450": ("신갈JC-수원신갈IC", 394.96, 392.28), "0010CZS440": ("수원신갈IC-기흥IC", 392.28, 387.19)}
INCIDENTS = [  # 날짜, 시각, 이정(km), 사상자, 원인
    ("2023-07-04", "07:10", 392.8, "부상 5", "주시태만"),
    ("2023-11-03", "07:28", 392.5, "부상 1", "안전거리 미확보"),
    ("2025-01-09", "07:05", 393.7, "없음", "안전거리 미확보"),
    ("2025-04-14", "07:20", 392.0, "부상 1", "과속"),
]
HOURS = range(5, 12)


def load(months):
    out = {}
    for m in months:
        p = VDS / f"vds_{m}.csv"
        if not p.exists():
            continue
        with p.open(encoding="cp949") as f:
            for r in csv.DictReader(f):
                if r["콘존ID"] in ZONES and r["차로유형구분코드"] == "1":
                    v = float(r["평균속도"])
                    if v > 0:
                        out[(r["집계일자"], r["콘존ID"], int(r["집계시"]))] = v
    return out


def main():
    res = []
    for day, hhmm, km, hurt, cause in INCIDENTS:
        d = dt.date.fromisoformat(day)
        months = sorted({(d + dt.timedelta(days=k)).strftime("%Y%m") for k in (-28, 0, 28)})
        data = load(months)
        base_days = [(d + dt.timedelta(days=7 * k)).isoformat() for k in (-4, -3, -2, -1, 1, 2, 3, 4)]
        zones = {}
        for z, (name, a, b) in ZONES.items():
            rows = {}
            for h in HOURS:
                v = data.get((day, z, h))
                base = [data[(bd, z, h)] for bd in base_days if (bd, z, h) in data]
                if v is None or len(base) < 3:
                    continue
                med = statistics.median(base)
                rows[h] = {"day": v, "base_med": med, "base_min": min(base), "base_max": max(base), "n": len(base), "ratio": v / med}
            zones[z] = {"name": name, "from_km": a, "to_km": b, "hours": rows}
        res.append({"day": day, "time": hhmm, "km": km, "hurt": hurt, "cause": cause, "weekday": d.strftime("%a"),
                    "base_days": base_days, "zones": zones})
        print(f"\n== {day} {hhmm} {km} km {hurt} {cause}")
        for z, e in zones.items():
            print(f"  {e['name']:16s}", " ".join(f"{h:02d}시 {r['day']:4.0f}/{r['base_med']:3.0f}({r['ratio']:.2f})" for h, r in e["hours"].items() if 6 <= h <= 10))
    (HERE / "data" / "obs.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
