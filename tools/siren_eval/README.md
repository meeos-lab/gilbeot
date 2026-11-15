# 사이렌 감지 평가 (PC)

앱의 사이렌 감지기(`SirenDetector.kt`)와 YAMNet 을 공개 실녹음으로 비교한다.
감지기 코드는 복사하지 않고 빌드할 때 앱 파일에서 떼어 온다(`build.gradle.kts` 의 `extractDetector`).

데이터(저장소 밖, `../datasets/siren/`):
- Scientific Data 2022 "Large-scale audio dataset for emergency vehicle sirens and road noises" — figshare 10.6084/m9.figshare.19291472, CC0. 시험 세트.
- sireNNet — Mendeley Data j4ydzzv4kb v1, CC BY 4.0(인터넷 수집, 증강본 섞임, 3초 클립). dev 세트(문턱 고르기).
- YAMNet TFLite 분류판 + `yamnet_class_map.csv`(TensorFlow models).

순서:
1. `python -I prep.py <데이터 루트>` — zip 안의 소리를 16 kHz 모노 16 bit 로 바꾸고 `manifest.csv`
2. `python -I streams.py <루트> <dataset> 300 7` — 도로 소음 배경 + 사이렌 300개(SNR +6~−18 dB, 차 밖·차 안 근사) + 배경만 1시간
3. `..\..\gradlew.bat -p tools/siren_eval run --args="<wav 목록> <결과.tsv> [app|local:32]"` — 규칙 감지기(app = 앱 그대로, local = 시험판)
4. `python -I yamnet_scores.py <모델> <class_map> <wav...>` — 0.48초마다 사이렌 점수
5. `python -I score.py <스트림 폴더> <결과.tsv> 0.3,0.5,0.7` — 검출률·오경보/시간 표

### YAMNet 임베딩 + 작은 머리(`train_head.py`, 2026-11-06)
모델: TF Hub `lite-model/yamnet/tflite/1`(출력 3개: 점수 521·임베딩 1024·log-mel, **float32 16 MB** — 4 MB 분류판과 다른 파일) → `../datasets/siren/models/yamnet_emb.tflite`.
누수 막기: 시험 클립은 학습·증강 소음·문턱 고르기에 한 번도 안 쓴다. 문턱은 dev 스트림에서만 고르고, 그 문턱을 같은 설정의 최종 모델에 옮긴다.
- A(교차 데이터셋): sireNNet 만으로 학습 → 기존 `streams/scidata2022`(scidata 전부) 로 시험. dev = sireNNet 20 %(증강본은 원본과 같은 쪽)
- B(scidata 안): scidata 를 클립 id 로 50/50(seed 2026, 사이렌·도로 따로) → sireNNet + scidata 학습 절반으로 학습,
  시험 절반만으로 만든 `streams/scidata2022_Btest` 로 시험. dev = 학습 절반의 20 %(`dev_scidata`)

1. `python -I train_head.py split <루트> 2026` — `splits/` 에 sn_fit·sn_dev·sd_test·sd_train(= sd_fit + sd_dev)·sd_fit·sd_dev
2. dev·시험 스트림(`streams.py` 에 `--ids`·`--name` 추가, 기본 동작은 그대로):
   `streams.py <루트> sirennet 0 7 --ids splits/sn_dev.txt --name dev_sirennet`,
   `streams.py <루트> scidata2022 0 7 --ids splits/sd_dev.txt --name dev_scidata`,
   `streams.py <루트> scidata2022 300 7 --ids splits/sd_test.txt --name scidata2022_Btest`
3. `python -I train_head.py embed <yamnet_emb.tflite> <스트림 wav...>` → `.emb.npy`(비교용 `yamnet_scores.py` 도 같은 스트림에)
4. `python -I train_head.py trainset <루트> <yamnet_emb.tflite> <out.npz> <목록...>` — 깨끗(밖)·깨끗(차 안 1.5 kHz 2차 저역)·
   **학습 목록의** 도로 소음에 SNR U(−15,+6) dB 로 섞은 것 4개. A_dev = sn_fit, A_final = sn_*, B_dev = sn_* + sd_fit, B_final = sn_* + sd_train
