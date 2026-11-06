# 사전 등록 X(docs/sim-preregistration.md, 2026-11-05 16:03): 극값 이론으로 상충 꼬리 → 기대 추돌 비.
# 입력: results/pairs/e_main_*.json.gz, e_delay_*.json.gz (쌍별 최소 TTC < 1.5 s). 출력: results/report_evt.md·json.
# POT(주): y = -ttc_min, u ∈ {-1.0(주), -1.5, -0.75}; 방식마다 24씨앗 초과분을 모아 GPD(loc 0) MLE; Ĉ_s = n_{u,s}·P(Y-u > -u).
# BM(보조): 씨앗·5분 구간별 최대 y → GEV; 구간당 P(Y ≥ 0) × 구간 수. CI: 씨앗 복원 추출 1,000회(rng 0), 재표본마다 재적합.
import gzip, json, pathlib, sys, time
import numpy as np
from multiprocessing import Pool
from scipy.stats import genpareto, genextreme

HERE = pathlib.Path(__file__).parent
PAIRS = HERE / 'results' / 'pairs'
OUT = HERE / 'results' / 'report_evt'
SEEDS = list(range(1, 25))
SCHEMES = {'official': '기준선', 'official+tago12+relay': '단계 연계', 'official+tago12+relay-u80': '일률 80',
           'official+tago12+relay-sham': 'sham', 'official+tago12+relay-u80tail': 'u80tail', 'official+tago12+relay-u80right': 'u80right'}
STEMS = {'e_main': '779 s', 'e_delay': 'E1 실측 등록 지연'}
US = [-1.0, -1.5, -0.75]
BLOCK = 300.0
NBOOT, RNG = 1000, 0
COUNT_RATES = {'official+tago12+relay-u80': -19.1, 'official+tago12+relay': 12.6}   # 건수 변화율(표 3), 부호 비교용

