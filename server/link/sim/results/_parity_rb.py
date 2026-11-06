import json, multiprocessing as mp, sys
sys.path.insert(0, ".")
import tago_sim as S
def go(sc): return S.run_one((S.cond_for(3), sc, False))
if __name__ == "__main__":
    ref = {}
    for f in ("v2_main.jsonl", "fu_pc.jsonl"):
        for r in map(json.loads, open(S.RES / f, encoding="utf-8")):
            if r["seed"] == 3: ref[r["scheme"]] = (r["conflicts"], r["fast"], r["severe"])
    with mp.get_context("spawn").Pool(2) as p:
        for r in p.map(go, ["official+tago12+relay", "official+tago12+relay-u80"]):
            got = (r["conflicts"], r["fast"], r["severe"])
            print("코드 확인", r["scheme"], got, ref[r["scheme"]], "같음" if got == ref[r["scheme"]] else "다름", flush=True)