5. `fit <npz> <json> <lr:λ|mlp:H:λ> [--min-snr -6] [--neg-yam 0.5]` → `pick <dev json> <dev 스트림>` → 같은 설정으로 최종 `fit ... --threshold-from <dev json>`
   (pick 규칙: dev neg_out·neg_cab 오경보 ≤ 1/h 이고 배경 켜짐 ≤ 1 % 인 문턱 중 out/cab +6·0·−6 dB 평균 검출 최대)
6. `apply <json> <시험 emb.npy...>` → `python -I score.py <시험 스트림> <rule.tsv|-> 0.3,0.5,0.7 <머리 문턱>` — head@th 열

dev 로 고른 것: A = `lr:0.1`(문턱 0.98, dev 검출 39 %·오경보 0/h), B = `mlp:32:0.01 --min-snr -6 --neg-yam 0.5`(문턱 0.998, dev 23 %·1/h).
같은 dev 규칙으로 고른 기본 YAMNet 문턱: A dev 0.8(6 %), B dev 0.7(32 %).

시험 결과(검출률 · 사건 300개, 오경보/h · 배경 1시간):

| 조건 | A 머리@0.98 | B 머리@0.998 | YAMNet@0.5(A/B) | YAMNet@0.7(A/B) |
|---|---|---|---|---|
| out +6 | 66 % | 28 % | 86 / 88 % | 43 / 41 % |
| out 0 | 60 % | 25 % | 82 / 83 % | 36 / 36 % |
| out −6 | 50 % | 17 % | 71 / 69 % | 31 / 27 % |
| out −12 | 30 % | 5 % | 52 / 48 % | 17 / 13 % |
| cab 0 | 61 % | 17 % | 69 / 72 % | 21 / 24 % |
| cab −6 | 41 % | 7 % | 54 / 53 % | 17 / 16 % |
| neg_out | 16/h | 2/h | 10 / 8/h | 2 / 1/h |
| neg_cab | 12/h | 0/h | 5 / 3/h | 0 / 0/h |

결론: 두 분할 모두 dev 로 고른 머리는 기본 YAMNet 의 검출–오경보 곡선 위로 못 올라감(A 는 같은 오경보에서 검출이 낮고, B 는 YAMNet@0.7 과 오경보가 비슷한데 검출이 낮음).
앱에 넣지 않음. 학습한 머리 파일(`models/siren_head.json`)은 학습 자료(sireNNet) 원본 권리가 불명확해 2026-11-06 저장소에서 지웠다 — 위 수치만 남긴다(`train_head.py fit` 으로 다시 만들 수 있다).
해 본 것 중 효과 없던 것: L2 세기(0.01~10), MLP, 묻힌 양성 빼기(−6 dB 미만), YAMNet 이 사이렌을 듣는 '도로' 클립 빼기, YAMNet 사이렌 가중치 쪽으로 당긴 L2(`lrp`).

주의(누수·측정):
- 도로 클립 약 5 %에 YAMNet 사이렌 점수 ≥ 0.5(sd_test 450개 중 20개) — 실제 사이렌이 섞인 '음성'일 수 있어 배경 오경보가 모든 방법에서 부풀려진다.
- dev·시험 배경 1시간은 도로 클립 90~450개를 되풀이해 이은 것이라 오경보 수가 서로 독립이 아니다(1/h 차이는 잡음 수준). dev 사이렌도 93~250개라 같은 설정을 다시 증강해도 dev 검출이 ±10 %p 흔들렸다.
- B 는 클립 id 무작위 분할이라 같은 녹음에서 잘린 이웃 클립이 학습·시험에 갈렸을 수 있다(유리한 쪽 누수). 그래도 졌다.
- sireNNet 은 증강본이 섞여 있어 sound_N_k 를 원본과 같은 쪽에 묶었지만 이름이 다른 중복은 못 막는다.


