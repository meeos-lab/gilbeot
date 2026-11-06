"""후속 실험(권고 방식) 분석 — 사전 고정 docs/sim-preregistration.md '후속' → results/report_fu.json, report_fu.md
  python -X utf8 analyze_fu.py
PC: 기준선·단계는 v2_main.jsonl, 세 변형은 fu_pc.jsonl(같은 기계·같은 설정). 맥 재현: mac/fu_mac.jsonl 안에서만 비교.
"""
import json
import statistics

import analyze as A

RES = A.RES
VARIANTS = (("official+tago12+relay", "단계 90·70·50 (v2)"), ("official+tago12+relay-u80", "일률 80"),
            ("official+tago12+relay-near", "꼬리 근처만 70"), ("official+tago12+relay-none", "권고 없음(주의만)"))


def summarize(tab):
    out = {}
    for sc, name in VARIANTS:
        rs = [d[sc] for d in tab.values() if sc in d]
        if not rs:
            continue
        out[sc] = {"name": name, "n": len(rs), "fast": statistics.mean(r["fast"] for r in rs),
                   "vs_official": {m: A.reduction(tab, sc, "official", m) for m in ("fast", "conflicts", "severe")},
                   "vs_graded": {m: A.reduction(tab, sc, "official+tago12+relay", m) for m in ("fast", "conflicts", "severe")} if sc != "official+tago12+relay" else None,
                   "kinds": {k: statistics.mean(r["kinds"][k] for r in rs) for k in ("merge", "queue", "approach", "other")}}
    return out


def main():
    base = [r for r in A.load("v2_main.jsonl") if r["scheme"] in ("official", "official+tago12+relay")]
    pc = A.by_seed(base + A.load("fu_pc.jsonl"))
    out = {"pc": {"n_seeds": len(pc), "variants": summarize(pc)}}
    ps = [A.wil(pc, "official+tago12+relay", sc, "fast") for sc in ("official+tago12+relay-u80", "official+tago12+relay-near", "official+tago12+relay-none")]
    adj = A.holm(ps)
    out["pc"]["hypotheses"] = {h: {"p": p, "p_holm": q} for h, p, q in zip(("H5 일률 80 < 단계", "H6 꼬리 근처만 < 단계", "H7 권고 없음 < 단계"), ps, adj)}
    mac = A.by_seed(A.load("mac/fu_mac.jsonl"))
    if mac:
        out["mac"] = {"n_seeds": len(mac), "variants": summarize(mac)}
    (RES / "report_fu.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# 후속 실험: 넘김 메시지의 권고 방식", ""]
    for key in ("pc", "mac"):
        if key not in out:
            continue
        o = out[key]
        L += [f"## {key.upper()} (씨앗 {o['n_seeds']}개)", "", "| 권고 방식 | 고속 접근(기준선 대비) | 전체 | 심각 | 고속 접근(단계 대비) |", "|---|---|---|---|---|"]
        for sc, v in o["variants"].items():
            f = lambda r: f"{r['mean']*100:+.1f} % ({r['ci'][0]*100:.1f} ~ {r['ci'][1]*100:.1f})" if r else ""
            L.append(f"| {v['name']} | {f(v['vs_official']['fast'])} | {f(v['vs_official']['conflicts'])} | {f(v['vs_official']['severe'])} | {f(v['vs_graded']['fast']) if v['vs_graded'] else '기준'} |")
        if "hypotheses" in o:
            L += ["", "가설(홀름 보정): " + ", ".join(f"{k} p {h['p']:.2g} 보정 {h['p_holm']:.2g}" for k, h in o["hypotheses"].items())]
        L.append("")
    (RES / "report_fu.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
