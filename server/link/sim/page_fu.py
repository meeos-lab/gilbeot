"""후속 실험 결과를 결과 페이지(page/report.json)에 합친다: 세 변형 행, H5~H7, 제목·요약. analyze_fu.py 다음에 sim 폴더에서 실행"""
import json, statistics, pathlib, sys
sys.path.insert(0, ".")
import analyze as A
base = [r for r in A.load("v2_main.jsonl") if r["scheme"] in ("official", "official+tago12+relay")]
tab = A.by_seed(base + A.load("fu_pc.jsonl"))
p = pathlib.Path("page/report.json"); R = json.loads(p.read_text(encoding="utf-8"))
G = "official+tago12+relay"
for sc in ("official+tago12+relay-u80", "official+tago12+relay-near", "official+tago12+relay-none"):
    rs = [d[sc] for d in tab.values() if sc in d]
    e = {m: statistics.mean(r[m] for r in rs) for m in ("fast", "fast1", "conflicts", "severe", "travel")}
    e["n"] = len(rs)
    e["vs_official"] = {m: A.reduction(tab, sc, "official", m) for m in ("fast", "fast1", "conflicts", "severe")}
    tv = [d[sc]["travel"] - d["official"]["travel"] for d in tab.values() if d[sc]["travel"] and d["official"]["travel"]]
    e["travel_vs_official_s"] = statistics.mean(tv)
    R["schemes"][sc] = e
fu = json.loads(pathlib.Path("results/report_fu.json").read_text(encoding="utf-8"))["pc"]["hypotheses"]
labels = {"H5 일률 80 < 단계": ("H5", "official+tago12+relay-u80", "넘김 메시지의 권고를 일률 80 km/h로 바꾸면 단계(90·70·50)보다 고속 접근 상충이 적다"),
          "H6 꼬리 근처만 < 단계": ("H6", "official+tago12+relay-near", "꼬리 1 km 안에서만 70 km/h를 권하면 단계보다 고속 접근 상충이 적다"),
          "H7 권고 없음 < 단계": ("H7", "official+tago12+relay-none", "속도·차로 권고 없이 경고만 하면 단계보다 고속 접근 상충이 적다")}
for k, h in fu.items():
    hid, sc, lab = labels[k]
    R["hypotheses"][hid] = {"label": lab + "(후속 실험)", "p": h["p"], "p_holm": h["p_holm"], "effect": A.reduction(tab, sc, G, "fast")}
R["headline"] = "Tago 의 빠른 감지는 유효하다. 넘김 메시지의 단계 감속 권고를 일률 80 으로 바꾸면 고속 접근 상충까지 준다"
R["lede"] = ("수정 모형(v2, 씨앗 24개)에서 보급 12 % 의 Tago 는 사고를 중앙값 137초에 확정했다(공식 779초). 이를 공식 채널로 넘겨 모든 차에 알리면 "
             "전체 상충은 20.2 %, 심각 상충은 13.9 % 줄었지만, 먼 곳부터 90·70·50 km/h 로 낮추라는 단계 권고 때문에 미리 정한 주 지표인 고속 접근 상충은 12.6 % 늘었다. "
             "사전 고정한 후속 실험(72회)에서 알림 시점은 두고 권고만 일률 80 km/h 로 바꾸자 고속 접근 상충이 기준선보다 19.1 %, 꼬리 1 km 안에서만 70 을 권하면 23.0 % 줄었다(단계 대비 보정 p < 0.001, 맥 재현 같은 방향). "
             "처음 모형(v1)의 −18.2 % 는 '경고를 받으면 모두 주의를 되찾는다'는 가정에서 나왔다는 것이 동료 검토와 점검 실험으로 확인돼 바꿨다.")
p.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print({k: round(v["effect"]["mean"]*100, 1) for k, v in R["hypotheses"].items()})
