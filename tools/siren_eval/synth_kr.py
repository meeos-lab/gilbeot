"""한국 긴급차량 사이렌 패턴을 코드로 합성한다(실제 녹음 아님 — 결과 표에 '합성'으로 표시).
근거(DATA_SOURCES.md 'kr_synth' 절): 한국소방산업기술원 웹진 2020-12 「사이렌, 유별난 악기에서 안전의 파수꾼으로!」,
모터매거진 2024-01-08 「생명을 살리는 구급차 소리…」. 두 글 모두 법 기준이 아니라 설명 자료다(법은 음량만 정함).
  fire_wail  소방차 웨일: 300~750 Hz, 주기 약 5초(두 글)
  police_yelp 경찰차 옐프: 300~750 Hz, 주기 약 1초(모터매거진 '약 1초', 웹진은 주기 없음)
  amb_hilo   구급차 하이로우: 610 Hz·690 Hz 를 1초 간격으로 번갈아(두 글)
근거 없는 것(unknown → 아래처럼 두 갈래로 두거나 가장 단순하게):
  - 파형: sine(기본음만)·harm(홀수 배음 1/n, 4 kHz 까지 — 전자 사이렌의 사각파 구동을 흉내) 두 갈래
  - 쓸기 모양: 직선 주파수 삼각형(올라갔다 내려옴), 하이로우 두 음의 길이: 반반(0.5 s + 0.5 s)
  - 주파수 흔들림·도플러·확성기 특성: 넣지 않음
사용: python -I synth_kr.py <데이터 루트> <종류당 개수> <seed>
  → <루트>/_16k/kr_synth__<종류>_<파형>_<번호>.wav, manifest.csv 에 dataset=kr_synth, cls=siren, sub=<종류>_<파형> 행(있으면 바꿈)
"""
import csv, os, sys, wave
import numpy as np

SR = 16000
PATTERNS = {   # 이름: (f_lo, f_hi, 주기 s, 종류)
    'fire_wail': (300.0, 750.0, 5.0, 'sweep'),
    'police_yelp': (300.0, 750.0, 1.0, 'sweep'),
    'amb_hilo': (610.0, 690.0, 1.0, 'step'),
}
WAVES = ('sine', 'harm')

def freq(kind, lo, hi, per, t):
    ph = (t / per) % 1.0
    if kind == 'sweep':                                     # 0→0.5 오르고 0.5→1 내림(직선)
        return lo + (hi - lo) * (1 - np.abs(2 * ph - 1))
    return np.where(ph < 0.5, hi, lo)                       # 하이로우: 높은 음 먼저(순서 근거 없음)

def tone(f, wave_kind):
    phase = 2 * np.pi * np.cumsum(f) / SR
    if wave_kind == 'sine': return np.sin(phase)
    y = np.zeros_like(phase)
    for k in range(1, 40, 2):                               # 홀수 배음 1/k, 4 kHz 넘는 배음은 뺌(앨리어싱 방지)
        y += np.where(k * f < 4000, np.sin(k * phase) / k, 0)
    return y


def main():
    root, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    rng = np.random.default_rng(seed)
    out = os.path.join(root, '_16k'); os.makedirs(out, exist_ok=True)
    rows = []
    for name, (lo, hi, per, kind) in PATTERNS.items():
        for wk in WAVES:
            for i in range(n):
                dur = rng.uniform(4.0, 10.0)
                t = np.arange(int(dur * SR)) / SR + rng.uniform(0, per)   # 주기 안 아무 자리에서 시작
                y = tone(freq(kind, lo, hi, per, t), wk)
                y = y / np.sqrt((y ** 2).mean()) * 0.1                       # −20 dBFS RMS(스트림에서 SNR 로 다시 맞춘다)
                fade = int(0.05 * SR); y[:fade] *= np.linspace(0, 1, fade); y[-fade:] *= np.linspace(1, 0, fade)
                fid = f'kr_synth__{name}_{wk}_{i:03d}.wav'
                with wave.open(os.path.join(out, fid), 'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
                    w.writeframes((np.clip(y, -1, 1) * 32767).astype('<i2').tobytes())
                rows.append(dict(id=fid, dataset='kr_synth', cls='siren', sub=f'{name}_{wk}', src=f'synth_kr.py seed={seed}', dur=round(dur, 3)))

    mp = os.path.join(root, 'manifest.csv')
    old = [r for r in csv.DictReader(open(mp, encoding='utf-8')) if r['dataset'] != 'kr_synth']
    with open(mp, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'dataset', 'cls', 'sub', 'src', 'dur']); w.writeheader(); w.writerows(old + rows)
    print('kr_synth', len(rows))


if __name__ == '__main__':
    main()
