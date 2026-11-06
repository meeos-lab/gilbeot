"""E7 정보의 가치(EVPI) — 등록: docs/sim-preregistration.md '## 관점 확장 E1~E8' 의 E7 (분석만, 서술).
  python -X utf8 analyze_e7_evpi.py  → results/report_e7_evpi.json, results/report_e7_evpi.md

loss(모형, 권고, 지표) = 같은 모형 기준선 대비 씨앗별 변화율 평균(%, 작을수록 좋음) — analyze_c.py 정의 그대로
(씨앗별 변화율은 analyze_c_pairs.build_changes() 를 재사용, 점추정은 results/report_c.json 과 일치하는지 검산).
사전확률 p(Krauss) = p(IDM) = 0.5.
EVPI = E_model[min_d loss(m, d)] − min_d E_model[loss(m, d)]   (단위 %p, 항상 ≥ 0).
부트스트랩: 씨앗 1~24 복원 추출 10,000회, random.Random("c") — analyze_c_pairs.py 와 같은 rng·같은 추출 순서,
같은 재표본을 두 모형·여섯 권고에 함께 적용, 재표본마다 EVPI 를 다시 계산. CI = 2.5·97.5 백분위(analyze_c.pct).
"""
import json
import random

from analyze_c import METRICS, MLABEL, MNAME, MODELS, N_BOOT, RECS, RES, SEEDS, mean_over, pct
from analyze_c_pairs import build_changes

PRIOR = {"krauss": 0.5, "idm": 0.5}


def evpi_of(L, avail):
    """L[(m, k)] = loss. 반환: evpi, 모형별 최선, 사전 기대 최선, 각 항."""
    best_m = {m: min(avail, key=lambda k: L[(m, k)]) for m in MODELS}
    e_min = sum(PRIOR[m] * L[(m, best_m[m])] for m in MODELS)
    exp_loss = {k: sum(PRIOR[m] * L[(m, k)] for m in MODELS) for k in avail}
    best_prior = min(avail, key=lambda k: exp_loss[k])
    return e_min, exp_loss, best_m, best_prior, exp_loss[best_prior] - e_min


