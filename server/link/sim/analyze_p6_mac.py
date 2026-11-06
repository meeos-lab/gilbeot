"""검토 뒤 보강 P6(a)·(b) — 맥 민감도 격자(탐색, 판정 규칙 없음) — 사전 고정 docs/sim-preregistration.md
'## 검토 뒤 보강 실험 P1~P8' 의 P6. 맥 결과만 쓰며 PC 결과와 섞지 않는다.
  python -X utf8 analyze_p6_mac.py [--grid results/mac/p6_grid.jsonl] [--lc results/mac/p6_lc.jsonl] [--out results/report_p6_mac]
  → results/report_p6_mac.json, results/report_p6_mac.md

입력
- p6_grid.jsonl: ov {"comply": 0.05|0.25|0.45|0.65|0.85} × 방식 official(기준선), official+tago{1.5,12,50}+relay(단계)·-u80, 씨앗 1~6.
- p6_lc.jsonl: ov {"lc_assert": "0.8"|"1.6"} × official·단계·u80, 씨앗 1~12.
통계량: 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 = 같은 준수율(또는 같은 lc 수준)·같은 씨앗의 official,
대조 0 씨앗 제외. 단계 대 일률 80 = 같은 칸의 u80 대 단계 변화율. CI = 씨앗 복원 추출 10,000회(random.Random("p")),
(a) 와 (b) 는 씨앗 수가 달라(6, 12) 각각의 재표본 행렬, 한 표 안에서는 같은 행렬. 백분위 95 %.
부분 자료: 있는 씨앗으로 계산하고 머리에 '부분 자료 — 확정 결과 아님'과 빠진 수. 파일이 없으면 그 절은 '자료 없음'.
"""
import argparse
import json
from pathlib import Path

from analyze_p import METRICS, MNAME, N_BOOT, RES, RNG_KEY, Boot, chg, fpct, fval, has0, jsonable, read_jsonl

O = "official"
COMPLY = (0.05, 0.25, 0.45, 0.65, 0.85)
PEN = ("1.5", "12", "50")
LC = ("0.8", "1.6")
GRID_SEEDS = list(range(1, 7))
LC_SEEDS = list(range(1, 13))
MNM = {"graded": "단계", "u80": "일률 80"}


def sc(pen, m):
    return f"official+tago{pen}+relay" + ("-u80" if m == "u80" else "")


def load_grid(path):
    recs, ex, bad = read_jsonl(path)
    inv = {O: ("base", None)}
    for pen in PEN:
        for m in ("graded", "u80"):
            inv[sc(pen, m)] = (m, pen)
    t = {}
    for r in recs:
        ov = r.get("ov") or {}
        if r.get("scheme") not in inv or r.get("false") or r.get("seed") not in GRID_SEEDS or set(ov) != {"comply"}:
            continue
        cp = next((c for c in COMPLY if abs(float(ov["comply"]) - c) < 1e-6), None)
        if cp is None:
            continue
        m, pen = inv[r["scheme"]]
        t.setdefault((cp, pen, m), {})[r["seed"]] = r
    return t, ex, bad


def load_lc(path):
    recs, ex, bad = read_jsonl(path)
    inv = {O: "base", "official+tago12+relay": "graded", "official+tago12+relay-u80": "u80"}
    t = {}
    for r in recs:
        ov = r.get("ov") or {}
        if r.get("scheme") not in inv or r.get("false") or r.get("seed") not in LC_SEEDS or set(ov) != {"lc_assert"}:
            continue
        la = str(ov["lc_assert"])
        if la not in LC:
            continue
        t.setdefault((la, inv[r["scheme"]]), {})[r["seed"]] = r
    return t, ex, bad


