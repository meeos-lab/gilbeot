"""차 안 조건 평가 스트림(2026-11-06): 차체 차음 필터 + 주행 실내 소음을 거쳐 들리는 사이렌을 만든다.
streams.py 의 'cab'(1.5 kHz 2차 저역 통과, 실측 아님)을 대신하는 자리. 출처·읽은 값은 DATA_SOURCES.md '차 안 조건' 절.

조건(파일 이름):
  out_clean          사이렌만(차 밖, 소음 없음, −26 dBFS)
  out_snr<±dB>       차 밖: 사이렌 + 실녹음 도로 소음(LSSiren 시험 절반; 속도 표기 없는 자료라 60/100 을 가르지 못함)
  cab_clean          차 안 필터만 거친 사이렌(−26 dBFS 로 다시 맞춤 — 마이크 이득은 unknown 이라 음색 차이만 본다)
  cab60_snr<±dB>     차 안: 필터 거친 사이렌 + 60 km/h 실내 소음(합성, 스펙트럼 모양만 출처)
  cab100_snr<±dB>    차 안: 필터 거친 사이렌 + 100 km/h 실내 소음(출처는 90 km/h 측정 — 가장 가까운 공개 값, 그대로 씀)
  neg_out / neg_cab60 / neg_cab100   사건 없는 배경 1시간(오경보용)
SNR 은 **A 가중 RMS** 비(사이렌 : 그 자리 배경). 실내 소음은 저주파가 세서 가중 없이 재면 0 dB 가 실제보다 쉬운 조건이 된다.
  (streams.py 의 기존 표는 가중 없는 RMS 비라 '0 dB' 가 같은 뜻이 아니다 — README 참고.)

차 안 필터: Howard 2011(Acoustics Australia 39(2)) 그림 4 "Noise reduction of an average passenger vehicle"
  — 2005 Mitsubishi Magna 왜건, 문·창 닫음, 백색소음 스피커 3곳(앞·옆·뒤, 4.2 m), 운전석 마이크, 1/3 옥타브.
  세 위치 평균을 그래프에서 읽음(±2 dB). 25 Hz 아래·8 kHz 위는 끝값 유지. 선형 위상 FIR(firwin2).
실내 소음: Staneva·Ivanov·Kadikyanov 2023(Transport Problems 18(2), DOI 10.20858/tp.2023.18.2.06)
  그림 19(60 km/h)·그림 21(90 km/h), 매끈한 아스팔트, GV(Nissan Qashqai 1.6 DIG-T), 옥타브 대역 dB(가중 없음), 그래프에서 읽음(±1 dB).
  4~16 kHz 값(38~43 dB)은 속도와 무관하게 같아 측정기 바닥으로 보이나 읽은 대로 둔다(고음 소음이 조금 과하게 들어가는 쪽 = 보수적).
  백색 가우스 잡음을 이 옥타브 모양의 FIR 로 물들인 정상(stationary) 잡음 — 바람·엔진 변동·음악·대화는 없다.

사용: python -I cabin_streams.py <데이터 루트> <dataset> <최대 사건 수|0=전부> <seed> [--ids ..] [--name ..] [--bg .. --bg-ids ..] [--repeat N] [--int-hf read|slope]
  (인자는 streams.py 와 같다) → <루트>/streams/<name>/ 에 wav + events.json
  --int-hf slope: 실내 소음 4·8 kHz 값을 1→2 kHz 기울기로 외삽(그래프의 고음 바닥이 결과를 좌우하는지 보는 민감도 확인)
"""
import csv, json, os, sys, wave
import numpy as np
from scipy.signal import firwin2, fftconvolve

root, ds, maxev, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
opt = dict(zip(sys.argv[5::2], sys.argv[6::2]))
assert set(opt) <= {'--ids', '--name', '--bg', '--bg-ids', '--repeat', '--int-hf'} and len(sys.argv[5:]) % 2 == 0, sys.argv[5:]
INT_HF = opt.get('--int-hf', 'read')     # read = 그래프 값 그대로 | slope = 4·8 kHz 를 1→2 kHz 기울기로 외삽(측정기 바닥 의심 → 민감도 확인용)
assert INT_HF in ('read', 'slope'), INT_HF
keep = {l.strip() for l in open(opt['--ids'], encoding='utf-8') if l.strip()} if '--ids' in opt else None
sub = opt.get('--name', ds)
SR = 16000
SNRS = [10, 0, -5]
GAP = (15.0, 30.0)
NEG_HOURS = 1.0
BG_RMS = 0.05                # 배경 기준 크기 −26 dBFS(가중 없음) — streams.py 와 같게
NTAPS = 2047
rng = np.random.default_rng(seed)