### 한국 패턴 합성 세트·A칸 음원 2개(2026-11-06, 앱 문턱 0.7)
출처·권리: `DATA_SOURCES.md`. 배경은 모두 LSSiren 시험 절반(`splits/sd_test.txt`)의 도로 소음.
1. `python -I synth_kr.py <루트> 50 2026` — 소방차 웨일(300~750 Hz, 5 s)·경찰차 옐프(300~750 Hz, 1 s)·구급차 하이로우(610·690 Hz, 1 s) × 파형 sine·harm, 300개
2. `python -I prep_extra.py <루트> a_cc0 siren fire_whelen_wail_yelp_piercer <Whelen.ogg> <sha256>`, `… a_alarm siren nonvehicle_time_signal <201775378.wav> <sha256>`
3. `streams.py <루트> kr_synth 0 7 --bg scidata2022 --bg-ids splits/sd_test.txt --name kr_synth`, A칸은 `--repeat 30 --name a_cc0_whelen` / `a_alarm_folha`
4. `yamnet_scores.py` → `score.py <스트림> - 0.5,0.7`(종류가 여럿이면 종류별 표가 붙는다)

결과(검출률, 0.7 / 0.5). **합성은 실제 녹음이 아니다.** A칸은 원본 1개를 30번 넣은 것이라 '30개 사건'이 아니라 '한 소리 × 배경 30곳'이다.
| 조건 | 합성 전체(300) | 합성 웨일 harm | 합성 옐프 harm | 합성 하이로우 harm | 합성 sine 3종 | Whelen 실녹음(CC0) | Folha 시보(차량 아님, CC0) |
|---|---|---|---|---|---|---|---|
| out +6 | 24 / 44 % | 94 / 100 % | 42 / 96 % | 0 / 16 % | 0~6 / 4~40 % | 97 / 100 % | **97 / 97 %** |
| out 0 | 20 / 45 % | 90 / 98 % | 26 / 86 % | 0 / 16 % | 0~2 / 4~52 % | 97 / 100 % | **80 / 87 %** |
| out −6 | 12 / 36 % | 60 / 86 % | 10 / 74 % | 0 / 10 % | 0~2 / 6~34 % | 67 / 100 % | 37 / 53 % |
| out −12 | 6 / 22 % | 30 / 48 % | 4 / 54 % | 0 / 8 % | 0~2 / 4~12 % | 43 / 93 % | 10 / 23 % |
| cab 0 | 18 / 33 % | 94 / 100 % | 14 / 80 % | 0 / 4 % | 0~2 / 2~10 % | 57 / 100 % | 47 / 60 % |
| cab −6 | 12 / 26 % | 56 / 82 % | 12 / 58 % | 0 / 2 % | 0~2 / 2~6 % | 30 / 100 % | 13 / 40 % |
| 배경만 1 h(out / cab) | 0 / 1 회 (0.7) | | | | | 4 / 1 회 | 3 / 0 회 |

읽기:
- YAMNet 은 패턴보다 음색을 본다. 기본음만인 sine 은 세 패턴 모두 '사이렌'으로 거의 안 잡히고(맑은 화면에서 1위 = "Sine wave"), 배음을 넣은 harm 은 웨일이 잘 잡히며 옐프는 0.5 에서만 잡힌다.
- **합성 구급차 하이로우(610·690 Hz)는 0.7 에서 0 %**(맑은 화면 1위 = "Music"). 실제 한국 구급차 소리가 이렇다는 뜻은 아니다 — 합성 음색이 실제와 다를 수 있다(파형·확성기·반사 unknown). 실제 한국 구급차 녹음으로 확인하기 전에는 "한국 구급차를 마이크로 잡는다"고 말할 근거가 없다.
- 실녹음 Whelen(웨일·옐프·피어서)은 차 밖 0 dB 97 %, 차 안 근사 57 %.
- **차량이 아닌 시보 사이렌도 0.7 에서 차 밖 0 dB 80 % 켜진다**(YAMNet 'Siren'·'Civil defense siren' 종류를 우리가 사이렌으로 셈). 한 자리에 선 소리라 허브의 onset 이동 조건이 거를 것으로 보지만 이 경우는 시험하지 않았다.

