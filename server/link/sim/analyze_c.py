"""모형 강건 권고 설계 C(탐색, 미니맥스) — 사전 고정 docs/sim-preregistration.md '## 모형 강건 권고 설계 C'
  python -X utf8 analyze_c.py  → results/report_c.json, results/report_c.md
권고 6개 × 추종 모형 2개(Krauss v2, IDM b 2.0·T 0.4) × 지표 3개(fast 주, severe, conflicts).
같은 모형 안 기준선(official) 대비 씨앗별 변화율 평균((처리−대조)/대조×100, 대조 0 인 씨앗 제외).
부트스트랩: 씨앗 1~24 복원 추출 10,000회, random.Random("c"), 같은 재표본을 두 모형·모든 권고에 함께 적용.
최악 = 두 모형 평균 중 큰 값, CI 는 재표본마다 max 를 취한 분포의 2.5·97.5 백분위.
모두 PC 실행. 씨앗이 다 갖춰지지 않은 권고는 '자료 없음'(IDM 설계 파일은 생성 중일 수 있음). 잘린 실행은 수를 보고하고 포함.
"""
import json
import random
from pathlib import Path

RES = Path(__file__).parent / "results"
SEEDS = list(range(1, 25))
N_BOOT = 10000
METRICS = ("fast", "severe", "conflicts")
MNAME = {"fast": "고속 접근(주)", "severe": "심각", "conflicts": "전체 상충"}
BASE = "official"
P = "official+tago12+relay"
RECS = [  # (키, 스킴, 이름)
    ("graded", P, "단계 90·70·50"),
    ("u80", P + "-u80", "일률 80"),
    ("near", P + "-near", "꼬리 1 km 안만 70"),
    ("u80near", P + "-u80near", "일률 80 + 꼬리 1 km 안 70"),
    ("u80nl", P + "-u80nl", "일률 80, 차로 권고 없음"),
    ("none", P + "-none", "권고 없음(경고만)"),
]
MODELS = {  # 모형: [(파일, 쓰는 스킴)]
    "krauss": [("v2_main.jsonl", {BASE, P}), ("fu_pc.jsonl", {P + "-u80", P + "-near", P + "-none"}),
               ("rb_design.jsonl", {P + "-u80near", P + "-u80nl"})],
    "idm": [("m1_idm_b2.jsonl", {BASE, P, P + "-u80"}),
            ("m1_idm_b2_design.jsonl", {P + "-near", P + "-none", P + "-u80near", P + "-u80nl"})],
}
MLABEL = {"krauss": "Krauss", "idm": "IDM"}


def load(name, keep):
    p = RES / name
    if not p.exists():
        return []
    rows = []
    for x in p.read_text(encoding="utf-8").splitlines():
        x = x.strip()
        if not x:
            continue
        try:
            r = json.loads(x)
        except json.JSONDecodeError:  # 생성 중인 파일의 마지막 줄이 덜 써졌을 수 있다
            continue
        if r.get("scheme") in keep and r.get("seed") in SEEDS:
            rows.append(r)
    return rows


def table(model):
    t = {}  # scheme -> seed -> row (같은 씨앗·스킴이 두 번 있으면 마지막 것)
    for f, keep in MODELS[model]:
        for r in load(f, keep):
            t.setdefault(r["scheme"], {})[r["seed"]] = r
    return t


def pct(lo_hi_list, q):
    s = sorted(lo_hi_list)
    k = (len(s) - 1) * q
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def mean_over(idx, ch):
    v = [ch[i] for i in idx if ch[i] is not None]
    return sum(v) / len(v) if v else None


