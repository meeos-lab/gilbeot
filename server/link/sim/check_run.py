"""점검: 보정 2차로 구경 감속, 새 주시태만 모형(씨앗 2개 × 방식 3개)."""
import multiprocessing as mp
import sys
import time

import calib
import tago_sim as S

if __name__ == "__main__":
    t0 = time.time()
    with mp.get_context("spawn").Pool(12) as pool:
        cal = pool.map_async(calib.measure, [(0.6, 0.5, 0, None), (0.6, 0.5, 2, 25), (0.6, 0.5, 2, 20), (0.6, 0.5, 2, 15)])
        runs = pool.map_async(S.run_one, [(S.cond_for(s), sc, False) for s in (4, 5) for sc in ("official", "official+tago12+relay", "tago100")])
        rows = cal.get()
        base = rows[0]["mid"]
        print(f"기본 {base:.0f}대/시", flush=True)
        for r in rows[1:]:
            print(f"2차로 막힘 구경 {r['gawk']}km/h: {r['down']:.0f}대/시 = {r['down'] / base:.2f}", flush=True)
        for r in runs.get():
            print(r["seed"], r["scheme"], "상충", r["conflicts"], "고속", r["fast"], r["kinds"], "추돌", r["crashes"], "정체", r["queue_km"], "km 잘림", r["truncated"], "확정", r["inc_at"], flush=True)
    print(f"{time.time() - t0:.0f}s", flush=True)