결과(2026-11-05·06)는 `docs/dev/60-test-quality.md` 1-2 절.


### 차 안 조건(2026-11-06, `cabin_streams.py`) — 차체 차음 + 주행 실내 소음, 문턱 0.5 / 0.6 / 0.7
앱은 창을 닫은 차 안 마이크로 듣는데 위 표들은 차 밖 녹음에 도로 소음을 섞은 것이고 'cab' 은 1.5 kHz 저역 통과 근사였다. 여기서는 공개 측정값으로 차 안을 흉내 냈다(출처·그래프에서 읽은 값·한계는 `DATA_SOURCES.md` 6절):
- **차체 차음**: Howard·Maddern·Privopoulos 2011(*Acoustics Australia* 39(2)) 그림 4 — 2005 Mitsubishi Magna, 창 닫음, 1/3 옥타브 소음 저감(100 Hz 17, 500 Hz 27, 1 kHz 36, 2 kHz 32, 4 kHz 38 dB; 세 스피커 위치 평균, ±2 dB) → 선형 위상 FIR.
- **실내 주행 소음**: Staneva·Ivanov·Kadikyanov 2023(*Transport Problems* 18(2)) 그림 19(60 km/h)·21(90 km/h, **100 km/h 조건에 그대로 씀**) 옥타브 스펙트럼 모양의 정상(stationary) 합성 잡음. 음악·대화·바람 변동 없음.
- **SNR 은 A 가중** RMS 비(필터 거친 사이렌 : 그 자리 배경) +10 / 0 / −5 dB. 실내 소음은 저주파가 세서 가중 없는 비로 맞추면 실제보다 쉬운 조건이 된다. 그래서 이 표의 '밖 0 dB' 는 위 표들의 0 dB(가중 없음)와 같은 뜻이 아니다.
- 차 밖 조건의 소음은 LSSiren 실녹음 도로 소음(속도 표기 없음)이라 60/100 을 가르지 못한다. 소음 없는 조건은 사이렌을 −26 dBFS 로 다시 맞춘 것(마이크 이득 unknown → 음색 차이만).

명령(`R` = 데이터 루트 `../../../datasets/siren`):
```
python -I cabin_streams.py $R kr_synth 0 7 --bg scidata2022 --bg-ids $R/splits/sd_test.txt --name kr_synth_cabin
python -I cabin_streams.py $R a_cc0   0 7 --bg scidata2022 --bg-ids $R/splits/sd_test.txt --repeat 30 --name a_cc0_whelen_cabin
python -I cabin_streams.py $R a_alarm 0 7 --bg scidata2022 --bg-ids $R/splits/sd_test.txt --repeat 30 --name a_alarm_folha_cabin
python -I yamnet_scores.py $R/models/yamnet_cls.tflite $R/models/yamnet_class_map.csv $R/streams/<폴더>/*.wav      # 세 폴더
python -I score.py $R/streams/<폴더> - 0.5,0.6,0.7                                                                   # 세 폴더(score.json 에 종류별 검출률도 남김)
python -I cabin_table.py $R/streams/kr_synth_cabin $R/streams/a_cc0_whelen_cabin $R/streams/a_alarm_folha_cabin
# 민감도(고음 소음): 위 2·3번째 줄에 --int-hf slope --name <폴더>_slope 를 붙여 다시 만들고 cab*·neg_cab* 만 채점
```

결과(칸 = 문턱 **0.5 / 0.6 / 0.7** 의 검출률, 배경 행 = 1시간 오경보 횟수). A칸 두 열은 원본 1개 × 배경 30곳. **합성은 실제 녹음이 아니다.**