def main():
    changes = build_changes()
    keys = [k for k, _, _ in RECS]
    NM = {k: n for k, _, n in RECS}
    avail = [k for k in keys if all((m, k, met) in changes for m in MODELS for met in METRICS)]
    full = list(range(len(SEEDS)))

    # 검산: report_c.json 과 점추정 일치
    rc = json.loads((RES / "report_c.json").read_text(encoding="utf-8"))
    maxdiff = 0.0
    for k in avail:
        for met in METRICS:
            for m in MODELS:
                maxdiff = max(maxdiff, abs(mean_over(full, changes[(m, k, met)]) - rc["recs"][k][met][m]["mean"]))

    out = {"prereg": "docs/sim-preregistration.md '## 관점 확장 E1~E8' E7",
           "note": "탐색, 서술(판정 규칙 없음). loss = 같은 모형 기준선 대비 씨앗별 변화율 평균(%), 작을수록 좋음. "
                   "EVPI = E_model[min_d loss] − min_d E_model[loss], %p.",
           "prior": PRIOR, "n_boot": N_BOOT, "rng": 'random.Random("c") (analyze_c_pairs.py 와 같은 재표본 열)',
           "available": avail, "check_vs_report_c_max_abs_diff": maxdiff, "metrics": {}}

    point = {}
    for met in METRICS:
        L = {(m, k): mean_over(full, changes[(m, k, met)]) for m in MODELS for k in avail}
        e_min, exp_loss, best_m, best_prior, ev = evpi_of(L, avail)
        point[met] = ev
        out["metrics"][met] = {
            "loss": {k: {m: L[(m, k)] for m in MODELS} | {"prior_expected": exp_loss[k]} for k in avail},
            "best_per_model": best_m, "best_per_model_loss": {m: L[(m, best_m[m])] for m in MODELS},
            "best_prior": best_prior, "best_prior_expected_loss": exp_loss[best_prior],
            "expected_min_given_model": e_min, "evpi": ev}

    rng = random.Random("c")
    boots = {met: [] for met in METRICS}
    bcount = {met: {"best_prior": {k: 0 for k in avail}, **{f"best_{m}": {k: 0 for k in avail} for m in MODELS}}
              for met in METRICS}
    for _ in range(N_BOOT):
        idx = [rng.randrange(len(SEEDS)) for _ in SEEDS]
        for met in METRICS:
            L = {(m, k): mean_over(idx, changes[(m, k, met)]) for m in MODELS for k in avail}
            if any(v is None for v in L.values()):
                continue
            _, _, best_m, best_prior, ev = evpi_of(L, avail)
            boots[met].append(ev)
            bcount[met]["best_prior"][best_prior] += 1
            for m in MODELS:
                bcount[met][f"best_{m}"][best_m[m]] += 1
    for met in METRICS:
        b = boots[met]
        o = out["metrics"][met]
        o["evpi_ci"] = [pct(b, 0.025), pct(b, 0.975)]
        o["evpi_boot_mean"] = sum(b) / len(b)
        o["evpi_boot_share_zero"] = sum(v <= 1e-12 for v in b) / len(b)
        o["n_boot_used"] = len(b)
        o["boot_best_share"] = {kk: {k: c / len(b) for k, c in v.items()} for kk, v in bcount[met].items()}

    (RES / "report_e7_evpi.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    f1 = lambda v: f"{v:+.1f}"
    L_ = ["# E7 정보의 가치(EVPI) — 어느 추종 모형이 맞는지 알면 권고 선택이 얼마나 나아지나 (탐색)", "",
          "등록: `docs/sim-preregistration.md` '관점 확장 E1~E8' 의 E7. 분석만, 판정 규칙 없음(서술).", "",
          "- loss = 같은 모형 기준선 대비 씨앗별 변화율 평균(%, 음수 = 상충 감소, 작을수록 좋음). 정의·자료는 "
          "`report_c.md`(표 F1) 그대로이며 점추정 최대 차이 " + f"{maxdiff:.2e} %p 로 일치를 검산했다.",
          "- 사전확률 Krauss 0.5 · IDM 0.5. EVPI = E_model[min_권고 loss | 모형] − min_권고 E_model[loss] (%p, 항상 ≥ 0).",
          f"- 95 % CI: 씨앗 1~24 복원 추출 {N_BOOT:,}회, random.Random(\"c\")(analyze_c_pairs.py 와 같은 재표본), "
          "재표본마다 두 모형·여섯 권고 평균을 다시 내고 EVPI 를 다시 계산한 백분위.",
          "- 읽는 법: EVPI 가 0 이면 모형을 몰라도 같은 권고를 고르게 되어 모형 불확실성이 결정을 바꾸지 않는다. "
          "EVPI 는 'min' 연산 때문에 재표본 잡음만으로도 위로 치우치므로(0 에 바닥), CI 하한이 0 근처라는 것만으로 "
          "'정보 가치 없음'을 확정할 수는 없다.", "",
          "## 요약", "", "| 지표 | EVPI (%p) | 95 % CI | 재표본 EVPI=0 비율 | Krauss 최선 | IDM 최선 | 사전 기대 최선 |",
          "|---|---|---|---|---|---|---|"]
    for met in METRICS:
        o = out["metrics"][met]
        bm = o["best_per_model"]
        L_.append(f"| {MNAME[met]} | {o['evpi']:.2f} | {o['evpi_ci'][0]:.2f} ~ {o['evpi_ci'][1]:.2f} | "
                  f"{o['evpi_boot_share_zero']*100:.1f} % | {NM[bm['krauss']]} ({f1(o['best_per_model_loss']['krauss'])}) | "
                  f"{NM[bm['idm']]} ({f1(o['best_per_model_loss']['idm'])}) | "
                  f"{NM[o['best_prior']]} ({f1(o['best_prior_expected_loss'])}) |")
    L_.append("")
    for i, met in enumerate(METRICS, 1):
        o = out["metrics"][met]
        L_ += [f"## 표 {i}. {MNAME[met]} — 권고별 loss", "",
               "| 권고 | Krauss | IDM | 사전 기대(0.5·0.5) | 재표본에서 Krauss 최선 | IDM 최선 | 사전 기대 최선 |",
               "|---|---|---|---|---|---|---|"]
        sh = o["boot_best_share"]
        for k in avail:
            l = o["loss"][k]
            mark = lambda c: f"**{c}**"
            kc = f1(l["krauss"]); ic = f1(l["idm"]); pc = f1(l["prior_expected"])
            if o["best_per_model"]["krauss"] == k: kc = mark(kc)
            if o["best_per_model"]["idm"] == k: ic = mark(ic)
            if o["best_prior"] == k: pc = mark(pc)
            L_.append(f"| {NM[k]} | {kc} | {ic} | {pc} | {sh['best_krauss'][k]*100:.1f} % | "
                      f"{sh['best_idm'][k]*100:.1f} % | {sh['best_prior'][k]*100:.1f} % |")
        L_ += ["", f"E_model[min | 모형] = {f1(o['expected_min_given_model'])}, min E_model = "
               f"{f1(o['best_prior_expected_loss'])} → EVPI = {o['evpi']:.2f} %p "
               f"(CI {o['evpi_ci'][0]:.2f} ~ {o['evpi_ci'][1]:.2f}, 재표본 평균 {o['evpi_boot_mean']:.2f}).", ""]
    L_ += ["## 서술", ""]
    for met in METRICS:
        o = out["metrics"][met]
        bm = o["best_per_model"]
        same = bm["krauss"] == bm["idm"]
        L_.append(f"- {MNAME[met]}: " + (
            f"두 모형의 최선이 같은 권고({NM[bm['krauss']]})라 점추정 EVPI 는 0 — 모형을 알아도 선택이 바뀌지 않는다."
            if same else
            f"Krauss 최선 {NM[bm['krauss']]}, IDM 최선 {NM[bm['idm']]}로 갈리고, 사전 기대 최선은 {NM[o['best_prior']]}; "
            f"완전한 모형 정보는 기대 변화율을 {o['evpi']:.2f} %p 더 낮춘다(CI {o['evpi_ci'][0]:.2f} ~ {o['evpi_ci'][1]:.2f})."))
    L_ += ["", "한계: 사전확률 0.5·0.5 는 가정이다. 두 모형 밖의 모형(실제 운전자)은 다루지 않으므로 이 EVPI 는 "
           "'두 모형 중 어느 쪽인가'에 대한 정보 가치의 상한이 아니라 그 질문에 한정된 값이다. 권고 후보는 여섯 개로 고정."]
    (RES / "report_e7_evpi.md").write_text("\n".join(L_) + "\n", encoding="utf-8")
    for met in METRICS:
        o = out["metrics"][met]
        print(met, round(o["evpi"], 3), [round(x, 3) for x in o["evpi_ci"]], o["best_per_model"], o["best_prior"])
    print("check", maxdiff)


if __name__ == "__main__":
    main()
