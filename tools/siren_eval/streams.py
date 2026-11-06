"""평가용 '주행 스트림' 만들기: 도로 소음 클립을 이어 붙인 배경에 사이렌 클립을 띄엄띄엄 넣는다(SNR 별).
앱의 감지기는 3초 창 + 0.5초 켬 이력이라 짧은 클립 단독으로는 판정할 수 없다 → 실제처럼 이어지는 소리에 넣어 본다.
사용: python -I streams.py <데이터 루트> <dataset> <최대 사건 수|0=전부> <seed>
출력: <루트>/streams/<dataset>/<cond>_snr<±dB>.wav + events.json, 그리고 사건 없는 배경만 neg_<cond>.wav(오경보용)
선택: --ids <목록 파일>(한 줄에 manifest id 하나, 이 클립만 쓴다 — 학습/시험 분할용) · --name <하위 폴더>(기본 = dataset 이름)
  --bg <dataset> --bg-ids <목록 파일>: 배경 도로 소음을 다른 데이터셋(의 이 클립들)에서 — 합성·낱개 음원처럼 도로 소음이 없는 세트용
  --repeat <N>: 사이렌 클립마다 N 번 넣는다(원본이 1~2개뿐인 세트; 결과는 '원본 수 × N 삽입'으로 읽는다)
cond: out(원본) · cab(차 안 근사: 2차 저역 통과 1.5 kHz — 차체가 높은 음을 더 깎는다는 거친 근사, 실측 아님)
"""
import csv, json, os, sys, wave
import numpy as np
from scipy.signal import butter, sosfilt

root, ds, maxev, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
opt = dict(zip(sys.argv[5::2], sys.argv[6::2]))
assert set(opt) <= {'--ids', '--name', '--bg', '--bg-ids', '--repeat'} and len(sys.argv[5:]) % 2 == 0, sys.argv[5:]
keep = {l.strip() for l in open(opt['--ids'], encoding='utf-8') if l.strip()} if '--ids' in opt else None
sub = opt.get('--name', ds)
SR = 16000
SNRS = [6, 0, -6, -12, -18]
GAP = (15.0, 30.0)          # 사건 사이 배경 길이(초)
NEG_HOURS = 1.0             # 오경보 측정용 배경만 스트림 길이(시간)
rng = np.random.default_rng(seed)

rows = [r for r in csv.DictReader(open(os.path.join(root, 'manifest.csv'), encoding='utf-8')) if r['dataset'] == ds and (keep is None or r['id'] in keep)]
sir = [r for r in rows if r['cls'] == 'siren']; neg = [r for r in rows if r['cls'] == 'neg']
if '--bg' in opt:
    bkeep = {l.strip() for l in open(opt['--bg-ids'], encoding='utf-8') if l.strip()} if '--bg-ids' in opt else None
    neg = [r for r in csv.DictReader(open(os.path.join(root, 'manifest.csv'), encoding='utf-8'))
           if r['dataset'] == opt['--bg'] and r['cls'] == 'neg' and (bkeep is None or r['id'] in bkeep)]
sir = sir * int(opt.get('--repeat', 1))
rng.shuffle(sir)
if maxev: sir = sir[:maxev]
print(ds, 'siren', len(sir), 'neg', len(neg))

cache = {}
def load(r):
    if r['id'] not in cache:
        with wave.open(os.path.join(root, '_16k', r['id'])) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768
        cache[r['id']] = x
    return cache[r['id']]

def rms(x):
    # 조용한 앞뒤(−60 dBFS 아래 20 ms 블록)는 빼고 잰다
    b = x[:len(x) // 320 * 320].reshape(-1, 320)
    e = np.sqrt((b ** 2).mean(1) + 1e-12)
    act = e[e > 10 ** (-60 / 20)]
    return float(np.sqrt((act ** 2).mean())) if len(act) else 1e-6

def background(n):
    out = np.zeros(n, np.float32); i = 0; fade = int(0.05 * SR)
    while i < n:
        x = load(neg[rng.integers(len(neg))]).copy()
        x = x / rms(x) * 0.05                     # 배경 기준 크기 −26 dBFS 근처
        if len(x) > 2 * fade:
            x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        k = min(len(x), n - i); out[i:i + k] += x[:k]; i += max(k - fade, 1)
    return out

sos = butter(2, 1500, 'low', fs=SR, output='sos')
od = os.path.join(root, 'streams', sub); os.makedirs(od, exist_ok=True)

def save(name, x):
    x = np.clip(x, -1, 1)
    with wave.open(os.path.join(od, name), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((x * 32767).astype('<i2').tobytes())

# 사건 배치는 SNR 마다 같게(같은 클립·같은 자리) → SNR 만 바뀐다
t = 5.0; plan = []
for r in sir:
    t += rng.uniform(*GAP); d = len(load(r)) / SR
    plan.append(dict(id=r['id'], sub=r['sub'], start=round(t, 3), end=round(t + d, 3), dur=round(d, 3))); t += d
total = int((t + 20) * SR)
bg = background(total)
events = {'dataset': ds if sub == ds else f'{ds}:{sub}', 'seed': seed, 'events': plan, 'files': {}}
if keep is not None: events['ids'] = opt['--ids']
if '--bg' in opt: events['bg'] = opt['--bg'] + (':' + opt['--bg-ids'] if '--bg-ids' in opt else '')
if '--repeat' in opt: events['repeat'] = int(opt['--repeat'])
for snr in SNRS:
    mix = bg.copy()
    for e in plan:
        s = load(next(r for r in sir if r['id'] == e['id']))
        a = int(e['start'] * SR); seg = mix[a:a + len(s)]
        g = rms(seg) / rms(s) * 10 ** (snr / 20)
        mix[a:a + len(s)] += s[:len(seg)] * g
    for cond in ('out', 'cab'):
        y = mix if cond == 'out' else sosfilt(sos, mix).astype(np.float32)
        name = f'{cond}_snr{snr:+d}.wav'; save(name, y); events['files'][name] = dict(cond=cond, snr=snr, dur=round(len(y) / SR, 1))
    print('snr', snr)
nb = background(int(NEG_HOURS * 3600 * SR))
for cond in ('out', 'cab'):
    y = nb if cond == 'out' else sosfilt(sos, nb).astype(np.float32)
    name = f'neg_{cond}.wav'; save(name, y); events['files'][name] = dict(cond=cond, snr=None, dur=round(len(y) / SR, 1))
json.dump(events, open(os.path.join(od, 'events.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('길이(시간)', round(total / SR / 3600, 2), '사건', len(plan))
