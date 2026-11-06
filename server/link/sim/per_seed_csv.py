"""씨앗 1~24 씨앗별 원자료를 한 줄에 모은다(PC 결과만) → results/per_seed_v2.csv

  python -X utf8 per_seed_csv.py
조건 열(seed, demand, blocked, dur, rain, inatt, comply)은 v2_main 'official' 의 cond.
rb_comply 는 현장 따름 비율을 바꿔 다시 뽑은 것이라 그 따름 값을 rb1_comply 열로 따로 둔다.
방식 열: v2_main 8개·fu_pc 3개·rb_design 3개는 scheme 이름 그대로, rb_comply 3개는 rb1_ 접두,
d1 10조건은 짧은 영문 접두(d1_delay0 등) + fast 만. 빈 칸 = 값 없음(inc_at 이 None 등).
씨앗 101~200 은 results/r6_per_seed.csv.
"""
import csv
import json
from pathlib import Path

RES = Path(__file__).parent / "results"
COND = ("seed", "demand", "blocked", "dur", "rain", "inatt", "comply")
METRICS = ("fast", "severe", "conflicts", "fast1", "inc_at", "queue_km")


def rows(name):
    return [json.loads(x) for x in (RES / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def d1_name(ov):
    if "relay_delay" in ov:
        return f"d1_delay{ov['relay_delay']:.0f}"
    if "loss" in ov:
        return f"d1_loss{ov['loss'] * 100:.0f}"
    e = ov["tail_err"]
    return f"d1_tail{'p' if e > 0 else 'm'}{abs(e):.0f}"


def main():
    groups = []  # (열 접두, 파일, {seed: row})
    for fname, prefix in (("v2_main.jsonl", ""), ("fu_pc.jsonl", ""), ("rb_comply.jsonl", "rb1_"), ("rb_design.jsonl", "")):
        by = {}
        for r in rows(fname):
            by.setdefault(prefix + r["scheme"], {})[r["seed"]] = r
        groups += [(k, v, METRICS) for k, v in by.items()]
    d1 = {}
    for r in rows("d1.jsonl"):
        d1.setdefault(json.dumps(r["ov"], sort_keys=True), {})[r["seed"]] = r
    order = lambda k: (list(json.loads(k))[0], list(json.loads(k).values())[0])
    groups += [(d1_name(json.loads(k)), d1[k], ("fast",)) for k in sorted(d1, key=order)]
    names = [g[0] for g in groups]
    assert len(names) == len(set(names)), names

    base = groups[[g[0] for g in groups].index("official")][1]
    seeds = sorted(base)
    rb1_any = next(g[1] for g in groups if g[0].startswith("rb1_"))
    header = list(COND) + ["rb1_comply"] + [f"{n}_{m}" for n, _, ms in groups for m in ms]
    with (RES / "per_seed_v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for s in seeds:
            c = base[s]["cond"]
            line = [c[k] for k in COND] + [rb1_any[s]["cond"]["comply"] if s in rb1_any else ""]
            for _, by, ms in groups:
                r = by.get(s)
                line += ["" if r is None or r.get(m) is None else r[m] for m in ms]
            w.writerow(line)
    print(f"{len(seeds)} 씨앗 × {len(header)} 열 → {RES / 'per_seed_v2.csv'}")


if __name__ == "__main__":
    main()
