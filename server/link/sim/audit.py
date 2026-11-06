"""리뷰 대응 점검(탐색): 같은 씨앗을 다른 설정으로 돌려 본 실험(results/main.jsonl)과 짝 비교.
  TAGO_STEP=0.25 TAGO_TINC=900 python -X utf8 audit.py numeric   → results/audit_numeric.jsonl
  TAGO_NOATTN=1 python -X utf8 audit.py noattn                   → results/audit_noattn.jsonl
"""
import sys
import tago_sim as S

if __name__ == "__main__":
    name = sys.argv[1]
    seeds = range(1, int(sys.argv[2]) + 1 if len(sys.argv) > 2 else 7)
    schemes = ("none", "official", "official+tago12+relay")
    S.pool_run([(S.cond_for(s), sc, False) for s in seeds for sc in schemes], S.RES / f"audit_{name}.jsonl", procs=14)
