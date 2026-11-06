"""규칙 감지기(Kotlin TSV)·YAMNet(점수 npy)을 같은 사건 목록으로 채점한다.
- 검출: 사건 [start, end+3s] 안에 켜짐이 있으면 검출, 지연 = 처음 켜진 시각 − start
- 오경보: 어느 사건 창 [start−1, end+5] 와도 겹치지 않는 켜짐 구간 하나 = 1건, 시간당(사건 창 뺀 길이로 나눔)
- YAMNet 켬/끔: 점수 ≥ th 가 2번 연속(≈1 s) → 켬, < th 가 8번 연속(≈4 s) → 끔(앱 규칙 감지기의 0.5 s 켬·4 s 끔 이력과 비슷하게)
- 머리(train_head.py) 확률: <이름>.head.npy(열: 시각 끝(s), 확률)가 있으면 같은 켬/끔 규칙으로 head@th 열을 더한다
사용: python -I score.py <스트림 폴더> <rule.tsv|-> [th,th,...] [머리 th,th,...]  → 표(markdown)를 출력하고 score.json 저장
  rule.tsv 자리에 - 를 주면 규칙 감지기는 뺀다. 머리 문턱을 안 주면 YAMNet 문턱과 같게.
  사건 종류(events.json 의 sub)가 여럿이면 YAMNet 문턱마다 종류별 검출률 표를 더 낸다.
"""
import csv, json, os, sys
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')   # -I 는 PYTHONIOENCODING 을 무시한다(윈도 cp949)
sd, tsv = sys.argv[1], sys.argv[2]
ths = [float(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else [0.1, 0.2, 0.3, 0.5]
hths = [float(v) for v in sys.argv[4].split(',')] if len(sys.argv) > 4 else ths
ev = json.load(open(os.path.join(sd, 'events.json'), encoding='utf-8'))
E = ev['events']

def spans_rule():
    out = {}
    if tsv == '-': return None
    for r in csv.DictReader(open(tsv, encoding='utf-8'), delimiter='\t'):
        if os.path.normcase(os.path.abspath(os.path.dirname(r['path']))) != os.path.normcase(os.path.abspath(sd)): continue   # 데이터셋마다 파일 이름이 같다
        sp =[tuple(map(float, s.split('-'))) for s in r['on_spans'].split(';') if s]
        out[os.path.basename(r['path'])] = sp
    return out

def spans_yam(name, th, on_n=2, off_n=8, ext='.yamnet.npy'):
    a = np.load(os.path.join(sd, name[:-4] + ext))
    sp, on, good, bad, st = [], False, 0, 0, 0.0
    for t, s in a:
        if s >= th: good += 1; bad = 0
        else: bad += 1; good = 0
        if not on and good >= on_n: on = True; st = float(t)
        elif on and bad >= off_n: on = False; sp.append((st, float(t)))
    if on: sp.append((st, float(a[-1, 0])))
    return sp

def score(sp, dur, with_events):
    det, lat = 0, []
    wins = [(e['start'] - 1, e['end'] + 5) for e in E] if with_events else []
    if with_events:
        for e in E:
            hit = [max(a, e['start']) for a, b in sp if a <= e['end'] + 3 and b >= e['start']]
            if hit: det += 1; lat.append(min(hit) - e['start'])
    fa = sum(1 for a, b in sp if not any(a <= w1 and b >= w0 for w0, w1 in wins))
    free = dur - sum(w1 - w0 for w0, w1 in wins)
    return dict(recall=det / len(E) if with_events else None, lat_med=float(np.median(lat)) if lat else None, fa_per_h=fa / (free / 3600), fa=fa, on_frac=sum(b - a for a, b in sp) / dur)

def recall_by_sub(sp):
    out = {}
    for sb in sorted({e['sub'] for e in E}):
        es = [e for e in E if e['sub'] == sb]
        out[sb] = sum(1 for e in es if any(a <= e['end'] + 3 and b >= e['start'] for a, b in sp)) / len(es)
    return out

rule = spans_rule()
res = {}
for name, f in ev['files'].items():
    we = f['snr'] is not None
    if rule is not None: res[(name, 'rule')] = score(rule.get(name, []), f['dur'], we)
    if os.path.exists(os.path.join(sd, name[:-4] + '.yamnet.npy')):
        for th in ths:
            sp = spans_yam(name, th); res[(name, f'yamnet@{th}')] = score(sp, f['dur'], we)
            if we: res[(name, f'yamnet@{th}')]['by_sub'] = recall_by_sub(sp)   # 종류별 검출률(score.json 에도 남김, cabin_table.py 가 읽음)
    if os.path.exists(os.path.join(sd, name[:-4] + '.head.npy')):
        for th in hths: res[(name, f'head@{th}')] = score(spans_yam(name, th, ext='.head.npy'), f['dur'], we)

# 짧은 클립은 규칙 감지기가 구조상 못 잡는다(3 s 창 + 0.5 s) → 길이별 검출률도 따로
def by_len(name, sp):
    out = {}
    for lo, hi in ((0, 4), (4, 8), (8, 99)):
        es = [e for e in E if lo <= e['dur'] < hi]
        if not es: continue
        d = sum(1 for e in es if any(a <= e['end'] + 3 and b >= e['start'] for a, b in sp))
        out[f'{lo}-{hi}s'] = (d, len(es))
    return out

meths = sorted({m for _, m in res})
print(f"## {ev['dataset']} — 사건 {len(E)}개(길이 중앙값 {np.median([e['dur'] for e in E]):.1f}s)\n")
print('| 조건 | ' + ' | '.join(meths) + ' |'); print('|' + '---|' * (len(meths) + 1))
for name in ev['files']:
    cells = []
    for m in meths:
        r = res.get((name, m))
        if not r: cells.append('-'); continue
        cells.append(f"{r['recall']*100:.0f}% · 오경보 {r['fa_per_h']:.1f}/h" if r['recall'] is not None else f"오경보 {r['fa_per_h']:.1f}/h")
    print(f'| {name[:-4]} | ' + ' | '.join(cells) + ' |')
if rule is not None: print('\n규칙 감지기 클립 길이별 검출(out_snr+0):', by_len('out_snr+0.wav', rule.get('out_snr+0.wav', [])))

# 사건 종류(sub)가 둘 이상이면(합성 세트의 패턴×파형 등) YAMNet 문턱마다 종류별 검출률
subs = sorted({e['sub'] for e in E})
if len(subs) > 1:
    for th in ths:
        print(f'\n종류별 검출(yamnet@{th}):\n')
        print('| 조건 | ' + ' | '.join(subs) + ' |'); print('|' + '---|' * (len(subs) + 1))
        for name, f in ev['files'].items():
            if f['snr'] is None or not os.path.exists(os.path.join(sd, name[:-4] + '.yamnet.npy')): continue
            sp = spans_yam(name, th); cells = []
            for sb in subs:
                es = [e for e in E if e['sub'] == sb]
                cells.append(f"{sum(1 for e in es if any(a <= e['end'] + 3 and b >= e['start'] for a, b in sp)) / len(es) * 100:.0f}%")
            print(f'| {name[:-4]} | ' + ' | '.join(cells) + ' |')
json.dump({f'{k[0]}|{k[1]}': v for k, v in res.items()}, open(os.path.join(sd, 'score.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