# --- 출처 값(그래프에서 읽음) ---------------------------------------------------------------
# Howard 2011 그림 4, 1/3 옥타브 중심 주파수(Hz): 소음 저감(dB), Rear/Adjacent/Front 세 위치 평균
NR_CABIN = {25: 7, 31.5: 8, 40: 3, 50: 5, 63: 10, 80: 14, 100: 17, 125: 15, 160: 15, 200: 17, 250: 22, 315: 23, 400: 20,
            500: 27, 630: 30, 800: 31, 1000: 36, 1250: 38, 1600: 33, 2000: 32, 2500: 35, 3150: 31, 4000: 38, 5000: 34, 6300: 34, 8000: 35}
# Staneva 2023 그림 19(60 km/h)·그림 21(90 km/h) GV, 옥타브 대역 레벨(dB)
INT_NOISE = {
    'cab60': {31.5: 40, 63: 47, 125: 48, 250: 49, 500: 48, 1000: 47, 2000: 43, 4000: 38, 8000: 41},
    'cab100': {31.5: 42, 63: 46, 125: 48, 250: 54, 500: 52, 1000: 52, 2000: 42, 4000: 38, 8000: 41},   # 90 km/h 측정값
}


def fir_from_db(points_db, ntaps=NTAPS):
    """log-주파수로 보간한 dB 곡선 → 선형 위상 FIR. points_db: {Hz: dB(이득)}."""
    f = np.array(sorted(points_db)); g = np.array([points_db[k] for k in f])
    grid = np.linspace(0, SR / 2, 4097)
    gl = np.interp(np.log(np.maximum(grid, 1.0)), np.log(f), g, left=g[0], right=g[-1])
    return firwin2(ntaps, grid, 10 ** (gl / 20), fs=SR)


def apply_fir(x, h):
    y = fftconvolve(x, h)[(len(h) - 1) // 2:][:len(x)]      # 선형 위상 → 군지연만큼 당김
    return y.astype(np.float32)


if INT_HF == 'slope':
    for tab in INT_NOISE.values():
        for fc in (4000, 8000): tab[fc] = round(tab[2000] + (tab[2000] - tab[1000]) * np.log2(fc / 2000), 1)
    print('int-hf slope:', {k: {f: v[f] for f in (2000, 4000, 8000)} for k, v in INT_NOISE.items()})
H_CAB = fir_from_db({k: -v for k, v in NR_CABIN.items()})
# 옥타브 대역 레벨 → 1 Hz 당 밀도(대역폭 0.707·fc 로 나눔) 모양의 FIR(절대 크기는 뒤에서 맞춘다)
H_INT = {k: fir_from_db({fc: L - 10 * np.log10(0.7071 * fc) for fc, L in v.items()}) for k, v in INT_NOISE.items()}

def a_weight(x):
    """A 가중(IEC 61672 식)을 FFT 로 적용한 파형."""
    f = np.fft.rfftfreq(len(x), 1 / SR); f2 = f ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194.0 ** 2) + 1e-30)
    f1k = 1000.0 ** 2
    ra1k = (12194.0 ** 2 * f1k ** 2) / ((f1k + 20.6 ** 2) * np.sqrt((f1k + 107.7 ** 2) * (f1k + 737.9 ** 2)) * (f1k + 12194.0 ** 2))
    return np.fft.irfft(np.fft.rfft(x) * (ra / ra1k), n=len(x)).astype(np.float32)