| 조건(SNR 은 A 가중) | 합성 전체(300) | 합성 웨일 harm | 합성 옐프 harm | 합성 하이로우 harm | Whelen 실녹음(1×30) | Folha 시보(차량 아님, 1×30 — 켜지면 오탐) |
|---|---|---|---|---|---|---|
| 밖 · 소음 없음 | 17 / 17 / 16 % | 100 / 100 / 96 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 100 / 100 / 100 % | 100 / 100 / 100 % |
| 차 안 · 소음 없음 | 15 / 2 / 0 % | 90 / 12 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 100 / 100 / 100 % | 100 / 100 / 100 % |
| 밖 · 도로 소음 +10 dB | 45 / 31 / 24 % | 100 / 100 / 96 % | 96 / 72 / 46 % | 16 / 4 / 0 % | 100 / 100 / 93 % | 100 / 100 / 100 % |
| 밖 · 도로 소음 0 dB | 42 / 26 / 18 % | 98 / 94 / 82 % | 86 / 40 / 20 % | 14 / 6 / 0 % | 100 / 100 / **77 %** | 83 / 77 / **70 %** |
| 밖 · 도로 소음 −5 dB | 31 / 17 / 10 % | 82 / 62 / 52 % | 60 / 24 / 6 % | 12 / 6 / 0 % | 100 / 80 / 43 % | 53 / 43 / 30 % |
| 차 안 · 60 km/h +10 dB | 18 / 17 / 16 % | 100 / 100 / 96 % | 6 / 0 / 0 % | 0 / 0 / 0 % | 100 / 100 / 47 % | 40 / 13 / 3 % |
| 차 안 · 60 km/h 0 dB | 13 / 0 / 0 % | 76 / 2 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 97 / 53 / **3 %** | 0 / 0 / **0 %** |
| 차 안 · 60 km/h −5 dB | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 7 / 0 / 0 % | 0 / 0 / 0 % |
| 차 안 · 100 km/h +10 dB | 17 / 17 / 16 % | 100 / 100 / 98 % | 4 / 0 / 0 % | 0 / 0 / 0 % | 100 / 93 / 27 % | 40 / 10 / 3 % |
| 차 안 · 100 km/h 0 dB | 17 / 8 / 0 % | 100 / 50 / 0 % | 4 / 0 / 0 % | 0 / 0 / 0 % | 100 / 67 / **0 %** | 0 / 0 / **0 %** |
| 차 안 · 100 km/h −5 dB | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % | 20 / 0 / 0 % | 0 / 0 / 0 % |
| 배경만 1 h · 밖(도로 소음) | 10 / 6 / 4회 | | | | 8 / 4 / 2회 | 16 / 7 / 4회 |
| 배경만 1 h · 차 안 60 km/h | 0 / 0 / 0회 | | | | 0 / 0 / 0회 | 0 / 0 / 0회 |
| 배경만 1 h · 차 안 100 km/h | 0 / 0 / 0회 | | | | 0 / 0 / 0회 | 0 / 0 / 0회 |

민감도 — 실내 소음의 4·8 kHz 값(출처 그래프에서 속도와 무관하게 38~41 dB = 측정기 바닥으로 보임)을 1→2 kHz 기울기로 외삽(`--int-hf slope`, 60 km/h 는 39·35, 100 km/h 는 32·22 dB)하면 차 안 결과가 크게 움직인다:

| 조건 | Whelen 읽은 값 | Whelen 외삽 | 시보 읽은 값 | 시보 외삽 |
|---|---|---|---|---|
| 차 안 · 60 km/h +10 dB | 100 / 100 / 47 % | 100 / 100 / 80 % | 40 / 13 / 3 % | 27 / 3 / 0 % |
| 차 안 · 60 km/h 0 dB | 97 / 53 / 3 % | 100 / 73 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |
| 차 안 · 100 km/h +10 dB | 100 / 93 / 27 % | 100 / 100 / 97 % | 40 / 10 / 3 % | 100 / 100 / 90 % |
| 차 안 · 100 km/h 0 dB | 100 / 67 / 0 % | 100 / 97 / 20 % | 0 / 0 / 0 % | 0 / 0 / 0 % |
| 차 안 · 100 km/h −5 dB | 20 / 0 / 0 % | 100 / 7 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |

