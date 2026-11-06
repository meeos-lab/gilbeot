"""YAMNet 임베딩(1024차원) 위에 작은 사이렌/아님 머리(로지스틱 회귀 또는 은닉층 하나 MLP)를 학습·적용한다.
모델: TF Hub lite-model/yamnet/tflite/1(출력 3개: 점수 521·임베딩 1024·log-mel, float32 16 MB) → datasets/siren/models/yamnet_emb.tflite
창 0.96 s(15600 표본), 홉 0.48 s(7680) — yamnet_scores.py 와 같은 틀(시각 = 창 끝).

하위 명령(전부 python -I 로):
  split   <루트> <seed>                       분할 목록 → <루트>/splits/*.txt
            sn_fit/sn_dev : sireNNet 80/20(증강본 sound_N_k 는 원본 sound_N 과 같은 묶음)
            sd_test/sd_train : scidata 50/50(클립 id, 사이렌·도로 따로) · sd_fit/sd_dev : sd_train 을 다시 80/20
  embed   <모델> <wav...> [--jobs N]          스트림 wav → <이름>.emb.npy(float16, 행 = 창)
  trainset <루트> <모델> <out.npz> <목록.txt...> [--seed S] [--jobs N]
            목록의 클립(사이렌=1, 도로=0)을 증강해 임베딩: 깨끗(밖)·깨끗(차 안 1.5 kHz 2차 저역)·
            같은 목록의 도로 소음에 SNR U(−15,+6) dB 로 섞은 것 4개(밖/차 안 무작위). 클립당 변형마다 창 최대 16개.
  fit     <train.npz> <out.json> <lr:λ|lrp:λ|mlp:H:λ> [--seed S]   표준화 + 클래스 균형 로그 손실
            --min-snr S : 섞은 SNR < S dB 인 양성 창 빼기 · --neg-yam T : YAMNet 사이렌 점수 ≥ T 인 학습 쪽 도로 클립 빼기
            --threshold-from <dev json> : pick 으로 dev 모델에 채운 문턱을 최종 모델 json 에 옮김
            lrp = L2 를 0 대신 YAMNet 자신의 사이렌 6종 분류 가중치(평균) 쪽으로 당긴 로지스틱 회귀
  apply   <head.json> <emb.npy...>             → <이름>.head.npy(열: 시각 끝(s), 확률) — score.py 가 읽는다
  pick    <head.json> <dev 스트림 폴더...> [--key head|yamnet] [--fa 1.0]   (배경 켜짐 시간 > 1 % 인 문턱은 탈락)
            dev 스트림을 score.py 로 채점해 문턱을 고른다: neg_out·neg_cab 오경보 ≤ fa/h 인 문턱 중
            out/cab SNR +6·0·−6 평균 검출이 가장 높은 것(같으면 높은 문턱). head 면 json 의 threshold 를 채운다.
"""
import csv, json, os, subprocess, sys, wave, hashlib
import numpy as np

SR, WIN, HOP = 16000, 15600, 7680
HERE = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding='utf-8')

def opts(args, flags):
    pos, kw, i = [], {}, 0
    while i < len(args):
        if args[i] in flags: kw[args[i]] = args[i + 1]; i += 2
        else: pos.append(args[i]); i += 1
    return pos, kw

# ---------- 공통 ----------
_it = None
def _init(model):
    global _it
    from ai_edge_litert.interpreter import Interpreter
    _it = Interpreter(model, num_threads=1)
    _it.resize_tensor_input(_it.get_input_details()[0]['index'], [WIN]); _it.allocate_tensors()
    _it._emb = next(d['index'] for d in _it.get_output_details() if list(d['shape'][-1:]) == [1024])
    _it._inp = _it.get_input_details()[0]['index']
    _it._sc = next(d['index'] for d in _it.get_output_details() if list(d['shape'][-1:]) == [521])

def _siren_score(x):
    """클립의 YAMNet 사이렌 점수(6종 최댓값)의 창 최댓값 — 학습 쪽 음성 클립 거르기용"""
    import csv as _c
    if not hasattr(_it, '_keep'):
        names = [r['display_name'] for r in _c.DictReader(open(os.path.join(os.path.dirname(_W['model']), 'yamnet_class_map.csv'), encoding='utf-8'))]
        _it._keep = [i for i, n in enumerate(names) if n in SIREN6]
    m = 0.0
    for a in range(0, len(x) - WIN + 1, HOP):
        _it.set_tensor(_it._inp, np.ascontiguousarray(x[a:a + WIN], np.float32)); _it.invoke()
        m = max(m, float(_it.get_tensor(_it._sc).reshape(-1)[_it._keep].max()))
    return m