def v(t, key, met, seeds):
    rows = t.get(key, {})
    return [None if s not in rows else rows[s].get(met) for s in seeds]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default=str(RES / "mac" / "p6_grid.jsonl"))
    ap.add_argument("--lc", default=str(RES / "mac" / "p6_lc.jsonl"))
    ap.add_argument("--out", default=str(RES / "report_p6_mac"))
    ap.add_argument("--grid-seeds", default="1-6", help="격자 씨앗 범위 a-b(기본 1-6; 씨앗 확장 뒤 1-12, 7-12)")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.grid_seeds.split("-"))
    GRID_SEEDS[:] = list(range(lo, hi + 1))
    tg, ex_g, bad_g = load_grid(a.grid)
    tl, ex_l, bad_l = load_lc(a.lc)
    exp_g, exp_l = len(COMPLY) * len(GRID_SEEDS) * (1 + 2 * len(PEN)), len(LC) * len(LC_SEEDS) * 3
    have_g, have_l = sum(len(x) for x in tg.values()), sum(len(x) for x in tl.values())
    miss_g, miss_l = exp_g - have_g, exp_l - have_l
    partial = miss_g + miss_l > 0

    bg = Boot(GRID_SEEDS, RNG_KEY)
    for cp in COMPLY:
        for met in METRICS:
            base = v(tg, (cp, None, "base"), met, GRID_SEEDS)
            bg.add(("raw", cp, "base", met), base)
            for pen in PEN:
                for m in ("graded", "u80"):
                    bg.add(("chg", cp, pen, m, met), chg(v(tg, (cp, pen, m), met, GRID_SEEDS), base))
                bg.add(("ug", cp, pen, met), chg(v(tg, (cp, pen, "u80"), met, GRID_SEEDS), v(tg, (cp, pen, "graded"), met, GRID_SEEDS)))
    bg.run()
    bl = Boot(LC_SEEDS, RNG_KEY)
    for la in LC:
        for met in METRICS:
            base = v(tl, (la, "base"), met, LC_SEEDS)
            for k in ("base", "graded", "u80"):
                bl.add(("raw", la, k, met), v(tl, (la, k), met, LC_SEEDS))
            for m in ("graded", "u80"):
                bl.add(("chg", la, m, met), chg(v(tl, (la, m), met, LC_SEEDS), base))
            bl.add(("ug", la, met), chg(v(tl, (la, "u80"), met, LC_SEEDS), v(tl, (la, "graded"), met, LC_SEEDS)))
    bl.run()

    st_g = {f"{cp}|{pen}|{m}": {"n_seeds": len(tg.get((cp, pen, m), {})), "missing": [s for s in GRID_SEEDS if s not in tg.get((cp, pen, m), {})]}
            for cp in COMPLY for pen, m in [(None, "base")] + [(p, mm) for p in PEN for mm in ("graded", "u80")]}
    st_l = {f"{la}|{k}": {"n_seeds": len(tl.get((la, k), {})), "missing": [s for s in LC_SEEDS if s not in tl.get((la, k), {})]}
            for la in LC for k in ("base", "graded", "u80")}
    out = {"note": "맥 결과, PC 와 섞지 않음. 탐색. 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 0 씨앗 제외. "
                   '95 % CI = 씨앗 복원 추출 10,000회, random.Random("p")(격자 씨앗 6, lc 씨앗 12 각각의 재표본 행렬), 백분위.',
           "inputs": {"grid": a.grid, "lc": a.lc, "grid_exists": ex_g, "lc_exists": ex_l},
           "status": {"grid": st_g, "lc": st_l, "bad_lines": {"grid": bad_g, "lc": bad_l},
                      "truncated": sum(bool(r.get("truncated")) for t in (tg, tl) for x in t.values() for r in x.values())},
           "partial": partial, "missing": {"grid": miss_g, "lc": miss_l},
           "grid": {"|".join(map(str, k)): jsonable(bg.get(k)) for k in bg.vecs},
           "lc": {"|".join(map(str, k)): jsonable(bl.get(k)) for k in bl.vecs}}
    stem = Path(a.out)
    stem.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    fstat = lambda p, ex, bad, have, exp: f"{Path(p).name} " + ("파일 없음" if not ex else f"{have}/{exp}개 실행, 빠짐 {exp - have}개, 깨진 줄 {bad}개")
    L = ["# 검토 뒤 보강 P6(a)·(b) 민감도 격자 (맥 결과, PC 와 섞지 않음; 탐색)", "",
         f"실행: `python -X utf8 analyze_p6_mac.py` (server/link/sim 에서; 입력 `results/mac/{Path(a.grid).name}`, `results/mac/{Path(a.lc).name}`)", "",
         f"**맥 결과, PC 와 섞지 않음. 자료 상태: {fstat(a.grid, ex_g, bad_g, have_g, exp_g)}; {fstat(a.lc, ex_l, bad_l, have_l, exp_l)}."
         + (f" 부분 자료 — 확정 결과 아님(빠진 실행 {miss_g + miss_l}개).**" if partial else " 모두 갖춰짐.**"), "",
         "변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 = 같은 준수율(또는 같은 lc 수준)·같은 씨앗의 기준선 official, 대조 0 씨앗 제외. "
         f"괄호는 부트스트랩 95 % CI(씨앗 복원 추출 {N_BOOT:,}회, random.Random(\"{RNG_KEY}\"), (a) 씨앗 6·(b) 씨앗 12 각각 같은 재표본 행렬, 백분위). "
         "씨앗 6개라 CI 가 넓다. 판정 규칙 없음(서술).", ""]

    # (a)
    L += ["## P6(a) 준수율 × 보급률 격자(씨앗 1~6)", ""]
    if not tg:
        L += ["자료 없음.", ""]
    else:
        for met in METRICS:
            L += [f"### 표 P6a-{MNAME[met]}. 기준선 대비 변화율 %({MNAME[met]})", "",
                  "| 준수율 | 기준선 평균 | " + " | ".join(f"{MNM[m]} {pen} %" for pen in PEN for m in ("graded", "u80")) + " |",
                  "|---|---|" + "---|" * (2 * len(PEN))]
            for cp in COMPLY:
                L.append(f"| {cp * 100:.0f} % | {fval(bg.get(('raw', cp, 'base', met)))} | "
                         + " | ".join(fpct(bg.get(("chg", cp, pen, m, met))) for pen in PEN for m in ("graded", "u80")) + " |")
            L.append("")
        L += ["### 표 P6a-단계 대 일률 80. 같은 칸에서 일률 80 의 단계 대비 변화율 %(음수 = 일률 80 이 적음)", "",
              "| 준수율 | 지표 | " + " | ".join(f"보급 {pen} %" for pen in PEN) + " |", "|---|---|" + "---|" * len(PEN)]
        for cp in COMPLY:
            for met in METRICS:
                L.append(f"| {cp * 100:.0f} % | {MNAME[met]} | " + " | ".join(f"{fpct(bg.get(('ug', cp, pen, met)))} [0 {has0(bg.get(('ug', cp, pen, met)))}]" for pen in PEN) + " |")
        L.append("")

    # (b)
    L += ["## P6(b) 차로 변경 공격성 lcAssertive(기본 1.2; 씨앗 1~12)", ""]
    if not tl:
        L += ["자료 없음.", ""]
    else:
        L += ["### 표 P6b-1. 지표 평균", "", "| lcAssertive | 방식 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|---|" + "---|" * len(METRICS)]
        for la in LC:
            for k, nm in (("base", "기준선"), ("graded", "단계"), ("u80", "일률 80")):
                L.append(f"| {la} | {nm} | " + " | ".join(fval(bl.get(("raw", la, k, m))) for m in METRICS) + " |")
        L += ["", "### 표 P6b-2. 기준선 대비 변화율 %와 단계 대 일률 80", "",
              "| lcAssertive | 비교 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|---|" + "---|" * len(METRICS)]
        for la in LC:
            for m in ("graded", "u80"):
                L.append(f"| {la} | {MNM[m]} 대 기준선 | " + " | ".join(fpct(bl.get(("chg", la, m, met))) for met in METRICS) + " |")
            L.append(f"| {la} | 일률 80 대 단계 | " + " | ".join(f"{fpct(bl.get(('ug', la, met)))} [0 {has0(bl.get(('ug', la, met)))}]" for met in METRICS) + " |")
        L.append("")
    stem.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ {stem.with_suffix('.json')}, {stem.with_suffix('.md')}" + (" (부분 자료)" if partial else ""))


if __name__ == "__main__":
    main()
