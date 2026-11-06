"""탐색: R6 결과를 '보정된 사고 규모 분포'(검증 V2 의 가중치)로 다시 가중했을 때 효과(사전 등록 밖, 탐색으로 보고).

  python -X utf8 reweight_r6.py      → results/reweight_r6.json
씨앗마다 (막힌 차로, 처리 시간 구간)의 보정 가중치 / 사전 분포 가중치를 중요도 가중치로 쓴다. 부트스트랩 4,000회.
"""
import json
import random

from validate_prior import W_BLK, W_DUR
import tago_sim as S

B, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"


def binm(dmin):
    return 20 if dmin < 30 else 40 if dmin < 50 else 60 if dmin < 75 else 90 if dmin <= 90 else 120


def main():
    cal = json.loads((S.RES / "validate_cal.json").read_text(encoding="utf-8"))["weights"]
    wc = {tuple(int(x) for x in k.replace("차로", "").replace("분", "").split()): v for k, v in cal.items()}
    runs = {}
    for line in (S.RES / "r6_confirm.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line); runs[(d["seed"], d["scheme"])] = d
    seeds = sorted({s for s, _ in runs})

    def weight(s):
        c = runs[(s, B)]["cond"]; b, m = c["blocked"], binm(c["dur"] / 60)
        p = W_BLK[b] * W_DUR[m]
        return wc.get((b, m), 0.0) / p if p > 0 else 0.0

    ws = {s: weight(s) for s in seeds}
    out = {"n_eff": round(sum(ws.values()) ** 2 / sum(v * v for v in ws.values()), 1), "effects": {}}
    for a, b, name in ((B, U, "u80_vs_baseline"), (G, U, "u80_vs_graded"), (B, G, "graded_vs_baseline")):
        for key in ("fast", "severe", "conflicts"):
            pairs = [(runs[(s, a)][key], runs[(s, b)][key], ws[s]) for s in seeds if runs[(s, a)][key] > 0]
            est = lambda smp: sum((t - c) / c * 100 * w for c, t, w in smp) / sum(w for *_, w in smp)
            r, bs = random.Random(1), []
            for _ in range(4000):
                smp = [pairs[r.randrange(len(pairs))] for _ in pairs]
                if sum(x[2] for x in smp) > 0:
                    bs.append(est(smp))
            bs.sort()
            out["effects"][f"{name}_{key}"] = {"mean": round(est(pairs), 1), "ci": [round(bs[100], 1), round(bs[3900], 1)]}
    (S.RES / "reweight_r6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