def main():
    tabs = {m: table(m) for m in MODELS}
    status = {}
    changes = {}  # (model, rec, metric) -> list per seed index (None = 대조 0 으로 제외)
    for m, t in tabs.items():
        base = t.get(BASE, {})
        st = {"baseline": {"n_seeds": len(base), "missing": [s for s in SEEDS if s not in base],
                           "truncated": sum(bool(r.get("truncated")) for r in base.values())}}
        for key, sc, _ in RECS:
            rows = t.get(sc, {})
            complete = len(base) == len(SEEDS) and all(s in rows for s in SEEDS)
            st[key] = {"n_seeds": len(rows), "missing": [s for s in SEEDS if s not in rows],
                       "truncated": sum(bool(r.get("truncated")) for r in rows.values()), "used": complete}
            if not complete:
                continue
            for met in METRICS:
                ch = []
                for s in SEEDS:
                    c, x = base[s][met], rows[s][met]
                    ch.append(None if c == 0 else (x - c) / c * 100)
                changes[(m, key, met)] = ch
        status[m] = st

    # 점 추정
    full = list(range(len(SEEDS)))
    est = {}
    for (m, key, met), ch in changes.items():
        est[(m, key, met)] = {"mean": mean_over(full, ch), "n_used": sum(v is not None for v in ch)}

    # 부트스트랩: 같은 씨앗 재표본을 모든 칸에 적용
    rng = random.Random("c")
    boots = {k: [] for k in changes}
    worst_boot = {(key, met): [] for key, _, _ in RECS for met in METRICS
                  if all((m, key, met) in changes for m in MODELS)}
    for _ in range(N_BOOT):
        idx = [rng.randrange(len(SEEDS)) for _ in SEEDS]
        cur = {}
        for k, ch in changes.items():
            v = mean_over(idx, ch)
            cur[k] = v
            if v is not None:
                boots[k].append(v)
        for (key, met), lst in worst_boot.items():
            vs = [cur[(m, key, met)] for m in MODELS]
            if all(v is not None for v in vs):
                lst.append(max(vs))
    for k, b in boots.items():
        est[k]["ci"] = [pct(b, 0.025), pct(b, 0.975)] if b else None

    out = {"note": "탐색(가설 없음). 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 음수 = 상충 감소. 부분 자료일 수 있음.",
           "n_boot": N_BOOT, "rng": 'random.Random("c")', "status": status, "recs": {}}
    for key, sc, name in RECS:
        r = {"scheme": sc, "name": name}
        for met in METRICS:
            cell = {}
            for m in MODELS:
                e = est.get((m, key, met))
                cell[m] = None if e is None else {"mean": e["mean"], "ci": e["ci"], "n_used": e["n_used"]}
            if (key, met) in worst_boot and all(cell[m]["mean"] is not None for m in MODELS):
                w = max(MODELS, key=lambda m: cell[m]["mean"])
                b = worst_boot[(key, met)]
                cell["worst"] = {"mean": cell[w]["mean"], "model": w,
                                 "ci": [pct(b, 0.025), pct(b, 0.975)] if b else None}
            else:
                cell["worst"] = None
            r[met] = cell
        out["recs"][key] = r

    # 판정: 주 지표 최악이 가장 작은 권고, CI 겹침은 '구별 안 됨'
    avail = [k for k, _, _ in RECS if out["recs"][k]["fast"]["worst"] is not None]
    verdict = {"available": avail, "unavailable": [k for k, _, _ in RECS if k not in avail]}
    if avail:
        best = min(avail, key=lambda k: out["recs"][k]["fast"]["worst"]["mean"])
        bl, bh = out["recs"][best]["fast"]["worst"]["ci"]
        tied = [k for k in avail if k != best
                and out["recs"][k]["fast"]["worst"]["ci"][0] <= bh and bl <= out["recs"][k]["fast"]["worst"]["ci"][1]]
        verdict.update({"candidate": best, "indistinguishable": tied})
    out["verdict"] = verdict

    # 지배: 두 모형 × 세 지표 모든 칸에서 값이 더 크면 지배됨
    dom = []
    for a in avail:
        for b in avail:
            if a == b:
                continue
            if all(out["recs"][a][met][m]["mean"] > out["recs"][b][met][m]["mean"] for met in METRICS for m in MODELS):
                dom.append({"dominated": a, "by": b})
    out["dominance"] = dom
    out["dominated"] = sorted({d["dominated"] for d in dom}, key=[k for k, _, _ in RECS].index)

    (RES / "report_c.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 보고서
    NM = {k: n for k, _, n in RECS}
    miss_idm = sum(len(v["missing"]) for k, v in status["idm"].items())
    miss_kr = sum(len(v["missing"]) for k, v in status["krauss"].items())
    partial = miss_idm + miss_kr > 0
    f1 = lambda v: f"{v:+.1f}"
    fc = lambda c: "자료 없음" if c is None else f"{f1(c['mean'])} ({c['ci'][0]:.1f} ~ {c['ci'][1]:.1f})"
    L = [f"# 모형 강건 권고 설계 C (탐색, 미니맥스)", "",
         f"**자료 상태: 빠진 씨앗 Krauss {miss_kr}개, IDM {miss_idm}개(실행 단위, 기준선 포함)."
         + (" 부분 자료 — 확정 결과 아님.**" if partial else " 모두 갖춰짐.**"), "",
         "같은 모형 안 기준선 대비 씨앗별 변화율 평균(%, 음수 = 상충 감소), 괄호는 부트스트랩 95 % CI "
         f"(씨앗 복원 추출 {N_BOOT:,}회, 두 모형 같은 재표본). 최악 = 두 모형 중 큰 값. 대조 0 인 씨앗은 제외. 모두 PC 실행.", ""]
    for i, met in enumerate(METRICS, 1):
        L += [f"## 표 {i}. {MNAME[met]}", "", "| 권고 | Krauss | IDM | 최악 (CI) |", "|---|---|---|---|"]
        for key, _, name in RECS:
            c = out["recs"][key][met]
            km = "자료 없음" if c["krauss"] is None else f1(c["krauss"]["mean"])
            im = "자료 없음" if c["idm"] is None else f1(c["idm"]["mean"])
            w = c["worst"]
            ws = "자료 없음" if w is None else f"{f1(w['mean'])} ({w['ci'][0]:.1f} ~ {w['ci'][1]:.1f}), {MLABEL[w['model']]}"
            L.append(f"| {name} | {km} | {im} | {ws} |")
        L.append("")
    L += ["## 판정", ""]
    if "candidate" in verdict:
        tied = verdict["indistinguishable"]
        line = f"모형 강건 후보: **{NM[verdict['candidate']]}**(고속 접근 최악 {fc(out['recs'][verdict['candidate']]['fast']['worst'])})"
        line += f"; 최악 CI 가 겹쳐 구별 안 됨: {', '.join(NM[k] for k in tied)}." if tied else "; 최악 CI 가 겹치는 다른 권고 없음."
        if verdict["unavailable"]:
            line += f" (자료 없어 판정에서 빠짐: {', '.join(NM[k] for k in verdict['unavailable'])})"
        if partial:
            line += " — 부분 자료 기준."
        L.append(line)
    else:
        L.append("두 모형 자료가 모두 갖춰진 권고가 없어 판정 못 함.")
    L += ["", "## 지배 관계", "", "두 모형 × 세 지표 여섯 칸 모두에서 값이 더 큰(나쁜) 경우만 지배로 본다(점 추정).", ""]
    if dom:
        for d in dom:
            L.append(f"- {NM[d['dominated']]} ← {NM[d['by']]} 에 지배됨")
        L += ["", f"지배된 권고: {', '.join(NM[k] for k in out['dominated'])}"]
    else:
        L.append("- 지배된 권고 없음" + ("(자료가 갖춰진 권고 사이에서)" if verdict["unavailable"] else ""))
    L += ["", "## 자료 상태", "", "| 모형 | 조건 | 씨앗 수 | 빠진 씨앗 | 잘린 실행 | 분석에 씀 |", "|---|---|---|---|---|---|"]
    for m in MODELS:
        for key in ["baseline"] + [k for k, _, _ in RECS]:
            s = status[m][key]
            nm = "기준선" if key == "baseline" else NM[key]
            miss = "—" if not s["missing"] else (f"{len(s['missing'])}개" if len(s["missing"]) > 6 else ", ".join(map(str, s["missing"])))
            used = "—" if key == "baseline" else ("예" if s["used"] else "아니오")
            L.append(f"| {MLABEL[m]} | {nm} | {s['n_seeds']} | {miss} | {s['truncated']} | {used} |")
    L += ["", "잘린 실행(정체가 도로 끝까지 참)은 분석에 포함했다."]
    (RES / "report_c.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
