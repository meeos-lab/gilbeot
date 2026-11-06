"""frames.json(시뮬레이션 1초 기록) → 애니메이션 페이지용 축약 데이터 anim.json.

사용: python -X utf8 anim_data.py [시나리오 이름들...]  (기본: none tago)
창: 사고 지점 앞 1.5 km ~ 뒤 0.3 km, 사고 20초 전 ~ 8분 뒤, 2초 간격.
한 프레임 = [시각(사고 뒤 초), x, 차로, km/h, 표시, x, 차로, km/h, 표시, ...]  x 는 창 왼쪽부터 m(정수), 표시 = 1 경고 받음 + 2 앱 차 + 4 화물
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
BEFORE, AFTER, BACK, AHEAD, EVERY = 1500, 300, 20, 480, 2


def main(names):
    d = json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    inc, t_inc = d["inc"], d["t_inc"]
    out = {"window": BEFORE + AFTER, "inc": BEFORE, "lanes": d["lanes"], "every": EVERY, "runs": []}
    for r in d["runs"]:
        key = r["scenario"] if not r["p"] else f'{r["scenario"]}@{int(r["p"] * 100)}'
        if key not in names and r["scenario"] not in names:
            continue
        frames = []
        for t, cars in r["frames"]:
            rel = t - t_inc
            if rel < -BACK or rel > AHEAD or int(round(t)) % EVERY:
                continue
            row = [int(rel)]
            for x, lane, v, warned, eq, truck in cars:
                xr = x - (inc - BEFORE)
                if 0 <= xr <= BEFORE + AFTER:
                    row += [int(xr), lane, int(round(v * 3.6)), warned + 2 * eq + 4 * truck]
            frames.append(row)
        out["runs"].append({"key": key, "title": r["title"], "tagoAt": None if r["tago_at"] is None else round(r["tago_at"] - t_inc, 1),
                            "stats": {k: r["stats"][k] for k in ("conflicts", "severe", "crashes", "travel_s")}, "frames": frames})
    p = HERE / "anim.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(p, p.stat().st_size // 1024, "KB", [(r["key"], len(r["frames"])) for r in out["runs"]])


if __name__ == "__main__":
    main(sys.argv[1:] or ["none", "tago"])
