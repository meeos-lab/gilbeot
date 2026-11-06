# 사전 등록 K(docs/sim-preregistration.md, 2026-11-05 15:58): 2차 사고 연간 건수 환산.
# 입력: data/kec_secondary_2020-2025_15142800.csv (공공데이터포털 15142800, 월 × 연도 집계).
# 출력: results/report_annual.md, results/report_annual.json. 판정 없음(탐색·서술).
import csv, json, pathlib, statistics as st

HERE = pathlib.Path(__file__).parent
SRC = HERE / 'data' / 'kec_secondary_2020-2025_15142800.csv'
OUT = HERE / 'results' / 'report_annual'

# 등록한 세 조건의 r (씨앗별 기준선 대비 변화율 평균, 95 % 부트스트랩 CI). 출처: 원고 표 2·3(fu_pc 정정판)·4.16절 E1.
R = {
    'a. 일률 80 대 기준선(공식 지연 779 s)': (-19.1, -27.2, -11.1),
    'b. 일률 80 대 기준선(E1, 실측 등록 지연)': (-6.3, -13.5, 0.5),
    'c. 단계 연계 대 기준선(779 s)': (12.6, -0.2, 26.3),
}
DENOM_YEARS = (2023, 2024, 2025)

rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig')))
years = sorted({int(k[:4]) for k in rows[0] if k.endswith('건수')})
N = {y: sum(int(r[f'{y}년 2차사고 건수']) for r in rows) for y in years}
D = {y: sum(int(r[f'{y}년 2차사고 사망자수']) for r in rows) for y in years}
I = {y: sum(int(r[f'{y}년 2차사고 부상자수']) for r in rows) for y in years}
month_tot = {r['발생월']: sum(int(r[f'{y}년 2차사고 건수']) for y in years) for r in rows}

nbar = st.mean(N[y] for y in DENOM_YEARS)
nmin, nmax = min(N[y] for y in DENOM_YEARS), max(N[y] for y in DENOM_YEARS)
dbar = st.mean(D[y] for y in DENOM_YEARS)

conv = {}
for name, (pt, lo, hi) in R.items():
    conv[name] = {
        'r': [pt, lo, hi],
        'dN_mean': [round(pt / 100 * nbar, 1), round(lo / 100 * nbar, 1), round(hi / 100 * nbar, 1)],
        'dN_range': [round(min(lo / 100 * nmin, lo / 100 * nmax), 1), round(max(hi / 100 * nmin, hi / 100 * nmax), 1)],
    }

out = {
    'source': '공공데이터포털 15142800 한국도로공사_고속도로 2차사고 발생현황_20251231 (2026-11-05 내려받음)',
    'N': N, 'D': D, 'I': I, 'fatality_rate': {y: round(D[y] / N[y], 3) for y in years},
    'month_total': month_tot,
    'denominator_years': DENOM_YEARS, 'N_bar': round(nbar, 1), 'N_min': nmin, 'N_max': nmax, 'D_bar': round(dbar, 1),
    'conversion': conv,
}
OUT.with_suffix('.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

L = ['# 연간 건수 환산 K (사전 등록 2026-11-05 15:58)', '',
     f'자료: {out["source"]}. 도로공사 관리 고속도로(민자 제외), 월 집계.', '',
     '| 연도 | 2차 사고 건수 | 사망자 | 부상자 | 치사율(사망/건수) |', '| --- | --- | --- | --- | --- |']
for y in years:
    L.append(f'| {y} | {N[y]} | {D[y]} | {I[y]} | {D[y] / N[y]:.2f} |')
L += ['', f'분모(등록대로 {DENOM_YEARS[0]}~{DENOM_YEARS[-1]}): 평균 N̄ = {nbar:.1f}건/년(최소 {nmin}, 최대 {nmax}), 사망자 평균 {dbar:.1f}명/년.',
      f'월 합계(6년): 최대 {max(month_tot, key=month_tot.get)}월 {max(month_tot.values())}건, 최소 {min(month_tot, key=month_tot.get)}월 {min(month_tot.values())}건.', '',
      '환산 ΔN = r × N̄ (가정: 상충 변화율 = 사고 변화율, 전 고속도로 전 차량 안내, 경부선 4차로 모형의 전국 전이, 자료 정의 = 본 연구 범위 — 어느 것도 검증되지 않음).', '',
      '| 조건 | r (95 % CI) | ΔN (N̄ 기준, CI 양끝) | ΔN 범위(3년 최소·최대 × CI) |', '| --- | --- | --- | --- |']
for name, c in conv.items():
    pt, lo, hi = c['r']
    m = c['dN_mean']
    L.append(f'| {name} | {pt:+.1f} % ({lo:+.1f} ~ {hi:+.1f}) | {m[0]:+.1f} ({m[1]:+.1f} ~ {m[2]:+.1f}) 건/년 | {c["dN_range"][0]:+.1f} ~ {c["dN_range"][1]:+.1f} 건/년 |')
L += ['', '판정 없음. 결론·초록에는 쓰지 않는다(등록 K).']
OUT.with_suffix('.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print('\n'.join(L))
