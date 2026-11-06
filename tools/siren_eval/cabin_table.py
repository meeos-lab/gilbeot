"""차 안 조건 격자 표(README '차 안 조건' 절)를 세 스트림의 score.json 에서 만든다.
사용: python -I cabin_table.py <kr_synth_cabin 폴더> <a_cc0_whelen_cabin 폴더> <a_alarm_folha_cabin 폴더> [문턱,문턱,...]
  칸 = 문턱별 검출률(기본 0.5 / 0.6 / 0.7), 배경 행 = 오경보 횟수/h. 시보 열은 차량이 아닌 소리라 '검출' = 잘못 켜짐.
"""
import json, os, sys

sys.stdout.reconfigure(encoding='utf-8')
kr, wh, fo = sys.argv[1:4]
ths = [float(v) for v in sys.argv[4].split(',')] if len(sys.argv) > 4 else [0.5, 0.6, 0.7]
S = {k: json.load(open(os.path.join(d, 'score.json'), encoding='utf-8')) for k, d in (('kr', kr), ('wh', wh), ('fo', fo))}
files = list(json.load(open(os.path.join(kr, 'events.json'), encoding='utf-8'))['files'])
LABEL = {'out_clean': '밖 · 소음 없음', 'out_snr+10': '밖 · 도로 소음 +10 dB', 'out_snr+0': '밖 · 도로 소음 0 dB', 'out_snr-5': '밖 · 도로 소음 −5 dB',
         'cab_clean': '차 안 · 소음 없음', 'cab60_snr+10': '차 안 · 60 km/h +10 dB', 'cab60_snr+0': '차 안 · 60 km/h 0 dB', 'cab60_snr-5': '차 안 · 60 km/h −5 dB',
         'cab100_snr+10': '차 안 · 100 km/h +10 dB', 'cab100_snr+0': '차 안 · 100 km/h 0 dB', 'cab100_snr-5': '차 안 · 100 km/h −5 dB',
         'neg_out': '배경만 1 h · 밖(도로 소음)', 'neg_cab60': '배경만 1 h · 차 안 60 km/h', 'neg_cab100': '배경만 1 h · 차 안 100 km/h'}
COLS = [('합성 전체(300)', 'kr', None), ('합성 웨일 harm', 'kr', 'fire_wail_harm'), ('합성 옐프 harm', 'kr', 'police_yelp_harm'),
        ('합성 하이로우 harm', 'kr', 'amb_hilo_harm'), ('Whelen 실녹음(1×30)', 'wh', None), ('Folha 시보(차량 아님, 1×30)', 'fo', None)]


def cell(src, sub, f):
    vals = []
    for th in ths:
        r = S[src].get(f'{f}|yamnet@{th}')
        if r is None: vals.append('-'); continue
        if r['recall'] is None: vals.append(f"{r['fa']}회")
        elif sub: vals.append(f"{r['by_sub'][sub] * 100:.0f}")
        else: vals.append(f"{r['recall'] * 100:.0f}")
    return ' / '.join(vals) + ('' if S[src].get(f'{f}|yamnet@{ths[0]}', {}).get('recall') is None else ' %')


print('| 조건(SNR 은 A 가중) | ' + ' | '.join(c[0] for c in COLS) + ' |')
print('|' + '---|' * (len(COLS) + 1))
for f in files:
    name = f[:-4]
    cells = [cell(src, sub, f) if not (name.startswith('neg') and sub) else '' for _, src, sub in COLS]
    print(f'| {LABEL.get(name, name)} | ' + ' | '.join(cells) + ' |')
print(f"\n칸 = 문턱 {' / '.join(str(t) for t in ths)} 의 검출률(배경 행은 1시간 오경보 횟수).")
