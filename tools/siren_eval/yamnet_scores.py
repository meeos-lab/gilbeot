"""YAMNet(AudioSet 521종, TFLite 분류판)으로 스트림의 사이렌 점수를 0.48초마다 낸다.
점수 = 사이렌 관련 6종(Emergency vehicle, Police car/Ambulance/Fire engine (siren), Siren, Civil defense siren) 중 최댓값.
사용: python -I yamnet_scores.py <모델.tflite> <class_map.csv> <wav...>  → wav 옆에 <이름>.yamnet.npy (열: 시각 끝(s), 점수)
"""
import csv, sys, wave
import numpy as np
from ai_edge_litert.interpreter import Interpreter

model, cmap, wavs = sys.argv[1], sys.argv[2], sys.argv[3:]
names = [r['display_name'] for r in csv.DictReader(open(cmap, encoding='utf-8'))]
KEEP = [i for i, n in enumerate(names) if n in ('Emergency vehicle', 'Police car (siren)', 'Ambulance (siren)', 'Fire engine, fire truck (siren)', 'Siren', 'Civil defense siren')]
assert len(KEEP) == 6, KEEP
it = Interpreter(model, num_threads=4); it.allocate_tensors()
inp = it.get_input_details()[0]['index']; out = it.get_output_details()[0]['index']
WIN, HOP, SR = 15600, 7680, 16000
for p in wavs:
    with wave.open(p) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        x = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768
    res = []
    for a in range(0, len(x) - WIN + 1, HOP):
        it.set_tensor(inp, x[a:a + WIN]); it.invoke()
        s = it.get_tensor(out)[0]
        res.append(((a + WIN) / SR, float(s[KEEP].max())))
    np.save(p[:-4] + '.yamnet.npy', np.array(res, np.float32))
    print(p, len(res))
