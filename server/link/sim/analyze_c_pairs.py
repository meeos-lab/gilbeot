"""설계 C 권고 쌍의 최악값 차이(탐색) — analyze_c.py 의 정의를 그대로 재사용.
  python -X utf8 analyze_c_pairs.py  → results/report_c_pairs.json, results/report_c_pairs.md
Δ = worst(A) − worst(B), worst = 두 모형(Krauss·IDM)의 '기준선 대비 씨앗별 변화율 평균' 중 큰 값.
부트스트랩: 씨앗 1~24 복원 추출 10,000회, random.Random("c")(analyze_c.py 와 같은 재표본 열),
재표본마다 각 모형·권고 평균 → 모형 최대 → 차이. CI = 2.5·97.5 백분위(analyze_c.pct).
비교 가족 = 권고 쌍 15개, 다중 비교 보정 없음(탐색).
"""
import json
import random
from itertools import combinations

from analyze_c import (BASE, METRICS, MLABEL, MNAME, MODELS, N_BOOT, RECS, RES, SEEDS,
                       mean_over, pct, table)


def build_changes():
    """analyze_c.main() 의 씨앗별 변화율 계산과 같은 정의(대조 0 씨앗은 None)."""
    tabs = {m: table(m) for m in MODELS}
    changes = {}
    for m, t in tabs.items():
        base = t.get(BASE, {})
        for key, sc, _ in RECS:
            rows = t.get(sc, {})
            if not (len(base) == len(SEEDS) and all(s in rows for s in SEEDS)):
                continue
            for met in METRICS:
                ch = []
                for s in SEEDS:
                    c, x = base[s][met], rows[s][met]
                    ch.append(None if c == 0 else (x - c) / c * 100)
                changes[(m, key, met)] = ch
    return changes