def rms(x):
    """조용한 앞뒤(−60 dBFS 아래 20 ms 블록)는 빼고 잰다(streams.py 와 같음)."""
    b = x[:len(x) // 320 * 320].reshape(-1, 320)
    e = np.sqrt((b ** 2).mean(1) + 1e-12)
    act = e[e > 10 ** (-60 / 20)]
    return float(np.sqrt((act ** 2).mean())) if len(act) else 1e-6


def rms_a(x):
    return rms(a_weight(x))


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


def background_road(n):
    out = np.zeros(n, np.float32); i = 0; fade = int(0.05 * SR)
    while i < n:
        x = load(neg[rng.integers(len(neg))]).copy()
        x = x / rms(x) * BG_RMS
        if len(x) > 2 * fade:
            x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        k = min(len(x), n - i); out[i:i + k] += x[:k]; i += max(k - fade, 1)
    return out


def background_cabin(n, kind):
    x = apply_fir(rng.standard_normal(n).astype(np.float32), H_INT[kind])
    return (x / rms(x) * BG_RMS).astype(np.float32)


od = os.path.join(root, 'streams', sub); os.makedirs(od, exist_ok=True)

def save(name, x):
    x = np.clip(x, -1, 1)
    with wave.open(os.path.join(od, name), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((x * 32767).astype('<i2').tobytes())

# 사건 배치는 모든 조건에서 같게(같은 클립·같은 자리)
t = 5.0; plan = []
for r in sir:
    t += rng.uniform(*GAP); d = len(load(r)) / SR
    plan.append(dict(id=r['id'], sub=r['sub'], start=round(t, 3), end=round(t + d, 3), dur=round(d, 3))); t += d
total = int((t + 20) * SR)
events = {'dataset': ds if sub == ds else f'{ds}:{sub}', 'seed': seed, 'events': plan, 'files': {}, 'snr': 'A-weighted',
          'cabin_filter': 'Howard2011_fig4_mean3pos', 'cabin_noise': 'Staneva2023_fig19_fig21_GV_smooth', 'int_hf': INT_HF}
if keep is not None: events['ids'] = opt['--ids']
if '--bg' in opt: events['bg'] = opt['--bg'] + (':' + opt['--bg-ids'] if '--bg-ids' in opt else '')
if '--repeat' in opt: events['repeat'] = int(opt['--repeat'])

sir_by_id = {r['id']: r for r in sir}
cab_cache = {}
def siren_cab(eid):
    if eid not in cab_cache: cab_cache[eid] = apply_fir(load(sir_by_id[eid]), H_CAB)
    return cab_cache[eid]


def build(cond, bg, snr):
    """cond: out|cab|cab60|cab100. bg: 배경(없으면 None → clean, 사이렌을 −26 dBFS 로)."""
    mix = bg.copy() if bg is not None else np.zeros(total, np.float32)
    for e in plan:
        s = load(sir_by_id[e['id']]) if cond == 'out' else siren_cab(e['id'])
        a = int(e['start'] * SR); seg = mix[a:a + len(s)]
        g = (rms_a(seg) / rms_a(s) * 10 ** (snr / 20)) if bg is not None else (BG_RMS / rms(s))
        mix[a:a + len(s)] += s[:len(seg)] * g
    return mix


save('out_clean.wav', build('out', None, None)); events['files']['out_clean.wav'] = dict(cond='out', snr=99, dur=round(total / SR, 1))
save('cab_clean.wav', build('cab', None, None)); events['files']['cab_clean.wav'] = dict(cond='cab', snr=99, dur=round(total / SR, 1))
print('clean')
bg_road = background_road(total)
for snr in SNRS:
    name = f'out_snr{snr:+d}.wav'; save(name, build('out', bg_road, snr)); events['files'][name] = dict(cond='out', snr=snr, dur=round(total / SR, 1))
print('out')
for kind in ('cab60', 'cab100'):
    bg = background_cabin(total, kind)
    for snr in SNRS:
        name = f'{kind}_snr{snr:+d}.wav'; save(name, build(kind, bg, snr)); events['files'][name] = dict(cond=kind, snr=snr, dur=round(total / SR, 1))
    print(kind)
nb = int(NEG_HOURS * 3600 * SR)
save('neg_out.wav', background_road(nb)); events['files']['neg_out.wav'] = dict(cond='out', snr=None, dur=round(nb / SR, 1))
for kind in ('cab60', 'cab100'):
    save(f'neg_{kind}.wav', background_cabin(nb, kind)); events['files'][f'neg_{kind}.wav'] = dict(cond=kind, snr=None, dur=round(nb / SR, 1))
json.dump(events, open(os.path.join(od, 'events.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('길이(시간)', round(total / SR / 3600, 2), '사건', len(plan))
