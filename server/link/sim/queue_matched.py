"""정체 길이를 실측과 같은 방식으로 다시 재기(표 7, Elicit 검토 4번 '같은 관측 연산자').

  python -X utf8 queue_matched.py run      # v2 기준선 씨앗 1~24 를 그림 기록(10 s × 100 m 속도 칸)과 함께 다시 돌림
  python -X utf8 queue_matched.py report   # → results/queue_matched.json, .md
실측(evidence.py): 1시간 콘존 속도가 평소의 0.7 미만인 콘존이 사고 지점부터 위쪽으로 끊기지 않고 이어진 끝까지(콘존 경계까지) 거리,
사고 시각부터 4시간 중 최대, 사고 콘존이 0.7 미만이 된 '정체를 만든 사고'만.
시뮬레이션에 같은 규칙을 씌운다: 사고 지점 = 393.5 km(신갈JC~수원신갈IC 가운데), 위쪽 콘존은 실제 경부선 하행 콘존 경계,
시간 창은 사고가 정시 20분에 났다고 보고 −20~40·40~100·100~160·160~220분, 평소 = 사고 전 10분 같은 칸 평균 속도.
"""
import json
import multiprocessing as mp
import os
import statistics
import sys
from pathlib import Path

import tago_sim as S

HERE = Path(__file__).parent
OUT = S.RES / "queue_matched.jsonl"
KM0, Z0 = 393.5, "0010CZS450"
WINDOWS = [(-20, 40), (40, 100), (100, 160), (160, 220)]   # 사고 뒤 분


def run(seed):
    r = S.run_one((S.cond_for(seed), "official", False, True))
    return {"seed": seed, "queue_km": r["queue_km"], "grid": r["record"]["grid"], "t_inc": S.T_INC}


def run_all():
    done = set()
    if OUT.exists():
        done = {json.loads(x)["seed"] for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()}
    todo = [s for s in range(1, 25) if s not in done]
    with mp.get_context("spawn").Pool(int(os.environ.get("TAGO_PROCS", 4))) as pool, OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(pool.imap_unordered(run, todo), 1):
            f.write(json.dumps(r) + "\n"); f.flush()
            print(f"  {i}/{len(todo)} 씨앗 {r['seed']}", flush=True)


def chain():
    zones = json.loads((HERE / "data" / "gyeongbu_conzones.json").read_text(encoding="utf-8"))
    out, cur = [Z0], zones[Z0]
    while True:
        nxt = [z for z, e in zones.items() if e["dir"] == "S" and abs(e["to_km"] - cur["from_km"]) < 0.05]
        if not nxt:
            break
        out.append(nxt[0]); cur = zones[nxt[0]]
        if cur["from_km"] - KM0 > 19:          # 모형 상류 20 km 안
            break
    return [(z, zones[z]["from_km"], zones[z]["to_km"]) for z in out]


def extent(grid, t_inc, segs):
    """grid: [[t10, x100, v m/s]] → 시간 창마다 정체 길이(km), 첫 창 사고 콘존 비율"""
    cell = {}
    for ti, xi, v in grid:
        cell[(int(ti), int(xi))] = v
    xkm = lambda km: S.INC_POS - (km - KM0) * 1000      # 이정 → 모형 거리(m)
    def zone_speed(a_km, b_km, t0, t1):
        lo, hi = sorted((xkm(a_km), xkm(b_km)))
        lo = max(lo, 1000.0)                             # 들어오는 끝 1 km 제외
        vals = [v for (ti, xi), v in cell.items() if t0 <= ti * 10 < t1 and lo <= xi * 100 < hi and xi * 100 <= S.INC_POS]
        return statistics.mean(vals) if vals else None
    out, r0s = [], []
    for w0, w1 in WINDOWS:
        far, ok = 0.0, True
        for k, (z, a, b) in enumerate(segs):
            pre = zone_speed(a, b, t_inc - 600, t_inc)
            cur = zone_speed(a, b, t_inc + w0 * 60, t_inc + w1 * 60)
            r = (cur / pre) if (pre and cur) else None
            if k == 0:
                r0s.append(r)
            if r is None or r >= 0.7:
                break
            far = a - KM0                                # 그 콘존의 위쪽 경계까지
        out.append(round(far, 2))
    return out, r0s


def report():
    segs = chain()
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    res = []
    for r in sorted(rows, key=lambda r: r["seed"]):
        ext, r0 = extent(r["grid"], r["t_inc"], segs)
        impact = any(x is not None and x < 0.7 for x in r0[:2])
        res.append({"seed": r["seed"], "ext_km": ext, "max_ext": max(ext), "impact": impact, "direct_queue_km": r["queue_km"]})
    imp = [x for x in res if x["impact"]]
    mx = sorted(x["max_ext"] for x in imp)
    summ = {"n": len(res), "n_impact": len(imp), "median": statistics.median(mx) if mx else None,
            "p90": mx[int(0.9 * len(mx))] if mx else None, "over6": round(sum(1 for v in mx if v > 6) / len(mx), 3) if mx else None,
            "direct_median": statistics.median(x["direct_queue_km"] for x in res)}
    field = json.loads((S.RES / "evidence.json").read_text(encoding="utf-8"))["ext_impact"]
    try:
        from scipy.stats import ks_2samp
        fv = [r["max_ext"] for r in json.loads((S.RES / "evidence.json").read_text(encoding="utf-8"))["rows"] if r.get("impact")]
        ks = ks_2samp(mx, fv)
        summ["ks_p"] = round(float(ks.pvalue), 3)
    except Exception:
        pass
    (S.RES / "queue_matched.json").write_text(json.dumps({"segments": segs, "summary": summ, "field": field, "runs": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# 정체 길이: 실측과 같은 측정 방식", "", f"콘존: {', '.join(f'{z}({a}→{b})' for z, a, b in segs)}", "",
         "| | 실측(정체를 만든 사고) | 시뮬레이션 v2 기준선(같은 방식) | 시뮬레이션(차 위치로 직접) |", "|---|---|---|---|",
         f"| 표본 | {field.get('n', 157)} | {summ['n_impact']}/{summ['n']} | {summ['n']} |",
         f"| 중앙값 | {field['median_max_km']:.1f} km | {summ['median']} km | {summ['direct_median']} km |",
         f"| 90 백분위 | {field['p90_max_km']:.1f} km | {summ['p90']} km | |",
         f"| 6 km 초과 | {field['share_over_6km'] * 100:.0f} % | {summ['over6'] * 100 if summ['over6'] is not None else ''} % | |",
         "", f"KS p = {summ.get('ks_p')}"]
    (S.RES / "queue_matched.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    run_all() if (sys.argv[1] if len(sys.argv) > 1 else "run") == "run" else report()
