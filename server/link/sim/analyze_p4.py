"""검토 뒤 보강 P4 — E1 공식 지연 다중 추출(탐색, 판정 규칙 없음) — 사전 고정 docs/sim-preregistration.md
'## 검토 뒤 보강 실험 P1~P8' 의 P4.
  python -X utf8 analyze_p4.py [--d1 results/e_delay.jsonl] [--d2 results/e_delay2.jsonl] [--out results/report_p4]
  → results/report_p4.json, results/report_p4.md

입력
- e_delay.jsonl: 추출 1(ov 없음), 씨앗 1~24 × official·단계·u80.
- e_delay2.jsonl: 추출 2~4(ov {"delay_draw": k}), 같은 씨앗·방식.
- data/its_registration_delay.json: 원 분포 delay_s(경부선 140쌍, 음수는 0).
통계량
- (씨앗, 추출) 쌍마다 같은 씨앗·같은 추출의 official 대비 변화율 % = (처리−대조)/대조×100, 대조 0 인 쌍 제외.
  방식별 평균 = 쌍 전체 평균. CI = 씨앗 군집 재표본(씨앗 24 복원 추출 10,000회, random.Random("p"); 뽑힌 씨앗의 추출 전부),
  백분위 95 %. 같은 재표본 행렬을 모든 칸에.
- 추출별 평균(추출 1·2·3·4 각각, 씨앗 24)도 같은 재표본으로.
- 추출된 official_delay(기준선 레코드) 분위수 10·25·50·75·90 % 대 원 분포, scipy.stats.ks_2samp p.
부분 자료: 있는 쌍으로 계산하고 머리에 '부분 자료 — 확정 결과 아님'과 빠진 수. 파일이 없으면 그 절은 '자료 없음'.
"""
import argparse
import json
from pathlib import Path

from analyze_p import (DATA, METRICS, MNAME, N_BOOT, RES, RNG_KEY, SEEDS, Boot, fnum, fpct, fval, has0, jsonable, quant,
                       read_jsonl)

O = "official"
P = "official+tago12+relay"
SCH = [(O, "base", "기준선(공식 안내)"), (P, "graded", "단계 90·70·50"), (P + "-u80", "u80", "일률 80")]
NM = {k: n for _, k, n in SCH}
DRAWS = (1, 2, 3, 4)
QS = (0.10, 0.25, 0.50, 0.75, 0.90)
E1_REPORT = "report_e.md 의 E1(추출 1, rng \"e\"): 일률 80 고속 접근 −6.3 %, CI 0 포함"


def load(d1, d2):
    """→ t[키][(씨앗, 추출)] = 레코드, 파일 상태"""
    inv = {s: k for s, k, _ in SCH}
    t, st = {}, {}
    for path, which in ((d1, "d1"), (d2, "d2")):
        recs, ex, bad = read_jsonl(path)
        st[which] = {"exists": ex, "bad_lines": bad}
        for r in recs:
            if r.get("scheme") not in inv or r.get("false") or r.get("seed") not in SEEDS:
                continue
            ov = r.get("ov") or {}
            if which == "d1":
                if ov:
                    continue
                k = 1
            else:
                k = ov.get("delay_draw")
                if k not in (2, 3, 4) or set(ov) != {"delay_draw"}:
                    continue
            t.setdefault(inv[r["scheme"]], {})[(r["seed"], k)] = r
    return t, st


