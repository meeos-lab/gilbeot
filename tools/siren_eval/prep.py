"""공개 사이렌 데이터셋 zip → 16 kHz 모노 16 bit wav + manifest.csv.
사용: python -I prep.py <데이터 루트(datasets/siren)>
- scidata2022: Scientific Data 2022(파키스탄, CC0) sirens.zip / road.zip
- sirennet: sireNNet(Mendeley 2023, CC BY 4.0) sireNNet.zip — 인터넷 수집 + 증강본 섞임 → dev(문턱 고르기)용
압축은 풀지 않고 zip 안에서 바로 읽어 ffmpeg 로 바꾼다(내려받은 파일을 실행하지 않음).
"""
import csv, io, os, subprocess, sys, zipfile, wave

root = sys.argv[1]
out_dir = os.path.join(root, '_16k')
os.makedirs(out_dir, exist_ok=True)

SOURCES = [
    ('scidata2022', 'scidata2022/sirens.zip'),
    ('scidata2022', 'scidata2022/road.zip'),
    ('sirennet', 'sirennet/sireNNet.zip'),
]

def label(path):
    p = path.lower()
    for k, sub in (('ambulance', 'ambulance'), ('police', 'police'), ('fire', 'firetruck')):
        if k in p: return 'siren', sub
    if 'road' in p or 'traffic' in p: return 'neg', 'road'
    return None, None

rows = []
for ds, rel in SOURCES:
    zp = os.path.join(root, rel)
    if not os.path.exists(zp): print('없음', zp); continue
    z = zipfile.ZipFile(zp)
    names = [n for n in z.namelist() if n.lower().endswith(('.wav', '.mp3', '.flac', '.ogg'))]
    print(ds, rel, len(names))
    for i, n in enumerate(names):
        cls, sub = label(n)
        if cls is None: print('라벨 모름', n); continue
        safe = f"{ds}__{n.replace('/', '__').replace(' ', '_')}"
        safe = os.path.splitext(safe)[0] + '.wav'
        dst = os.path.join(out_dir, safe)
        if not os.path.exists(dst):
            data = z.read(n)
            r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', 'pipe:0', '-ac', '1', '-ar', '16000', '-sample_fmt', 's16', '-map_metadata', '-1', '-fflags', '+bitexact', dst],
                               input=data, capture_output=True)
            if r.returncode != 0: print('변환 실패', n, r.stderr[:200]); continue
        with wave.open(dst) as w: dur = w.getnframes() / w.getframerate()
        rows.append(dict(id=safe, dataset=ds, cls=cls, sub=sub, src=n, dur=round(dur, 3)))
        if (i + 1) % 200 == 0: print(' ', i + 1)

with open(os.path.join(root, 'manifest.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['id', 'dataset', 'cls', 'sub', 'src', 'dur']); w.writeheader(); w.writerows(rows)
print('manifest', len(rows))