def main():
    changes = build_changes()
    keys = [k for k, _, _ in RECS]
    avail = [k for k in keys if all((m, k, met) in changes for m in MODELS for met in METRICS)]
    NM = {k: n for k, _, n in RECS}
    full = list(range(len(SEEDS)))

    def worst(idx, key, met):
        vs = [mean_over(idx, changes[(m, key, met)]) for m in MODELS]
        return None if any(v is None for v in vs) else max(vs)

    point = {(k, met): worst(full, k, met) for k in avail for met in METRICS}
    pairs = list(combinations(avail, 2))  # RECS 순서

    # 부트스트랩 — analyze_c.py 와 같은 rng·같은 추출 순서
    rng = random.Random("c")
    wboot = {(k, met): [] for k in avail for met in METRICS}  # 검산용(analyze_c 의 최악 CI 재현)
    dboot = {(a, b, met): [] for a, b in pairs for met in METRICS}
    for _ in range(N_BOOT):
        idx = [rng.randrange(len(SEEDS)) for _ in SEEDS]
        cur = {(k, met): worst(idx, k, met) for k in avail for met in METRICS}
        for kk, v in cur.items():
            if v is not None:
                wboot[kk].append(v)
        for a, b in pairs:
            for met in METRICS:
                va, vb = cur[(a, met)], cur[(b, met)]
                if va is not None and vb is not None:
                    dboot[(a, b, met)].append(va - vb)

    out = {"note": "탐색. Δ = worst(A) − worst(B) (%p, 음수 = A 의 최악이 더 작음 = A 가 낫다). "
                   "부트스트랩 백분위 95 % CI, 재표본마다 모형 최대를 다시 계산. 비교 가족 = 15쌍, 보정 없음.",
           "n_boot": N_BOOT, "rng": 'random.Random("c") (analyze_c.py 와 같은 재표본 열)',
           "family": f"{len(pairs)} pairs, no multiplicity adjustment",
           "available": avail, "unavailable": [k for k in keys if k not in avail],
           "worst": {k: {met: {"mean": point[(k, met)],
                               "ci": [pct(wboot[(k, met)], 0.025), pct(wboot[(k, met)], 0.975)]}
                         for met in METRICS} for k in avail},
           "pairs": {met: [] for met in METRICS}, "best": {}}
    for met in METRICS:
        for a, b in pairs:
            d = dboot[(a, b, met)]
            lo, hi = pct(d, 0.025), pct(d, 0.975)
            out["pairs"][met].append({"a": a, "b": b, "delta": point[(a, met)] - point[(b, met)],
                                      "ci": [lo, hi], "n_boot_used": len(d),
                                      "excludes_0": lo > 0 or hi < 0})
        out["best"][met] = min(avail, key=lambda k: point[(k, met)])

    def get(met, a, b):
        """a−b 로 방향을 맞춘 쌍 결과."""
        for p in out["pairs"][met]:
            if p["a"] == a and p["b"] == b:
                return p["delta"], p["ci"]
            if p["a"] == b and p["b"] == a:
                return -p["delta"], [-p["ci"][1], -p["ci"][0]]
        return None

    (RES / "report_c_pairs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    f1 = lambda v: f"{v:+.1f}"
    fci = lambda c: f"{c[0]:+.1f} ~ {c[1]:+.1f}"
    has0 = lambda c: "포함" if c[0] <= 0 <= c[1] else "벗어남"
    L = ["# 설계 C 권고 쌍의 최악값 차이 (탐색)", "",
         "Δ = worst(A) − worst(B), %p. worst = Krauss·IDM 두 모형의 '기준선 대비 씨앗별 변화율 평균' 중 큰(나쁜) 값"
         "(정의는 report_c.md 와 같음). 음수 = A 의 최악이 더 작다(A 가 낫다).",
         f"95 % CI = 같은 씨앗 재표본 부트스트랩 백분위(씨앗 1~24 복원 추출 {N_BOOT:,}회, random.Random(\"c\"), "
         "재표본마다 각 모형·권고 평균 → 모형 최대 → 차이). 짝지은 설계이므로 한계 CI 겹침 대신 이 차이 CI 로 판단한다.",
         f"**비교 가족 = {len(pairs)}쌍, 다중 비교 보정 없음(탐색).**", ""]
    if out["unavailable"]:
        L += [f"자료 없어 빠진 권고: {', '.join(NM[k] for k in out['unavailable'])}", ""]

    L += ["## 최악값 (검산: report_c.md 와 같아야 함)", "", "| 권고 | " + " | ".join(MNAME[m] for m in METRICS) + " |",
          "|---|" + "---|" * len(METRICS)]
    for k in avail:
        L.append(f"| {NM[k]} | " + " | ".join(f"{f1(out['worst'][k][m]['mean'])} ({out['worst'][k][m]['ci'][0]:.1f} ~ "
                                               f"{out['worst'][k][m]['ci'][1]:.1f})" for m in METRICS) + " |")
    L.append("")

    L += [f"## 표 1. {MNAME['fast']} — 15쌍 전부", "", "| A | B | Δ = A − B | 95 % CI | 0 |", "|---|---|---|---|---|"]
    for p in out["pairs"]["fast"]:
        L.append(f"| {NM[p['a']]} | {NM[p['b']]} | {f1(p['delta'])} | {fci(p['ci'])} | {has0(p['ci'])} |")
    L.append("")
    for i, met in enumerate(("severe", "conflicts"), 2):
        best = out["best"][met]
        L += [f"## 표 {i}. {MNAME[met]} — 가장 좋은 권고({NM[best]}) 대 나머지", "",
              "| A | B | Δ = A − B | 95 % CI | 0 |", "|---|---|---|---|---|"]
        for k in avail:
            if k == best:
                continue
            d, c = get(met, best, k)
            L.append(f"| {NM[best]} | {NM[k]} | {f1(d)} | {fci(c)} | {has0(c)} |")
        L.append("")

    # 요약 문단(주 지표)
    close = [k for k in ("near", "u80", "u80near", "u80nl", "none") if k in avail]
    cp = [(a, b) for a, b in combinations(close, 2)]
    inc = [(a, b) for a, b in cp if has0(get("fast", a, b)[1]) == "포함"]
    exc = [(a, b) for a, b in cp if (a, b) not in inc]
    s = [f"주 지표(고속 접근)에서 근접 후보 {len(close)}개({' / '.join(NM[k] for k in close)}) 사이 {len(cp)}쌍 중 "
         f"차이 CI 가 0 을 포함하는 쌍은 {len(inc)}개"]
    if exc:
        s[-1] += ", 0 을 벗어나는 쌍은 " + "; ".join(
            f"{NM[a]} − {NM[b]} {f1(get('fast', a, b)[0])} ({fci(get('fast', a, b)[1])})" for a, b in exc)
    s[-1] += "."
    if "near" in close:
        s.append("꼬리 1 km 안만 70 기준: " + "; ".join(
            f"− {NM[k]} {f1(get('fast', 'near', k)[0])} ({fci(get('fast', 'near', k)[1])})" for k in close if k != "near") + ".")
    if "graded" in avail:
        gs = [(k, get("fast", "graded", k)) for k in avail if k != "graded"]
        s.append(f"단계 90·70·50 − 나머지: " + "; ".join(
            f"{NM[k]} 대비 {f1(d)} ({fci(c)}, 0 {has0(c)})" for k, (d, c) in gs) + ".")
    s.append(f"비교 가족 = {len(pairs)}쌍, 보정 없음 — 탐색 결과다.")
    L += ["## 요약", "", " ".join(s), ""]
    (RES / "report_c_pairs.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
