"""맥에서 주의 회복 민감도(v2): 회복 확률 0·0.35·0.65·1.0 × 기준선·넘김 × 씨앗 1~8 → results/v2_attn{p}.jsonl
  TAGO_STEP=0.25 TAGO_TAU=0.5 TAGO_TINC=900 TAGO_GAWK=1:13,2:13 python mac_sweep.py
"""
import json
import multiprocessing as mp
import os
import time

import tago_sim as S

PS = (0.0, 0.35, 0.65, 1.0)


def run(job):
    p, c, sc = job
    S.ATTN_P = p                       # 일꾼 프로세스 안에서 회복 확률만 바꾼다
    r = S.run_one((c, sc, False))
    r["attn_p"] = p
    return r


if __name__ == "__main__":
    done = set()
    for p in PS:
        f = S.RES / f"v2_attn{p}.jsonl"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                d = json.loads(line); done.add((p, d["seed"], d["scheme"]))
    jobs = [(p, S.cond_for(s), sc) for s in range(1, 9) for p in PS for sc in ("official", "official+tago12+relay") if (p, s, sc) not in done]
    print(len(jobs), "실행", flush=True)
    t0 = time.time()
    with mp.get_context("spawn").Pool(int(os.environ.get("TAGO_PROCS", "16"))) as pool:
        for i, r in enumerate(pool.imap_unordered(run, jobs), 1):
            with (S.RES / f"v2_attn{r['attn_p']}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  {i}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