def load(stem, scheme):
    """씨앗 → (y 배열, 5분 구간 최댓값 배열)"""
    out = {}
    for s in SEEDS:
        fn = PAIRS / f'{stem}_{s}_{scheme}.json.gz'
        if not fn.exists():
            continue
        d = json.load(gzip.open(fn, 'rt', encoding='utf-8'))
        ci, ct = d['cols'].index('ttc_min'), d['cols'].index('t0_rel')
        y = -np.array([r[ci] for r in d['rows']], float)
        t = np.array([r[ct] for r in d['rows']], float)
        bm = {}
        for yy, tt in zip(y, t):
            b = int(tt // BLOCK)
            bm[b] = max(bm.get(b, -9), yy)
        out[s] = (y, np.array(list(bm.values()), float))
    return out

def gpd_fit(exc):
    c, loc, sc = genpareto.fit(exc, floc=0)
    return c, sc

def pot_crashes(data, seeds, u):
    """씨앗 목록(복원 추출 가능)으로 모은 초과분에 GPD 적합 → (Ĉ 합, ξ, σ, 끝점, n_u)"""
    excs = [data[s][0][data[s][0] > u] - u for s in seeds]
    allx = np.concatenate(excs)
    if len(allx) < 50:
        return 0.0, None, None, None, len(allx)
    c, sc = gpd_fit(allx)
    p = genpareto.sf(-u, c, loc=0, scale=sc)
    endpoint = (u + sc / -c) if c < 0 else None
    return float(sum(len(e) for e in excs) * p), float(c), float(sc), endpoint, int(len(allx))

def bm_crashes(data, seeds):
    allm = np.concatenate([data[s][1] for s in seeds])
    if len(allm) < 30:
        return 0.0, None, None, len(allm)
    c, loc, sc = genextreme.fit(allm)
    p = genextreme.sf(0.0, c, loc=loc, scale=sc)
    return float(len(allm) * p), float(c), float(sc), int(len(allm))

_DATA = {}
def _init(stems):
    for stem, sch in stems:
        _DATA[(stem, sch)] = load(stem, sch)

def ratio_boot(args):
    stem, sch, u, seeds, mode = args
    base, other = _DATA[(stem, 'official')], _DATA[(stem, sch)]
    if mode == 'pot':
        cb = pot_crashes(base, seeds, u)[0]
        co = pot_crashes(other, seeds, u)[0]
    else:
        cb = bm_crashes(base, seeds)[0]
        co = bm_crashes(other, seeds)[0]
    return (co / cb) if cb > 0 else np.nan

def main():
    t0 = time.time()
    rng = np.random.default_rng(RNG)
    boot_seeds = [list(rng.choice(SEEDS, len(SEEDS), replace=True)) for _ in range(NBOOT)]
    res = {'nboot': NBOOT, 'block_s': BLOCK, 'us': US, 'stems': {}}
    keys = [(stem, sch) for stem in STEMS for sch in SCHEMES if (PAIRS / f'{stem}_1_{sch}.json.gz').exists()]
    pool = Pool(initializer=_init, initargs=(keys,))
    for stem, lab in STEMS.items():
        data = {sch: load(stem, sch) for sch in SCHEMES if (PAIRS / f'{stem}_1_{sch}.json.gz').exists()}
        base = data['official']
        R = {'label': lab, 'schemes': {}}
        for sch, d in data.items():
            if set(d) != set(SEEDS):
                print('warn: seeds', stem, sch, sorted(set(SEEDS) - set(d)))
            S = {'n_pairs': int(sum(len(d[s][0]) for s in d)), 'pot': {}, 'bm': {}}
            for u in US:
                C, c, sc, ep, n = pot_crashes(d, SEEDS, u)
                S['pot'][str(u)] = {'crash': C, 'xi': c, 'sigma': sc, 'endpoint': ep, 'n_u': n}
            C, c, sc, n = bm_crashes(d, SEEDS)
            S['bm'] = {'crash': C, 'xi_gev': c, 'sigma': sc, 'n_blocks': n}
            if sch != 'official':
                for u in US:
                    pt = S['pot'][str(u)]['crash'] / R['schemes']['official']['pot'][str(u)]['crash'] if R['schemes']['official']['pot'][str(u)]['crash'] > 0 else None
                    S['pot'][str(u)]['ratio'] = pt
                    if sch in COUNT_RATES or sch in ('official+tago12+relay-sham', 'official+tago12+relay-u80tail', 'official+tago12+relay-u80right'):
                        bs = pool.map(ratio_boot, [(stem, sch, u, bsd, 'pot') for bsd in boot_seeds], chunksize=20)
                        bs = np.array(bs, float)
                        S['pot'][str(u)]['ratio_ci'] = [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))]
                        S['pot'][str(u)]['nan_frac'] = float(np.isnan(bs).mean())
                        print(f'{stem} {sch} u={u}: ratio {pt} CI {S["pot"][str(u)]["ratio_ci"]} ({time.time()-t0:.0f}s)', flush=True)
                pb = R['schemes']['official']['bm']['crash']
                S['bm']['ratio'] = S['bm']['crash'] / pb if pb > 0 else None
                if sch in COUNT_RATES:
                    bs = np.array(pool.map(ratio_boot, [(stem, sch, None, bsd, 'bm') for bsd in boot_seeds], chunksize=20), float)
                    S['bm']['ratio_ci'] = [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))]
                    S['bm']['nan_frac'] = float(np.isnan(bs).mean())
            R['schemes'][sch] = S
        res['stems'][stem] = R
    pool.close()
    OUT.with_suffix('.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')

    L = ['# 극값 이론 환산 X (사전 등록 2026-11-05 16:03)', '',
         f'POT: y = −TTC, GPD(loc 0) MLE, 씨앗 24개 합산; BM: {BLOCK/60:.0f}분 구간 최댓값 → GEV. CI: 씨앗 복원 추출 {NBOOT}회(rng {RNG}), 재표본마다 재적합. 추돌 수는 시뮬레이션 안의 기대값이며 실사고 수가 아니다.', '']
    for stem, R in res['stems'].items():
        L += [f'## {stem} ({R["label"]})', '',
              '| 방식 | 쌍 수 | u | n_u | ξ | σ | 끝점 | 기대 추돌 Ĉ | 비 Ĉ/Ĉ기준 (95 % CI) | 변화율 | 건수 변화율(표 3) |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for sch, S in R['schemes'].items():
            for u in US:
                p = S['pot'][str(u)]
                ep = '—' if p['endpoint'] is None else f'{p["endpoint"]:+.3f}'
                if sch == 'official':
                    rt = '—'; ch = '—'
                else:
                    r = p.get('ratio'); ci = p.get('ratio_ci')
                    rt = ('판정 불가' if r is None else f'{r:.3f}') + (f' ({ci[0]:.3f} ~ {ci[1]:.3f})' if ci else '')
                    ch = '—' if r is None else f'{(r-1)*100:+.1f} %'
                cr = COUNT_RATES.get(sch); cr = f'{cr:+.1f} %' if cr is not None else '—'
                L.append(f'| {SCHEMES[sch]} | {S["n_pairs"]} | {u} | {p["n_u"]} | {p["xi"]:+.3f} | {p["sigma"]:.3f} | {ep} | {p["crash"]:.2f} | {rt} | {ch} | {cr} |' if p['xi'] is not None else f'| {SCHEMES[sch]} | {S["n_pairs"]} | {u} | {p["n_u"]} | — | — | — | 0 | — | — | {cr} |')
            b = S['bm']
            if b['xi_gev'] is not None:
                r = b.get('ratio'); ci = b.get('ratio_ci')
                rt = '—' if sch == 'official' else (('판정 불가' if r is None else f'{r:.3f}') + (f' ({ci[0]:.3f} ~ {ci[1]:.3f})' if ci else ''))
                ch = '—' if (sch == 'official' or r is None) else f'{(r-1)*100:+.1f} %'
                L.append(f'| {SCHEMES[sch]} | {S["n_pairs"]} | BM 5분 | {b["n_blocks"]} 구간 | {b["xi_gev"]:+.3f} (GEV) | {b["sigma"]:.3f} | — | {b["crash"]:.2f} | {rt} | {ch} | {COUNT_RATES.get(sch, "—") if sch in COUNT_RATES else "—"} |')
        L.append('')
    L.append(f'실행 시간 {time.time()-t0:.0f} s.')
    OUT.with_suffix('.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))

if __name__ == '__main__':
    main()
