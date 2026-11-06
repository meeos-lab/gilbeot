"""낱개 음원(권리 확인된 A칸 등)을 16 kHz 모노 16 bit 로 바꿔 manifest.csv 에 더한다(같은 id 가 있으면 바꿈).
사용: python -I prep_extra.py <데이터 루트> <dataset> <cls: siren|neg> <sub> <원본 파일> [sha256]
  sha256 을 주면 원본 해시가 같은지 먼저 확인한다(출처 기록의 해시와 같은 파일인지).
"""
import csv, hashlib, os, subprocess, sys, wave

def main():
    root, ds, cls, sub, src = sys.argv[1:6]
    want = sys.argv[6] if len(sys.argv) > 6 else None
    assert cls in ('siren', 'neg'), cls
    if want:
        got = hashlib.sha256(open(src, 'rb').read()).hexdigest()
        assert got == want, f'sha256 다름: {got}'
    fid = f'{ds}__{os.path.splitext(os.path.basename(src))[0]}.wav'
    dst = os.path.join(root, '_16k', fid)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-ac', '1', '-ar', '16000', '-sample_fmt', 's16', dst], check=True)
    with wave.open(dst) as w: dur = w.getnframes() / w.getframerate()
    mp = os.path.join(root, 'manifest.csv')
    rows = [r for r in csv.DictReader(open(mp, encoding='utf-8')) if r['id'] != fid]
    rows.append(dict(id=fid, dataset=ds, cls=cls, sub=sub, src=os.path.basename(src), dur=round(dur, 3)))
    with open(mp, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'dataset', 'cls', 'sub', 'src', 'dur']); w.writeheader(); w.writerows(rows)
    print(fid, round(dur, 2), 's')


if __name__ == '__main__':
    main()
