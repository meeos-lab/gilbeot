"""충돌 판정 점검(탐색): SUMO 가 '충돌'로 세는 쌍이 실제로 겹친 것인지, 최소 간격(minGap) 침범인지 본다.

  TAGO_COLL_DIAG=1 (v2 설정) python -X utf8 coll_check.py run    → results/coll_check.jsonl (맥, 씨앗 1~8 × 기준선·단계·일률 80; run 24 면 씨앗 1~24 — DRAC·노출 지표도 같은 실행에서)
  python -X utf8 coll_check.py report                             → results/coll_check.md
"""
import json
import os
import statistics
import sys
from collections import Counter

import tago_sim as S

OUT = S.RES / "coll_check.jsonl"
SCH = ("official", "official+tago12+relay", "official+tago12+relay-u80")


def pct_ci(pairs, key, n=10000):
    import random
    r = random.Random(key)
    est = lambda smp: statistics.mean((t - c) / c * 100 for c, t in smp if c > 0)
    bs = sorted(est([pairs[r.randrange(len(pairs))] for _ in pairs]) for _ in range(n))
    return round(est(pairs), 1), [round(bs[int(0.025 * n)], 1), round(bs[int(0.975 * n)], 1)]


def overlaps(rows):
    """실제 겹침 쌍을 상황별로: 사고 차 넣기(사고 순간 사고 차로), 옆 접촉(차로 바꾸기), 뒤 추돌. 주시태만 차 포함 여부"""
    t_inc = float(os.environ.get("TAGO_TINC", 900))
    out = {}
    for sc in SCH:
        rs = [r for r in rows if r["scheme"] == sc]
        k = Counter()
        for r in rs:
            for c in r["coll"]:
                if c[8] is None or c[8] >= 0:
                    continue
                kind = "insert" if abs(c[0] - t_inc) < 1.0 else "side" if c[1] == "side" else "rear"
                k[kind] += 1
                k["inatt"] += "car_i" in (str(c[6]) + str(c[7]))
                k["dv30"] += (c[4] - c[5]) >= 30
        out[sc] = {x: round(v / len(rs), 2) for x, v in k.items()} if rs else {}
    return out


def report():
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    L = ["# 충돌 판정 점검", "", f"실행 {len(rows)}회(씨앗 {len({r['seed'] for r in rows})}개 × 방식 3)", "",
         "| 방식 | 판정 쌍(평균) | 실제 겹침(간격 < 0) | 간격 0~1 m | 간격 1 m 이상 | 간격 모름 | 속도 차 ≥ 30 km/h | 사고 차량과 |", "|---|---|---|---|---|---|---|---|"]
    out = {}
    for sc in SCH:
        rs = [r for r in rows if r["scheme"] == sc]
        if not rs:
            continue
        cs = [c for r in rs for c in r["coll"]]
        n = len(rs)
        gaps = [c[8] for c in cs if c[8] is not None]
        k = {"pairs": len(cs) / n, "overlap": sum(1 for g in gaps if g < 0) / n, "g01": sum(1 for g in gaps if 0 <= g < 1) / n,
             "g1": sum(1 for g in gaps if g >= 1) / n, "nogap": sum(1 for c in cs if c[8] is None) / n,
             "dv30": sum(1 for c in cs if c[4] - c[5] >= 30) / n, "crash": sum(1 for c in cs if str(c[7]).startswith("crash") or "crash" in str(c[7])) / n,
             "types": Counter(c[1] for c in cs), "gap_median": statistics.median(gaps) if gaps else None}
        out[sc] = {**k, "types": dict(k["types"])}
        L.append(f"| {sc} | {k['pairs']:.0f} | {k['overlap']:.1f} | {k['g01']:.0f} | {k['g1']:.0f} | {k['nogap']:.0f} | {k['dv30']:.1f} | {k['crash']:.1f} |")
    L += ["", "판정 종류: " + "; ".join(f"{sc}: {v['types']}" for sc, v in out.items()),
          "", "간격 중앙값: " + ", ".join(f"{sc} {v['gap_median']}" for sc, v in out.items())]
    ov = overlaps(rows)
    out["overlap_kinds"] = ov
    L += ["", "실제 겹침(회당): " + "; ".join(f"{sc}: {v}" for sc, v in ov.items()) + "  (insert = 사고 차를 넣는 순간, side = 옆 접촉, rear = 뒤 추돌, inatt = 주시태만 차 포함, dv30 = 속도 차 30 km/h 이상)"]
    by = {}
    for r in rows:
        by.setdefault(r["seed"], {})[r["scheme"]] = r
    full = [d for d in by.values() if all(x in d for x in SCH)]
    if full and "drac" in full[0][SCH[0]]:
        rate = lambda r: r["fast"] / max(1, r["exposed"]) * 1000
        L += ["", f"## 기본 행동 가정에서 보조 지표(씨앗 {len(full)}개, 맥 안에서 비교)", "", "| 지표 | 일률 80 대 기준선 | 95 % CI | 일률 80 대 단계 | 95 % CI |", "|---|---|---|---|---|"]
        out["aux"] = {}
        for name, f in (("고속 접근 상충", lambda r: r["fast"]), ("DRAC > 3.35 쌍", lambda r: r["drac"]), ("노출 1,000대당 고속 접근", rate)):
            a = pct_ci([(f(d[SCH[0]]), f(d[SCH[2]])) for d in full], name + "b")
            b = pct_ci([(f(d[SCH[1]]), f(d[SCH[2]])) for d in full], name + "g")
            out["aux"][name] = {"u80_vs_baseline": a, "u80_vs_graded": b}
            L.append(f"| {name} | {a[0]:+.1f} % | {a[1][0]:+.1f} ~ {a[1][1]:+.1f} | {b[0]:+.1f} % | {b[1][0]:+.1f} ~ {b[1][1]:+.1f} |")
        ovn = lambda r: sum(1 for c in r["coll"] if c[8] is not None and c[8] < 0 and abs(c[0] - float(os.environ.get("TAGO_TINC", 900))) >= 1.0)
        m = {sc: statistics.mean(ovn(d[sc]) for d in full) for sc in SCH}
        out["aux"]["overlap_per_run_excl_insert"] = m
        L.append(f"| 실제 겹침(사고 차 넣기 제외, 회당) | 기준선 {m[SCH[0]]:.2f} · 단계 {m[SCH[1]]:.2f} · 일률 80 {m[SCH[2]]:.2f} | | | |")
    (S.RES / "coll_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (S.RES / "coll_check.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        assert S.COLL_DIAG
        S.pool_run([(S.cond_for(s), sc, False) for s in range(1, int(sys.argv[2]) + 1 if len(sys.argv) > 2 else 9) for sc in SCH], OUT)
    else:
        report()
