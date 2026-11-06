#!/usr/bin/env python
"""P9 확정 규칙 정정 재실행 분석(사전 등록 'P9', 맥 결과, PC 와 섞지 않음).

입력 results/mac/p9_confirm.jsonl(씨앗 1~24 × 기준선·단계·일률 80 × {정정 전(ov 없음), 정정 후(ov confirm_fix)}).
통계량은 등록 정의대로: (1) 씨앗별 inc_at 전후와 달라진 씨앗, (2) 정정 후 기준선 대비·일률 80 대 단계 변화율(씨앗별 평균, CI 10,000회 rng "p")
+ 윌콕슨(일률 80 대 단계, 고속 접근), (3) 정정 전후 같은 방식 변화율(짝)·4개 씨앗 전후 값, (4) 정정 전(맥) 대 PC v2_main 일치.
부분 자료면 '부분 자료 — 확정 결과 아님'을 머리에 적는다.
"""
import json
from pathlib import Path

from scipy.stats import wilcoxon

from analyze_p import METRICS, MNAME, RES, SEEDS, Boot, chg, dif, fpct, fval, has0, jsonable, read_jsonl, table

SCH = [("official", 0, "기준선"), ("official+tago12+relay", 1, "단계 90·70·50"), ("official+tago12+relay-u80", 2, "일률 80")]   # (방식, 키, 이름) — analyze_p.table 의 순서
KEYS = [k for _, k, _ in SCH]
NAME = {k: n for _, k, n in SCH}
EXPECT_CHANGED = (13, 17, 19, 21)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(RES / "mac" / "p9_confirm.jsonl"))
    ap.add_argument("--out", default="report_p9", help="결과 파일 이름(확장자 없이)")
    ap.add_argument("--machine", default="맥")
    args = ap.parse_args()
    src = Path(args.src)
    recs, exists, bad = read_jsonl(src)
    before = table(recs, SCH, ov_ok=lambda ov: not ov)
    after = table(recs, SCH, ov_ok=lambda ov: bool(ov.get("confirm_fix")))
    n_b = sum(len(v) for v in before.values())
    n_a = sum(len(v) for v in after.values())
    partial = n_b < 72 or n_a < 72
    missing = {"before": {NAME[k]: [s for s in SEEDS if s not in before.get(k, {})] for k in KEYS},
               "after": {NAME[k]: [s for s in SEEDS if s not in after.get(k, {})] for k in KEYS}}
    L = [f"# P9 확정 규칙 정정 재실행 분석({args.machine}, 같은 기계 안에서만 비교)", "",
         "실행: `python -X utf8 analyze_p9.py` (server/link/sim 에서; 입력 `results/mac/p9_confirm.jsonl`)", "",
         f"**자료 상태: 정정 전 {n_b}/72, 정정 후 {n_a}/72, 깨진 줄 {bad}개." + (" 부분 자료 — 확정 결과 아님.**" if partial else " 모두 갖춰짐.**"), "",
         "변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 0 씨앗 제외. 괄호는 부트스트랩 95 % CI(씨앗 1~24 복원 추출 10,000회, random.Random(\"p\"), 같은 재표본 행렬, 백분위). 판정 규칙(등록): 정정 후 일률 80 대 단계의 고속 접근 CI 가 0 을 포함하지 않고 윌콕슨 p < 0.05 이면 'H5 유지'.", ""]
    out = {"partial": partial, "missing": missing, "bad_lines": bad, "inputs": str(src), "exists": exists}

    # (1) inc_at 전후
    L += ["## (1) 사고 확정 시각 inc_at 과 첫 길벗 경고 시각 warn_first(사고 뒤 초), 정정 전 → 후", "",
          "정정 전 기록의 inc_at 은 처리 종료 시점에 1·31 로 덮어써진 값이라 전후가 같다. 실제 변화는 첫 경고 시각(warn_first)과 지표로 본다. '달라짐' = 세 지표·통행 시간 중 하나라도 다름.", "",
          "| 씨앗 | 단계 inc_at 전 → 후 | 단계 warn_first 전 → 후 | 일률 80 warn_first 전 → 후 | 달라짐 |", "|---|---|---|---|---|"]
    changed = []
    inc = {}
    for s in SEEDS:
        ch = False
        for k in KEYS:
            b = before.get(k, {}).get(s); a = after.get(k, {}).get(s)
            inc[f"{k}|{s}"] = [None if b is None else b.get("inc_at"), None if a is None else a.get("inc_at"),
                               None if b is None else b.get("warn_first"), None if a is None else a.get("warn_first")]
            if b is not None and a is not None and any(b.get(m) != a.get(m) for m in METRICS + ("travel",)):
                ch = True
        if ch:
            changed.append(s)
        g, u = inc[f"1|{s}"], inc[f"2|{s}"]
        f = lambda v: "—" if v is None else v
        L.append(f"| {s} | {f(g[0])} → {f(g[1])} | {f(g[2])} → {f(g[3])} | {f(u[2])} → {f(u[3])} | {'예' if ch else ''} |")
    unexpected = [s for s in changed if s not in EXPECT_CHANGED]
    L += ["", f"달라진 씨앗: {changed} (등록 예상 {list(EXPECT_CHANGED)}; 예상 밖 {unexpected if unexpected else '없음'}" + (" → 구현 오류로 적는다" if unexpected else "") + ")", ""]
    out["inc_at"] = inc; out["changed_seeds"] = changed; out["unexpected_changed"] = unexpected

    # 기준선은 길벗이 없어 inc_at 이 None 이어야 함을 확인
    base_inc = [r.get("inc_at") for r in after.get(0, {}).values()]
    out["baseline_inc_at_all_none"] = all(v is None for v in base_inc)

    # (2) 정정 후 변화율 + (3) 전후
    B = Boot()
    for m in METRICS:
        va = {k: [None if r is None else r[m] for r in (after.get(k, {}).get(s) for s in SEEDS)] for k in KEYS}
        vb = {k: [None if r is None else r[m] for r in (before.get(k, {}).get(s) for s in SEEDS)] for k in KEYS}
        for k in (1, 2):
            B.add(f"after|{k}|{m}", chg(va[k], va[0]))
            B.add(f"before|{k}|{m}", chg(vb[k], vb[0]))
        B.add(f"after|ug|{m}", chg(va[2], va[1]))
        B.add(f"before|ug|{m}", chg(vb[2], vb[1]))
        for k in KEYS:
            B.add(f"ba|{k}|{m}", chg(va[k], vb[k]))        # 정정 후 대 정정 전(같은 방식)
            B.add(f"raw_after|{k}|{m}", va[k]); B.add(f"raw_before|{k}|{m}", vb[k])
    B.run()
    C = {k: B.get(k) for k in B.vecs}
    out["cells"] = {k: jsonable(v) for k, v in C.items()}

    def row(label, keys):
        return f"| {label} | " + " | ".join(fpct(C[k]) if C.get(k) else "—" for k in keys) + " |"
    L += ["## (2) 정정 후: 기준선 대비 변화율 %(씨앗별 평균, 95 % CI)", "", "| 비교 | 고속 접근 | 심각 | 전체 상충 |", "|---|---|---|---|",
          row("단계 대 기준선", [f"after|1|{m}" for m in METRICS]), row("일률 80 대 기준선", [f"after|2|{m}" for m in METRICS]),
          row("일률 80 대 단계", [f"after|ug|{m}" for m in METRICS]), ""]
    # 윌콕슨
    xs = [(after[2][s]["fast"], after[1][s]["fast"]) for s in SEEDS if s in after.get(2, {}) and s in after.get(1, {})]
    p = float(wilcoxon([x for x, _ in xs], [y for _, y in xs]).pvalue) if len(xs) >= 5 and any(x - y for x, y in xs) else None
    ug = C.get("after|ug|fast")
    verdict = None
    if ug and p is not None and not partial:
        verdict = "H5 유지(확정 규칙 정정 뒤에도 일률 80 < 단계)" if (p < 0.05 and has0(ug) == "벗어남") else "유지 안 됨"
    L += [f"윌콕슨(일률 80 대 단계, 고속 접근, 양측, n = {len(xs)}): p = {p if p is None else f'{p:.2e}'}", f"판정: {verdict or '부분 자료 — 판정 보류'}", ""]
    out["wilcoxon_p"] = p; out["n_pairs"] = len(xs); out["verdict"] = verdict
    L += ["### 정정 전(같은 기계, 참고)", "", "| 비교 | 고속 접근 | 심각 | 전체 상충 |", "|---|---|---|---|",
          row("단계 대 기준선", [f"before|1|{m}" for m in METRICS]), row("일률 80 대 기준선", [f"before|2|{m}" for m in METRICS]),
          row("일률 80 대 단계", [f"before|ug|{m}" for m in METRICS]), ""]
    L += ["## (3) 정정 후 대 정정 전(같은 방식, 씨앗별 변화율 %)", "", "| 방식 | 고속 접근 | 심각 | 전체 상충 |", "|---|---|---|---|"]
    for k in KEYS:
        L.append(row(NAME[k], [f"ba|{k}|{m}" for m in METRICS]))
    L += ["", "### 달라진 씨앗의 전후 값(고속 접근 / 심각 / 전체; 첫 길벗 경고 시각 s)", "", "| 씨앗 | 방식 | 정정 전 | 정정 후 |", "|---|---|---|---|"]
    for s in changed:
        for k in KEYS:
            b = before.get(k, {}).get(s); a = after.get(k, {}).get(s)
            fb = "—" if b is None else f"{b['fast']} / {b['severe']} / {b['conflicts']}; 첫 경고 {b.get('warn_first')}"
            fa = "—" if a is None else f"{a['fast']} / {a['severe']} / {a['conflicts']}; 첫 경고 {a.get('warn_first')}"
            L.append(f"| {s} | {NAME[k]} | {fb} | {fa} |")
    L += ["", "### 방식별 지표 평균(참고)", "", "| 방식 | 고속 접근 전 → 후 | 심각 전 → 후 | 전체 전 → 후 |", "|---|---|---|---|"]
    for k in KEYS:
        L.append(f"| {NAME[k]} | " + " | ".join(f"{fval(C[f'raw_before|{k}|{m}'])} → {fval(C[f'raw_after|{k}|{m}'])}" if C.get(f'raw_before|{k}|{m}') and C.get(f'raw_after|{k}|{m}') else "—" for m in METRICS) + " |")

    # (4) 정정 전(맥) 대 PC v2_main
    pc, pc_exists, _ = read_jsonl(RES / "v2_main.jsonl")
    pct = table(pc, SCH)
    same = diff = 0; diffs = []
    for k in KEYS:
        for s in SEEDS:
            b = before.get(k, {}).get(s); r = pct.get(k, {}).get(s)
            if b is None or r is None:
                continue
            if all(b[m] == r[m] for m in METRICS):
                same += 1
            else:
                diff += 1; diffs.append((NAME[k], s, [(m, b[m], r[m]) for m in METRICS if b[m] != r[m]]))
    L += ["", f"## (4) 정정 전({args.machine}) 대 PC v2_main 같은 키(기계 차이 기록용, 판정에 안 씀)", "", f"같음 {same}, 다름 {diff}" + (f"; 다른 예: {diffs[:5]}" if diffs else ""), ""]
    out["mac_vs_pc"] = {"same": same, "diff": diff, "examples": diffs[:10]}

    (RES / f"{args.out}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (RES / f"{args.out}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", RES / f"{args.out}.md", "(부분 자료)" if partial else "", "판정:", verdict)


if __name__ == "__main__":
    main()
