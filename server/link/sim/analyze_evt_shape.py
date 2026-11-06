# 부록 J 보충(탐색, 등록 밖): 임계값 u 에 따른 GPD 형상 모수 ξ — '판정 불가'의 근거 그림(그림 11)용.
# 입력: results/pairs/e_main_{seed}_{scheme}.json.gz (씨앗 1~24, 쌍별 최소 TTC < 1.5 s, 공식 지연 779 s).
# 방법: y = -ttc_min, u ∈ {-1.5, -1.4, ..., -0.5}; 방식마다 24씨앗 초과분 y-u 를 모아 GPD(loc 0) 최대우도 → ξ, σ, n_u, 끝점 u + σ/|ξ|(ξ<0).
#       ξ 의 95 % 구간: 씨앗 복원 추출 NBOOT 회(rng 0, 모든 u·방식에 같은 재표본), 재표본마다 재적합.
# 실행: cd server/link/sim && python -X utf8 analyze_evt_shape.py [NBOOT=200]   → results/report_evt_shape.json·md
import json, pathlib, sys, time
import numpy as np
from multiprocessing import Pool
from analyze_evt import load, gpd_fit, SEEDS

HERE = pathlib.Path(__file__).parent
OUT = HERE / 'results' / 'report_evt_shape'
SCHEMES = {'official': '기준선', 'official+tago12+relay': '단계 연계', 'official+tago12+relay-u80': '일률 80'}
US = [round(-1.5 + 0.1 * i, 1) for i in range(11)]
NBOOT = int(sys.argv[1]) if len(sys.argv) > 1 else 200
RNG = 0

_D = {}
def _init():
    for sch in SCHEMES:
        _D[sch] = {s: v[0] for s, v in load('e_main', sch).items()}

def fit(y, u):
    x = y[y > u] - u
    if len(x) < 50:
        return None, None, len(x)
    c, sc = gpd_fit(x)
    return float(c), float(sc), int(len(x))

def boot(args):
    sch, seeds = args
    y = np.concatenate([_D[sch][s] for s in seeds])
    return [fit(y, u)[:2] for u in US]

def main():
    t0 = time.time()
    _init()
    rng = np.random.default_rng(RNG)
    bseeds = [list(rng.choice(SEEDS, len(SEEDS), replace=True)) for _ in range(NBOOT)]
    res = {'nboot': NBOOT, 'rng': RNG, 'us': US, 'schemes': {}}
    with Pool(initializer=_init) as pool:
        for sch, lab in SCHEMES.items():
            d = _D[sch]
            miss = sorted(set(SEEDS) - set(d))
            y = np.concatenate([d[s] for s in SEEDS if s in d])
            bs = pool.map(boot, [(sch, b) for b in bseeds], chunksize=4)
            rows = []
            for i, u in enumerate(US):
                c, sc, n = fit(y, u)
                xs = np.array([b[i][0] for b in bs if b[i][0] is not None], float)
                eps = np.array([u + b[i][1] / -b[i][0] for b in bs if b[i][0] is not None and b[i][0] < 0], float)
                rows.append({'u': u, 'n_u': n, 'xi': c, 'sigma': sc,
                             'endpoint': (u + sc / -c) if (c is not None and c < 0) else None,
                             'xi_ci': [float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5))],
                             'endpoint_ci': [float(np.percentile(eps, 2.5)), float(np.percentile(eps, 97.5))] if len(eps) else None,
                             'n_boot_ok': int(len(xs))})
                print(f'{lab} u={u:+.1f}: n_u {n} xi {c:+.3f} [{rows[-1]["xi_ci"][0]:+.3f}, {rows[-1]["xi_ci"][1]:+.3f}] ({time.time()-t0:.0f}s)', flush=True)
            res['schemes'][sch] = {'label': lab, 'n_pairs': int(len(y)), 'y_max': float(y.max()), 'missing_seeds': miss, 'rows': rows}
    res['elapsed_s'] = round(time.time() - t0)
    OUT.with_suffix('.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')

    L = ['# 임계값별 GPD 형상 모수 (부록 J 보충, 탐색, 등록 밖)', '',
         f'실행: `cd server/link/sim && python -X utf8 analyze_evt_shape.py {NBOOT}` (입력 results/pairs/e_main_{{1..24}}_{{scheme}}.json.gz, 공식 지연 779 s).', '',
         f'y = −TTC(쌍별 최소, TTC < 1.5 s 쌍만), 임계값 u 초과분 y − u 에 GPD(위치 0) 최대우도(scipy genpareto.fit, analyze_evt.gpd_fit). '
         f'끝점 = u + σ/|ξ|(ξ < 0, 초 단위의 y; 0 이면 TTC 0). ξ 구간: 씨앗 복원 추출 {NBOOT}회(rng {RNG}, 모든 u·방식 같은 재표본)의 2.5·97.5 백분위. '
         'ξ < −0.5 이면 최대우도 정칙 조건 밖, ξ < −1 이면 밀도가 끝점에서 발산(Coles 2001; Smith 1985).', '']
    for sch, S in res['schemes'].items():
        L += [f'## {S["label"]} ({sch}) — 쌍 {S["n_pairs"]:,}개, 관측 최대 y {S["y_max"]:+.4f} s' + (f', 빠진 씨앗 {S["missing_seeds"]}' if S['missing_seeds'] else ''), '',
              '| u (s) | n_u | ξ | ξ 95 % 구간 | σ | 끝점 (s) | 끝점 95 % 구간 |', '| --- | --- | --- | --- | --- | --- | --- |']
        for r in S['rows']:
            ep = '—' if r['endpoint'] is None else f'{r["endpoint"]:+.4f}'
            ec = '—' if r['endpoint_ci'] is None else f'{r["endpoint_ci"][0]:+.4f} ~ {r["endpoint_ci"][1]:+.4f}'
            L.append(f'| {r["u"]:+.1f} | {r["n_u"]:,} | {r["xi"]:+.3f} | {r["xi_ci"][0]:+.3f} ~ {r["xi_ci"][1]:+.3f} | {r["sigma"]:.3f} | {ep} | {ec} |')
        L.append('')
    L.append(f'실행 시간 {res["elapsed_s"]} s.')
    OUT.with_suffix('.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))

if __name__ == '__main__':
    main()