def _embed(x):
    """x: float32 파형 → [창 수, 1024] float32"""
    out = []
    for a in range(0, len(x) - WIN + 1, HOP):
        _it.set_tensor(_it._inp, np.ascontiguousarray(x[a:a + WIN], np.float32)); _it.invoke()
        out.append(_it.get_tensor(_it._emb).reshape(-1).copy())
    return np.array(out, np.float32).reshape(-1, 1024)

def read_wav(p, a=0, n=None):
    with wave.open(p) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        w.setpos(a); n = w.getnframes() - a if n is None else n
        return np.frombuffer(w.readframes(n), '<i2').astype(np.float32) / 32768

def rms(x):  # streams.py 와 같게: −60 dBFS 아래 20 ms 블록은 뺀다
    b = x[:len(x) // 320 * 320].reshape(-1, 320)
    e = np.sqrt((b ** 2).mean(1) + 1e-12)
    act = e[e > 10 ** (-60 / 20)]
    return float(np.sqrt((act ** 2).mean())) if len(act) else 1e-6

def manifest(root):
    return {r['id']: r for r in csv.DictReader(open(os.path.join(root, 'manifest.csv'), encoding='utf-8'))}

# ---------- split ----------
def cmd_split(root, seed):
    import re
    seed = int(seed); M = manifest(root); od = os.path.join(root, 'splits'); os.makedirs(od, exist_ok=True)
    def write(name, ids):
        open(os.path.join(od, name + '.txt'), 'w', encoding='utf-8', newline='\n').write('\n'.join(sorted(ids)) + '\n')
        print(name, len(ids), {c: sum(1 for i in ids if M[i]['cls'] == c) for c in ('siren', 'neg')})
    rng = np.random.default_rng(seed)
    # sireNNet: 증강본(sound_54_1)은 원본(sound_54)과 같은 묶음으로
    sn_fit, sn_dev = [], []
    for cls in ('siren', 'neg'):
        ids = sorted(i for i, r in M.items() if r['dataset'] == 'sirennet' and r['cls'] == cls)
        grp = lambda i: re.sub(r'(sound_\d+)_\d+\.wav$', r'\1.wav', M[i]['src'].split('/', 1)[-1])
        gs = sorted({grp(i) for i in ids}); rng.shuffle(gs); dev = set(gs[:len(gs) // 5])
        for i in ids: (sn_dev if grp(i) in dev else sn_fit).append(i)
    write('sn_fit', sn_fit); write('sn_dev', sn_dev)
    sd_test, sd_fit, sd_dev = [], [], []
    for cls in ('siren', 'neg'):
        ids = sorted(i for i, r in M.items() if r['dataset'] == 'scidata2022' and r['cls'] == cls); rng.shuffle(ids)
        h = len(ids) // 2; sd_test += ids[:h]; tr = ids[h:]
        sd_dev += tr[:len(tr) // 5]; sd_fit += tr[len(tr) // 5:]
    write('sd_test', sd_test); write('sd_train', sd_fit + sd_dev); write('sd_fit', sd_fit); write('sd_dev', sd_dev)

# ---------- embed (스트림) ----------
def _emb_chunk(t):
    p, a, n = t
    return p, a, _embed(read_wav(p, a, n + WIN - HOP)).astype(np.float16)

def cmd_embed(model, wavs, jobs):
    from multiprocessing import Pool
    tasks, nfr = [], {}
    for p in wavs:
        with wave.open(p) as w: L = w.getnframes()
        nfr[p] = (L - WIN) // HOP + 1
        for f0 in range(0, nfr[p], 2000):
            f1 = min(nfr[p], f0 + 2000); tasks.append((p, f0 * HOP, (f1 - f0) * HOP))
    out = {p: np.zeros((nfr[p], 1024), np.float16) for p in wavs}
    with Pool(jobs, _init, (model,)) as pool:
        for k, (p, a, e) in enumerate(pool.imap_unordered(_emb_chunk, tasks)):
            out[p][a // HOP:a // HOP + len(e)] = e
            if (k + 1) % 50 == 0: print(' ', k + 1, '/', len(tasks), flush=True)
    for p in wavs:
        np.save(p[:-4] + '.emb.npy', out[p]); print(p, out[p].shape)

# ---------- trainset (클립 증강) ----------
_W = {}
def _tinit(model, root, noise_ids, seed):
    _init(model); _W.update(root=root, noise=noise_ids, seed=seed, cache={}, model=model)
    from scipy.signal import butter
    _W['sos'] = butter(2, 1500, 'low', fs=SR, output='sos')

def _load(i):
    c = _W['cache']
    if i not in c:
        if len(c) > 400: c.clear()
        c[i] = read_wav(os.path.join(_W['root'], '_16k', i))
    return c[i]

def _noise(n, rng, avoid):
    out = np.zeros(n, np.float32); i = 0; fade = int(0.05 * SR); pool = _W['noise']
    while i < n:
        j = pool[rng.integers(len(pool))]
        if j == avoid and len(pool) > 1: continue
        x = _load(j).copy(); x = x / rms(x) * 0.05
        if len(x) > 2 * fade: x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
        k = min(len(x), n - i); out[i:i + k] += x[:k]; i += max(k - fade, 1)
    return out

def _aug_clip(t):
    k, cid, lab = t
    from scipy.signal import sosfilt
    rng = np.random.default_rng([_W['seed'], k])
    x = _load(cid)
    if len(x) < WIN: return k, np.zeros((0, 1024), np.float16), lab, np.zeros(0, np.float32), 0.0
    embs, snrs = [], []
    ys = _siren_score(x / rms(x) * 0.05)
    for v in range(6):
        if v < 2:
            y = x / rms(x) * 0.05 * 10 ** (rng.uniform(-6, 12) / 20); cab = v == 1; snr = 99.0
        else:
            snr = rng.uniform(-15, 6)
            nz = _noise(len(x), rng, cid); y = nz + x * (rms(nz) / rms(x) * 10 ** (snr / 20))
            cab = rng.random() < 0.5
        if cab: y = sosfilt(_W['sos'], y).astype(np.float32)
        y = np.clip(y, -1, 1)
        nf = (len(y) - WIN) // HOP + 1
        starts = np.arange(nf) * HOP
        if nf > 16: starts = np.sort(rng.choice(starts, 16, replace=False))
        e = np.concatenate([_embed(y[a:a + WIN]) for a in starts])
        embs.append(e.astype(np.float16)); snrs.append(np.full(len(e), snr, np.float32))
    return k, np.concatenate(embs), lab, np.concatenate(snrs), ys

def cmd_trainset(root, model, out, lists, seed, jobs):
    from multiprocessing import Pool
    M = manifest(root)
    ids = sorted({l.strip() for f in lists for l in open(f, encoding='utf-8') if l.strip()})
    noise = [i for i in ids if M[i]['cls'] == 'neg']
    tasks = [(k, i, int(M[i]['cls'] == 'siren')) for k, i in enumerate(ids)]
    print('클립', len(ids), '사이렌', sum(t[2] for t in tasks), '도로(소음 풀)', len(noise), flush=True)
    X, y, g, sn, yc = [], [], [], [], np.zeros(len(ids), np.float32)
    with Pool(jobs, _tinit, (model, root, noise, int(seed))) as pool:
        for n, (k, e, lab, s_, ys) in enumerate(pool.imap_unordered(_aug_clip, tasks, chunksize=8)):
            X.append(e); y.append(np.full(len(e), lab, np.int8)); g.append(np.full(len(e), k, np.int32)); sn.append(s_); yc[k] = ys
            if (n + 1) % 500 == 0: print(' ', n + 1, '/', len(tasks), flush=True)
    X, y, g, sn = np.concatenate(X), np.concatenate(y), np.concatenate(g), np.concatenate(sn)
    # snr: 창마다 섞은 SNR(깨끗 = 99) · yam_clip: 클립별 YAMNet 사이렌 점수 최댓값(fit --neg-yam 으로 '사이렌 섞인 도로' 음성 거르기)
    np.savez(out, X=X, y=y, g=g, snr=sn, yam_clip=yc, ids=np.array(ids), lists=np.array([os.path.basename(f) for f in lists]))
    print(out, X.shape, '양성 창', int(y.sum()), '음성 창', int((1 - y).sum()))

# ---------- fit ----------
def sig(z): return 1 / (1 + np.exp(-np.clip(z, -30, 30)))

SIREN6 = ('Emergency vehicle', 'Police car (siren)', 'Ambulance (siren)', 'Fire engine, fire truck (siren)', 'Siren', 'Civil defense siren')

def yamnet_dense(model):
    """YAMNet 마지막 dense(1024→521) 중 사이렌 6종 행. 점수 = sigmoid(W·e + b) 와 맞는지 확인했다(오차 < 1e-7)."""
    from ai_edge_litert.interpreter import Interpreter
    it = Interpreter(model); it.allocate_tensors()
    td = it.get_tensor_details()
    W = next(it.get_tensor(d['index']) for d in td if 'dense_1/MatMul' in d['name'] and list(d['shape']) == [521, 1024])
    b = next(it.get_tensor(d['index']) for d in td if list(d['shape']) == [521] and d['dtype'] == np.float32)
    names = [r['display_name'] for r in csv.DictReader(open(os.path.join(os.path.dirname(model), 'yamnet_class_map.csv'), encoding='utf-8'))]
    keep = [i for i, n in enumerate(names) if n in SIREN6]; assert len(keep) == 6
    return W[keep].astype(np.float64), b[keep].astype(np.float64)

def cmd_fit(npz, out, spec, seed, min_snr=None, neg_yam=None, th_from=None):
    d = np.load(npz); X = d['X'].astype(np.float32); y = d['y'].astype(np.float32)
    keep = np.ones(len(y), bool)
    if min_snr is not None: keep &= (y == 0) | (d['snr'] >= float(min_snr))           # 너무 묻힌 양성 창은 뺀다
    if neg_yam is not None: keep &= (y == 1) | (d['yam_clip'][d['g']] < float(neg_yam))  # 사이렌이 들린다고 YAMNet 이 본 '도로' 클립은 뺀다
    if not keep.all():
        print('거름: 양성', int(((y == 1) & ~keep).sum()), '음성', int(((y == 0) & ~keep).sum()), '/', len(y), '창')
        X, y = X[keep], y[keep]
    mu = X.mean(0); sd = X.std(0) + 1e-3; Z = (X - mu) / sd
    wt = np.where(y == 1, 0.5 / y.mean(), 0.5 / (1 - y.mean())).astype(np.float32)   # 클래스 균형
    parts = spec.split(':'); kind = parts[0]; rng = np.random.default_rng(int(seed))
    head = dict(kind=kind)
    if kind in ('lr', 'lrp'):
        # lr : L2 를 0 쪽으로. lrp : L2 를 YAMNet 자신의 사이렌 분류 가중치(마지막 dense 의 사이렌 6종 행 평균) 쪽으로 —
        #      λ→∞ 이면 YAMNet 사이렌 점수(6종 로짓 평균)와 같고, λ 가 작을수록 학습 데이터에 맞춘다. 저장 형식은 lr 과 같다.
        from scipy.optimize import minimize
        lam = float(parts[1]); w0 = np.zeros(Z.shape[1]); b0 = 0.0
        if kind == 'lrp':
            Wd, bd = yamnet_dense(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(npz))), 'models', 'yamnet_emb.tflite'))
            wr, br = Wd.mean(0), float(bd.mean())
            w0 = (wr * sd).astype(np.float64); b0 = br + float(wr @ mu)   # 표준화 공간으로 옮김
        def f(p):
            w, b = p[:-1], p[-1]; z = Z @ w + b; q = sig(z); dw = w - w0
            l = np.sum(wt * (np.logaddexp(0, z) - y * z)) / len(y) + lam * 0.5 * dw @ dw
            gz = wt * (q - y) / len(y)
            return l, np.concatenate([Z.T @ gz + lam * dw, [gz.sum()]])
        r = minimize(f, np.r_[w0, b0], jac=True, method='L-BFGS-B', options=dict(maxiter=500))
        head.update(kind='lr', w=r.x[:-1].tolist(), b=float(r.x[-1]), lam=lam, prior='yamnet_siren6_mean' if kind == 'lrp' else None)
        print(kind, r.message, 'loss', r.fun, '|w-w0|', float(np.linalg.norm(r.x[:-1] - w0)), '|w0|', float(np.linalg.norm(w0)))
        prob = sig(Z @ r.x[:-1] + r.x[-1])
    elif kind == 'mlp':
        H, lam = int(parts[1]), float(parts[2])
        W1 = rng.normal(0, np.sqrt(2 / 1024), (1024, H)).astype(np.float32); b1 = np.zeros(H, np.float32)
        w2 = rng.normal(0, np.sqrt(1 / H), H).astype(np.float32); b2 = np.float32(0)
        P = [W1, b1, w2, np.array([b2])]; m = [np.zeros_like(p) for p in P]; v = [np.zeros_like(p) for p in P]
        lr, bs, t = 1e-3, 512, 0
        for ep in range(30):
            idx = rng.permutation(len(y))
            for s in range(0, len(y), bs):
                j = idx[s:s + bs]; z1 = Z[j] @ P[0] + P[1]; h = np.maximum(z1, 0); z = h @ P[2] + P[3][0]
                gz = wt[j] * (sig(z) - y[j]) / len(j)
                gw2 = h.T @ gz + lam * P[2]; gb2 = np.array([gz.sum()])
                gh = np.outer(gz, P[2]) * (z1 > 0)
                gW1 = Z[j].T @ gh + lam * P[0]; gb1 = gh.sum(0)
                t += 1
                for p, gr, mm, vv in zip(P, (gW1, gb1, gw2, gb2), m, v):
                    mm *= 0.9; mm += 0.1 * gr; vv *= 0.999; vv += 0.001 * gr * gr
                    p -= lr * (mm / (1 - 0.9 ** t)) / (np.sqrt(vv / (1 - 0.999 ** t)) + 1e-8)
        head.update(W1=P[0].tolist(), b1=P[1].tolist(), w=P[2].tolist(), b=float(P[3][0]), hidden=H, lam=lam)
        prob = sig(np.maximum(Z @ P[0] + P[1], 0) @ P[2] + P[3][0])
    else: raise SystemExit(spec)
    acc = ((prob > 0.5) == (y == 1)).mean()
    print('학습 창 정확도', round(float(acc), 4), '양성 평균 p', round(float(prob[y == 1].mean()), 3), '음성 평균 p', round(float(prob[y == 0].mean()), 3))
    emb_model = os.path.join(os.path.dirname(os.path.dirname(npz)), 'models', 'yamnet_emb.tflite')
    sha = hashlib.sha256(open(emb_model, 'rb').read()).hexdigest() if os.path.exists(emb_model) else None
    J = dict(about='사이렌/아님 머리 — YAMNet 임베딩(Identity_1, 1024) → z=(e-mean)/std → p', classes=['not_siren', 'siren'],
             yamnet=dict(file='yamnet_emb.tflite', source='https://tfhub.dev/google/lite-model/yamnet/tflite/1?lite-format=tflite', sha256=sha,
                         input='waveform float32 [15600] 16 kHz mono −1..1', embedding_output='Identity_1'),
             frame=dict(win=WIN, hop=HOP, sr=SR), hysteresis=dict(on_hits=2, off_misses=8),
             mean=mu.tolist(), std=sd.tolist(), threshold=None,
             train=dict(npz=os.path.basename(npz), lists=[str(s) for s in d['lists']], windows=int(len(y)), pos=int(y.sum()), spec=spec,
                        min_snr=min_snr, neg_yam=neg_yam), **head)
    if th_from:   # dev 모델(같은 설정, dev 를 뺀 목록으로 학습)에서 고른 문턱을 그대로 옮긴다
        D = json.load(open(th_from, encoding='utf-8')); J['threshold'] = D['threshold']
        J['threshold_pick'] = dict(D.get('threshold_pick', {}), picked_with=os.path.basename(th_from))
    json.dump(J, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(out, '문턱', J['threshold'])

def load_head(p):
    J = json.load(open(p, encoding='utf-8'))
    mu, sd = np.array(J['mean'], np.float32), np.array(J['std'], np.float32)
    if J['kind'] == 'lr':
        w, b = np.array(J['w'], np.float32), J['b']
        return J, lambda E: sig(((E - mu) / sd) @ w + b)
    W1, b1, w, b = np.array(J['W1'], np.float32), np.array(J['b1'], np.float32), np.array(J['w'], np.float32), J['b']
    return J, lambda E: sig(np.maximum(((E - mu) / sd) @ W1 + b1, 0) @ w + b)

def cmd_apply(hp, embs):
    J, f = load_head(hp)
    for p in embs:
        E = np.load(p).astype(np.float32); t = (np.arange(len(E)) * HOP + WIN) / SR
        np.save(p.replace('.emb.npy', '.head.npy'), np.stack([t, f(E)], 1).astype(np.float32)); print(p, len(E))

# ---------- pick ----------
THS = [round(float(v), 4) for v in np.r_[np.arange(0.05, 0.9, 0.05), np.arange(0.9, 0.99, 0.01), [0.99, 0.995, 0.998, 0.999, 0.9995, 0.9998, 0.9999]]]

def cmd_pick(hp, dirs, key, fa_max):
    res = {}
    for d in dirs:
        if key == 'head':   # 이 머리로 dev 스트림의 .head.npy 를 새로 쓴다(다른 머리 결과가 남아 있지 않게)
            import glob; cmd_apply(hp, sorted(glob.glob(os.path.join(d, '*.emb.npy'))))
        a = ['-', ','.join(map(str, THS)), ','.join(map(str, THS))]
        r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'score.py'), d] + a, capture_output=True, text=True, encoding='utf-8')
        assert r.returncode == 0, r.stderr
        S = json.load(open(os.path.join(d, 'score.json'), encoding='utf-8'))
        for th in THS:
            m = f'{key}@{th}'
            fa = [S[f'neg_{c}.wav|{m}']['fa_per_h'] for c in ('out', 'cab')]
            on = max(S[f'neg_{c}.wav|{m}']['on_frac'] for c in ('out', 'cab'))
            if on > 0.01: fa = [999.0]   # 배경에서 1 % 넘게 켜져 있으면(켜진 채 머묾 = 구간 1개로 세어짐) 탈락
            rec = [S[f'{c}_snr{s:+d}.wav|{m}']['recall'] for c in ('out', 'cab') for s in (6, 0, -6)]
            res.setdefault(th, []).append((max(fa), float(np.mean(rec))))
    rows = [(th, max(v[0] for v in vs), float(np.mean([v[1] for v in vs]))) for th, vs in res.items()]
    for th, fa, rec in rows: print(f'  {key}@{th}: dev 오경보 최대 {fa:.1f}/h · 검출(±6,0 dB 평균) {rec*100:.1f}%')
    ok = [r for r in rows if r[1] <= fa_max]
    best = max(ok, key=lambda r: (round(r[2], 4), r[0])) if ok else max(rows, key=lambda r: r[0])
    print('고른 문턱', key, best)
    if key == 'head' and hp != '-':
        J = json.load(open(hp, encoding='utf-8')); J['threshold'] = best[0]
        J['threshold_pick'] = dict(dev=[os.path.basename(os.path.normpath(d)) for d in dirs], rule=f'neg 오경보 ≤ {fa_max}/h 중 out/cab +6·0·−6 dB 평균 검출 최대',
                                   dev_fa_per_h=best[1], dev_recall=round(best[2], 4))
        json.dump(J, open(hp, 'w', encoding='utf-8'), ensure_ascii=False)
    return best

if __name__ == '__main__':
    c, args = sys.argv[1], sys.argv[2:]
    if c == 'split': cmd_split(*args)
    elif c == 'embed':
        pos, kw = opts(args, {'--jobs'}); cmd_embed(pos[0], pos[1:], int(kw.get('--jobs', 16)))
    elif c == 'trainset':
        pos, kw = opts(args, {'--seed', '--jobs'}); cmd_trainset(pos[0], pos[1], pos[2], pos[3:], kw.get('--seed', 1), int(kw.get('--jobs', 16)))
    elif c == 'fit':
        pos, kw = opts(args, {'--seed', '--min-snr', '--neg-yam', '--threshold-from'})
        cmd_fit(pos[0], pos[1], pos[2], kw.get('--seed', 1), kw.get('--min-snr'), kw.get('--neg-yam'), kw.get('--threshold-from'))
    elif c == 'apply': cmd_apply(args[0], args[1:])
    elif c == 'pick':
        pos, kw = opts(args, {'--key', '--fa'}); cmd_pick(pos[0], pos[1:], kw.get('--key', 'head'), float(kw.get('--fa', 1.0)))
    else: raise SystemExit(__doc__)