def main():
    from scipy.stats import ks_2samp
    ap = argparse.ArgumentParser()
    ap.add_argument("--d1", default=str(RES / "e_delay.jsonl"))
    ap.add_argument("--d2", default=str(RES / "e_delay2.jsonl"))
    ap.add_argument("--out", default=str(RES / "report_p4"))
    a = ap.parse_args()
    t, fst = load(a.d1, a.d2)
    exp = {1: 24 * 3, 2: 24 * 3, 3: 24 * 3, 4: 24 * 3}
    have = {k: sum(1 for key in t for (s, d) in t[key] if d == k) for k in DRAWS}
    miss = {k: exp[k] - have[k] for k in DRAWS}
    n_miss = sum(miss.values())
    partial = n_miss > 0
    status = {"files": fst, "expected": exp, "present": have, "missing": miss,
              "by_scheme": {k: {d: sum(1 for (s, dd) in t.get(k, {}) if dd == d) for d in DRAWS} for k in NM},
              "truncated": sum(bool(r.get("truncated")) for k in t for r in t[k].values())}

    def per_seed(k, met, draws):
        """씨앗별 목록(그 씨앗의 추출들에서 기준선 대비 변화율)."""
        out = []
        for s in SEEDS:
            vs = []
            for d in draws:
                x, c = t.get(k, {}).get((s, d)), t.get("base", {}).get((s, d))
                if x is None or c is None or c.get(met) in (None, 0) or x.get(met) is None:
                    continue
                vs.append((x[met] - c[met]) / c[met] * 100)
            out.append(vs or None)
        return out

    def raw(k, met, draws):
        out = []
        for s in SEEDS:
            vs = [t[k][(s, d)][met] for d in draws if (s, d) in t.get(k, {}) and t[k][(s, d)].get(met) is not None]
            out.append(vs or None)
        return out

    bt = Boot(SEEDS, RNG_KEY)
    for met in METRICS:
        for k in NM:
            bt.add(("raw", k, met, "all"), raw(k, met, DRAWS))
            for d in DRAWS:
                bt.add(("raw", k, met, d), raw(k, met, (d,)))
        for k in ("graded", "u80"):
            bt.add(("chg", k, met, "all"), per_seed(k, met, DRAWS))
            bt.add(("chg", k, met, "rest"), per_seed(k, met, (2, 3, 4)))
            for d in DRAWS:
                bt.add(("chg", k, met, d), per_seed(k, met, (d,)))
    bt.run()
    G = bt.get

    # ---- 지연 분포
    orig = []
    dj_path = DATA / "its_registration_delay.json"
    if dj_path.exists():
        dj = json.loads(dj_path.read_text(encoding="utf-8"))
        orig = [max(0.0, float(x)) for x in (dj.get("delay_s") or dj.get("delays_s") or [])]
    drawn = {d: [r["official_delay"] for (s, dd), r in sorted(t.get("base", {}).items()) if dd == d and r.get("official_delay") is not None] for d in DRAWS}
    pooled = [x for d in DRAWS for x in drawn[d]]
    incons = 0
    for (s, d), r in t.get("base", {}).items():
        vs = {t[k][(s, d)].get("official_delay") for k in NM if (s, d) in t.get(k, {})}
        incons += len(vs) > 1
    dist = {"orig": {"n": len(orig), "q": {f"{int(q * 100)}": quant(orig, q) for q in QS}} if orig else None,
            "drawn_all": {"n": len(pooled), "q": {f"{int(q * 100)}": quant(pooled, q) for q in QS}} if pooled else None,
            "drawn_by_draw": {d: ({"n": len(v), "q": {f"{int(q * 100)}": quant(v, q) for q in QS}} if v else None) for d, v in drawn.items()},
            "ks_2samp_p": float(ks_2samp(pooled, orig).pvalue) if pooled and orig else None,
            "ks_2samp_stat": float(ks_2samp(pooled, orig).statistic) if pooled and orig else None,
            "seed_draw_inconsistent_across_schemes": incons}

    u_all, u_1 = G(("chg", "u80", "fast", "all")), G(("chg", "u80", "fast", 1))
    if u_all is None or u_all["ci"] is None:
        e1_line = "자료 없음 — 비교 불가."
    elif not any(have[d] for d in (2, 3, 4)):
        e1_line = f"추출 2~4 자료 없음 — 비교 보류(지금 값은 추출 1 만: 일률 80 고속 접근 {fpct(u_1)}, rng \"p\"; {E1_REPORT})."
    else:
        inc0 = has0(u_all) == "포함"
        e1_line = (f"일률 80 고속 접근 변화율: 네 추출 합산 {fpct(u_all)}(CI 0 {has0(u_all)}) 대 추출 1 만 {fpct(u_1)}(같은 rng \"p\"); "
                   f"{E1_REPORT}. 결론(효과가 공식 지연에 의존해 경험 지연에서는 CI 가 0 을 포함)은 "
                   + ("유지된다." if inc0 else "달라진다(합산 CI 가 0 을 벗어남)."))

    out = {"note": "탐색. 변화율 % = (처리−대조)/대조×100, 대조 = 같은 씨앗·같은 추출의 official, 대조 0 쌍 제외. 방식별 평균 = 쌍 전체 평균. "
                   '95 % CI = 씨앗 군집 재표본(씨앗 24 복원 추출 10,000회, random.Random("p"), 모든 칸 같은 재표본), 백분위.',
           "inputs": {"d1": a.d1, "d2": a.d2}, "status": status, "partial": partial, "n_missing": n_miss,
           "cells": {"|".join(map(str, k)): jsonable(G(k)) for k in bt.vecs}, "delay": dist, "e1_compare": e1_line}
    stem = Path(a.out)
    stem.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- MD
    fs = lambda w, p: f"{Path(p).name} " + ("파일 없음" if not fst[w]["exists"] else f"깨진 줄 {fst[w]['bad_lines']}개")
    L = ["# 검토 뒤 보강 P4 — E1 공식 지연 다중 추출 (PC, 탐색)", "",
         f"실행: `python -X utf8 analyze_p4.py` (server/link/sim 에서; 입력 `{Path(a.d1).name}`(추출 1), `{Path(a.d2).name}`(추출 2~4))", "",
         f"**자료 상태: {fs('d1', a.d1)}, {fs('d2', a.d2)}; 추출별 실행 수 " + ", ".join(f"{d}: {have[d]}/{exp[d]}" for d in DRAWS)
         + (f". 부분 자료 — 확정 결과 아님(빠진 실행 {n_miss}개).**" if partial else ". 모두 갖춰짐.**"), "",
         "변화율 % = (처리−대조)/대조×100, 대조 = 같은 씨앗·같은 추출의 기준선(official), 대조 0 인 쌍 제외. 방식별 평균 = (씨앗, 추출) 쌍 전체의 평균. "
         f"괄호는 씨앗 군집 부트스트랩 95 % CI(씨앗 24 복원 추출 {N_BOOT:,}회, 뽑힌 씨앗의 추출 전부, random.Random(\"{RNG_KEY}\"), 모든 칸 같은 재표본, 백분위).", ""]
    if not t:
        L += ["## P4", "", "자료 없음.", ""]
    else:
        L += ["## 표 P4-1. 기준선 대비 변화율 %(네 추출 합산)", "",
              "| 방식 | " + " | ".join(f"{MNAME[m]}" for m in METRICS) + " | 쌍 수(고속) |", "|---|" + "---|" * len(METRICS) + "---|"]
        for k in ("graded", "u80"):
            c = G(("chg", k, "fast", "all"))
            L.append(f"| {NM[k]} | " + " | ".join(fpct(G(("chg", k, m, "all"))) for m in METRICS) + f" | {c['n_values'] if c else 0} |")
        L += ["", "## 표 P4-2. 추출별 기준선 대비 변화율 %(추출마다 씨앗 24)", "",
              "| 방식 | 지표 | " + " | ".join(f"추출 {d}" for d in DRAWS) + " | 추출 2~4 합산 |", "|---|---|" + "---|" * (len(DRAWS) + 1)]
        for k in ("graded", "u80"):
            for m in METRICS:
                L.append(f"| {NM[k]} | {MNAME[m]} | " + " | ".join(fpct(G(("chg", k, m, d))) for d in DRAWS) + f" | {fpct(G(('chg', k, m, 'rest')))} |")
        L += ["", "## 표 P4-3. 지표 평균(쌍 평균 수)", "", "| 방식 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for k in NM:
            L.append(f"| {NM[k]} | " + " | ".join(fval(G(("raw", k, m, "all"))) for m in METRICS) + " |")
        L.append("")
    L += ["## 표 P4-4. 공식 안내 지연(s): 추출된 값 대 원 분포", ""]
    if not pooled:
        L += ["추출 자료 없음." + (f" 원 분포 n={len(orig)}." if orig else ""), ""]
    else:
        L += ["| 분포 | n | " + " | ".join(f"{int(q * 100)} %" for q in QS) + " |", "|---|---|" + "---|" * len(QS)]
        if orig:
            L.append(f"| 원 분포(경부선 ITS–DB 쌍, 음수→0) | {len(orig)} | " + " | ".join(fnum(dist["orig"]["q"][f"{int(q * 100)}"]) for q in QS) + " |")
        L.append(f"| 추출 전부(기준선 레코드) | {len(pooled)} | " + " | ".join(fnum(dist["drawn_all"]["q"][f"{int(q * 100)}"]) for q in QS) + " |")
        for d in DRAWS:
            dd = dist["drawn_by_draw"][d]
            if dd:
                L.append(f"| 추출 {d} | {dd['n']} | " + " | ".join(fnum(dd["q"][f"{int(q * 100)}"]) for q in QS) + " |")
        L += ["", f"KS 검정(추출 전부 대 원 분포, scipy.stats.ks_2samp): D = {fnum(dist['ks_2samp_stat'], 3)}, p = {fnum(dist['ks_2samp_p'], 3)}. "
              f"같은 (씨앗, 추출) 안에서 방식마다 지연이 다른 경우 {incons}개(0 이어야 함).", ""]
    L += ["## E1 단일 추출과 비교", "", e1_line, ""]
    stem.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ {stem.with_suffix('.json')}, {stem.with_suffix('.md')}" + (" (부분 자료)" if partial else ""))


if __name__ == "__main__":
    main()
