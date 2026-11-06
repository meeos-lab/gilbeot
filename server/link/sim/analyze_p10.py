#!/usr/bin/env python
"""P10 처리 중·처리 뒤 상충 분해(사전 등록 'P10', 맥 쌍 기록만, PC 와 섞지 않음).

입력: results/mac/pairs/p9_confirm_{seed}_{scheme}.json.gz(Krauss, 정정 전 = ov 없음)와 m1_idm_b2_{seed}_{scheme}.json.gz(IDM b 2.0, T 0.4).
쌍 파일 cols 에 fast(고속 접근 여부)·phase(a 처리 중 / b 처리 뒤 정체 소멸 전 / c 소멸 뒤)가 있다.
통계량(등록대로): 방식·모형별 씨앗마다 고속 접근 쌍 수를 처리 중(a)·처리 뒤(b+c)로 나눠, 일률 80 − 단계 의 씨앗별 차이(건)·변화율 평균과 95 % CI(씨앗 복원 추출 10,000회, rng "p"); 기준선 대비도 같이. 규칙: 서술.
"""
import gzip, json, random
from pathlib import Path

import numpy as np

RES = Path(__file__).parent / "results"
PAIRS = RES / "mac" / "pairs"
SEEDS = list(range(1, 25))
SCH = {"base": "official", "graded": "official+tago12+relay", "u80": "official+tago12+relay-u80"}
NAME = {"base": "기준선", "graded": "단계 90·70·50", "u80": "일률 80"}
MODELS = {"Krauss": "p9_confirm", "IDM": "m1_idm_b2"}
N_BOOT, RNG = 10000, "p"


def load(stem, seed, scheme):
    fn = PAIRS / f"{stem}_{seed}_{scheme}.json.gz"
    if not fn.exists():
        return None
    d = json.load(gzip.open(fn, "rt", encoding="utf-8"))
    cols = d["cols"]; fi, pi = cols.index("fast"), cols.index("phase")
    a = sum(1 for r in d["rows"] if r[fi] and r[pi] == "a")
    bc = sum(1 for r in d["rows"] if r[fi] and r[pi] in ("b", "c"))
    tot = sum(1 for r in d["rows"] if r[fi])
    return {"a": a, "bc": bc, "tot": tot}


def boot_mean_ci(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    rng = random.Random(RNG); n = len(vals)
    bs = np.array([np.mean([vals[rng.randrange(n)] for _ in range(n)]) for _ in range(N_BOOT)])
    return {"mean": float(np.mean(vals)), "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "n": n}


def fmt(e, nd=1):
    if e is None:
        return "—"
    f = lambda v: ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.{nd}f}"
    return f"{f(e['mean'])} ({f(e['ci'][0])} \\~ {f(e['ci'][1])})"


def main():
    data, missing = {}, []
    for model, stem in MODELS.items():
        for k, sc in SCH.items():
            for s in SEEDS:
                r = load(stem, s, sc)
                if r is None:
                    missing.append((model, k, s))
                data[(model, k, s)] = r
    partial = bool(missing)
    L = ["# P10 처리 중·처리 뒤 고속 접근 상충 분해(맥 쌍 기록, PC 와 섞지 않음)", "",
         "실행: `python -X utf8 analyze_p10.py` (server/link/sim 에서; 입력 results/mac/pairs 의 p9_confirm_*(Krauss, 정정 전)·m1_idm_b2_*(IDM b 2.0, T 0.4))", "",
         f"**자료 상태: 빠진 파일 {len(missing)}개." + (" 부분 자료 — 확정 결과 아님.**" if partial else " 모두 갖춰짐(모형 2 × 방식 3 × 씨앗 24).**"), "",
         "고속 접근 쌍 = TTC < 1.5 s 이고 속도 차 ≥ 30 km/h 가 처음 성립한 쌍(fast). 처리 중 = phase a, 처리 뒤 = phase b + c. 차이(건) = 씨앗별 (일률 80 − 단계)의 평균, 변화율 % = 씨앗별 (일률 80 − 단계)/단계 × 100 의 평균(단계 0 인 씨앗 제외). 괄호는 씨앗 복원 추출 10,000회(rng \"p\")의 백분위 95 % CI.", ""]
    out = {"partial": partial, "missing": missing, "cells": {}}
    for model in MODELS:
        L += [f"## {model}", "", "| 비교 | 구간 | 차이(건) | 변화율 % | 단계(또는 기준선) 평균 건수 | 일률 80 평균 건수 |", "|---|---|---|---|---|---|"]
        for ref, treat, label in (("graded", "u80", "일률 80 − 단계"), ("base", "u80", "일률 80 − 기준선"), ("base", "graded", "단계 − 기준선")):
            for ph, pn in (("a", "처리 중"), ("bc", "처리 뒤"), ("tot", "전체")):
                diffs, chgs, refs, trs = [], [], [], []
                for s in SEEDS:
                    r1, r2 = data[(model, ref, s)], data[(model, treat, s)]
                    if r1 is None or r2 is None:
                        continue
                    diffs.append(r2[ph] - r1[ph]); refs.append(r1[ph]); trs.append(r2[ph])
                    chgs.append(None if r1[ph] == 0 else (r2[ph] - r1[ph]) / r1[ph] * 100)
                d, c = boot_mean_ci(diffs), boot_mean_ci(chgs)
                out["cells"][f"{model}|{treat}_vs_{ref}|{ph}"] = {"diff": d, "chg": c, "ref_mean": float(np.mean(refs)) if refs else None, "treat_mean": float(np.mean(trs)) if trs else None}
                L.append(f"| {label} | {pn} | {fmt(d)} | {fmt(c)} | {np.mean(refs):.1f} | {np.mean(trs):.1f} |" if refs else f"| {label} | {pn} | — | — | — | — |")
        L.append("")
        # 씨앗별 부호 일치(일률 80 − 단계)
        signs = {ph: sum(1 for s in SEEDS if data[(model, 'graded', s)] and data[(model, 'u80', s)] and (data[(model, 'u80', s)][ph] - data[(model, 'graded', s)][ph]) < 0) for ph in ("a", "bc", "tot")}
        L.append(f"일률 80 < 단계 인 씨앗 수(24개 중): 처리 중 {signs['a']}, 처리 뒤 {signs['bc']}, 전체 {signs['tot']}")
        out["cells"][f"{model}|signs"] = signs
        L.append("")
    (RES / "report_p10.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (RES / "report_p10.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", RES / "report_p10.md", "(부분 자료)" if partial else "")


if __name__ == "__main__":
    main()