읽기:
- **실녹음 Whelen, 문턱 0.7**: 밖 0 dB 77 % → 차 안 0 dB **0~3 %**(외삽 0~20 %), 차 안 +10 dB 27~47 %(외삽 80~97 %). 문턱을 0.5 로 내리면 차 안 0 dB 97~100 %, −5 dB 7~20 %. 차 안 0 dB 사이렌 프레임의 YAMNet 1위는 여전히 '경찰차·구급차 사이렌'이지만 점수 중앙값이 0.15~0.26 으로 0.7 에 못 미친다(소음 없이 필터만 거친 Whelen 은 0.7 에서 100 % — 음색보다 **실내 소음과의 겹침**이 원인).
- **시보(차량 아님) 오탐, 0.7**: 밖 0 dB 70 % → 차 안 0 dB 0 %, +10 dB 3 %(0.5 면 40 %, 외삽 100 km/h +10 dB 는 90 %). 차 안이라고 시보 오탐이 없어진다고 말할 수 없다.
- 어느 SNR 이 실제인가: 한국 규칙 전방 20 m 90~120 dB(`DATA_SOURCES.md` 4절) − Howard 차음 약 30 dB(1 kHz) = 차 안 60~90 dB 와 실내 소음(보통 60~70 dB(A)) 의 차 → 가까운 긴급차는 +10 dB 쪽, 먼 차·창 닫고 음악은 0 dB 이하. 근거가 약해 범위로만 둔다.
- **합성 세트는 수치로 쓰지 않는다**: 소음 없는 조건에서 옐프 harm 0 % 인데 도로 소음을 더하면 96 %(YAMNet 이 도로 소음을 '차량' 맥락으로 쓴다), 차 안 필터만 거친 웨일 harm 은 0.7 에서 0 %. 차 안 +10 dB 에서 웨일 harm 96~98 % 만 남고 0 dB 에서 0 %, 옐프·하이로우 0 %.
- 배경만 차 안 1 h 오경보 0 은 합성 정상 잡음이 'Pink noise·Ocean' 으로 들려서다. **실제 차 안(음악·대화·방향지시등·에어컨)의 오경보는 측정하지 않았다** — 밖 도로 소음 오경보는 0.7 에서 2~4/h, 0.5 에서 8~16/h.
- 한계: 차 1대(2005년식)·실내 스펙트럼은 다른 차 1대(2023, 90 km/h)·그래프에서 읽은 값·정상 잡음·A 가중 SNR 정의. **한국 긴급차량 실녹음은 여전히 없다** — 실제 한국 구급차 소리를 차 안 마이크로 잡는다는 주장은 하지 않는다. 다음 단계는 실차 녹음이 아니라 재현 실증이다: 녹음한 사이렌 음원을 정해진 거리·소음 조건으로 다시 틀어 받은 파일로 같은 격자(`prep_extra.py` → `cabin_streams.py` 대신 원본 그대로 → `score.py`)를 다시 돌린다.

**문턱 권고(바꾸지 않음)**: 0.7 은 차 안 0 dB 에서 거의 못 잡고 0.5 는 잡지만, 0.5 로 내렸을 때의 차 안 오경보를 잴 자료가 없고(합성 잡음 0 회는 무의미) 밖 도로 소음 오경보는 4 → 10회/h, 시보 오탐은 3 → 40 % 로 는다. 결과가 명확하지 않으므로 `SirenYamnet.kt` 의 0.7 은 그대로 두고, 실차 차 안 녹음(사이렌 + 음악·대화 배경 각각)으로 이 격자를 다시 돌린 뒤 0.5/0.6 을 정한다 — 사용자 결정 필요.
