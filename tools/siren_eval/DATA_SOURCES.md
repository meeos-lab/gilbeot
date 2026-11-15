# 사이렌 감지: 자료 출처·권리 기록

규칙: 상업 사용이 확인된 자료만 앱·학습에 쓴다(2026-11-06 사용자 결정). 지금 앱은 **학습 없이** YAMNet 을 그대로 쓴다.

## 1. 앱에 들어간 것 — YAMNet 하나
| 항목 | 값 |
|---|---|
| 파일 | `app/siren/yamnet.tflite`, 4,126,810 B, sha256 `10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de` |
| 받은 곳 | `https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite` (TF Hub `lite-model/yamnet/classification/tflite/1` = Kaggle `google/yamnet/tfLite/classification-tflite` v1) |
| 가중치 라이선스 | **Apache 2.0** — Kaggle API `https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/classification-tflite/get` 의 `licenseName: "Apache 2.0"`, `totalUncompressedBytes: 4126810`(우리 파일 크기와 같음), 2026-11-06 확인 |
| 코드 라이선스 | Apache-2.0 — `tensorflow/models` 저장소 `research/audioset/yamnet`(LICENSE 원문 확인, 통합 세션 2026-11-06) |
| 학습 데이터 | Google AudioSet(구글이 학습, 우리는 다시 학습하지 않음) |
| 우리가 더한 것 | 없음(문턱 0.7·켬/끔 규칙만, `SirenYamnet.kt`) |

## 2. 평가에만 쓴 것(앱·학습에 안 들어감, 저장소에 음원 없음)
| 이름 | 출처 | 라이선스 | 비고 |
|---|---|---|---|
| LSSiren (Scientific Data 2022 "Large-scale audio dataset for emergency vehicle sirens and road noises") | figshare `10.6084/m9.figshare.19291472` | CC0 | 원본이 여러 출처에서 모인 것 — 원본마다의 권리는 따로 확인하지 않음. 시험 세트·배경 도로 소음 |
| sireNNet | Mendeley Data `j4ydzzv4kb` v1 | CC BY 4.0 | 인터넷 수집·증강본 섞임 — 원본 권리 불명확. dev 세트(문턱 고르기)·판별 층 학습(기각된 실험) |

저장소 밖 `datasets/siren/`(zip·16 kHz 변환본·스트림)에만 있다.

## 3. A칸(원본까지 CC0·CC BY 확인) 음원 2개 — 평가에만
통합 세션의 상업용 권리 재분류(`Documents/Codex/2026-11-05/new-chat/outputs/commercial_A/manifest.csv`, 근거 `license_evidence/*.json`).
| id(평가용) | 원본 | 작성자 | 라이선스 | 쓰임 |
|---|---|---|---|---|
| `a_cc0__Whelen.wav` | Wikimedia Commons `File:Whelen.ogg`(14.4 s, Whelen 사이렌 웨일·옐프·피어서, 소방차) | Heggyhomolit | CC0 1.0 | 양성(실제 녹음, 나라 unknown) |
| `a_alarm__201775378.wav` | Wikimedia Commons `File:Folha_de_S._Paulo_6pm_Siren.wav`(29.0 s, 브라질 신문사 건물 오후 6시 시보) | Vrsooo | CC0 1.0 | **차량이 아닌 경보음**(울리면 잘못 켜짐) |
sha256: Whelen.ogg `3262ec37…1fa433`, 201775378.wav `8384908d…ba361e`(`prep_extra.py` 가 변환 전에 맞춰 봄).

## 4. 합성 한국 사이렌 세트 `kr_synth` — 평가에만, **실제 녹음 아님**
`synth_kr.py`(seed 2026, 패턴×파형 6종 × 50개, 4~10 s). 한국 규칙(「자동차 및 자동차부품의 성능과 기준에 관한 규칙」)은 음량만 정하고(전방 20 m 90~120 dB — 아래 웹진 설명, 조문 원문은 이 기록에서 확인 안 함) 사이렌 종류·주파수는 정하지 않는다. 그래서 패턴 근거는 설명 자료다.
| 패턴 | 주파수 | 주기 | 근거 |
|---|---|---|---|
| 소방차 웨일 `fire_wail` | 300~750 Hz | 약 5 s | 한국소방산업기술원 웹진 2020-12 「사이렌, 유별난 악기에서 안전의 파수꾼으로!」(https://www.kfsi.or.kr/contents/webzine/202012/sub02-05.html), 모터매거진 2024-01-08 「생명을 살리는 구급차 소리, 반드시 알아야 하는 운전자의 상식」(https://www.motormag.co.kr/news/articleView.html?idxno=11773) |
| 경찰차 옐프 `police_yelp` | 300~750 Hz | 약 1 s | 주파수: 두 글. 주기: 모터매거진만('약 1초'), 웹진은 주기 없음 |
| 구급차 하이로우 `amb_hilo` | 610 Hz·690 Hz | 1 s 간격 | 두 글 |
| 파형 | **unknown** | — | sine(기본음만)·harm(홀수 배음 1/n, 4 kHz 까지 — 사각파 구동 흉내) 두 갈래로 둠 |
| 쓸기 모양·두 음 길이 | **unknown** | — | 직선 삼각형 / 반반으로 둠 |
| 주파수 흔들림·도플러·확성기·반사 | **unknown** | — | 넣지 않음 |
같은 글은 "실제로는 셋 다 옐프를 주로 쓰고 음색·주파수만 다르다", "전자 사이렌은 아무 소리나 낼 수 있다"는 설명도 소개한다 — 패턴과 차종의 짝은 확정이 아니다.

## 5. 저장소에 남은 학습 산출물
학습한 판별 층 기록 `tools/siren_eval/models/siren_head.json`(sireNNet + LSSiren 절반으로 학습, 기본 YAMNet 보다 못해 기각 — ADR-35)은 학습 자료 원본 권리가 불명확해 **2026-11-06 저장소에서 제거**(사용자 승인). 결과 수치만 README·60 에 남긴다. 저장소에 학습 산출물은 없다.

## 6. 차 안 조건 모델(2026-11-06, `cabin_streams.py`) — 평가에만, 출처는 공개 논문의 그래프에서 읽은 값
앱은 창을 닫은 차 안 마이크로 듣는다. 실차 녹음은 없어(다음 단계도 실차 녹음이 아니라, 녹음한 사이렌 음원을 조건별로 다시 트는 재현 실증) 아래 두 출처로 전달 특성을 흉내 냈다.
| 항목 | 출처 | 쓴 값 | 한계 |
|---|---|---|---|
| 차체 차음(소음 저감 NR, 1/3 옥타브) | C. Q. Howard, A. J. Maddern, E. P. Privopoulos, "Acoustic characteristics for effective ambulance sirens", *Acoustics Australia* 39(2), 2011, pp. 43–53 — 그림 4 "Noise reduction of an average passenger vehicle"(https://www.acoustics.asn.au/journal/2011/2011_39_2_Howard.pdf) | 2005 Mitsubishi Magna 왜건, 문·창 닫음, 백색소음 스피커 앞·옆·뒤 3곳(마이크에서 4.2 m), 운전석 마이크, 차 있을 때/없을 때 차. 세 위치 평균을 그래프에서 읽음(±2 dB): 100 Hz 17, 250 Hz 22, 500 Hz 27, 1 kHz 36, 2 kHz 32, 4 kHz 38, 8 kHz 35 dB(전체 표는 `cabin_streams.py` `NR_CABIN`) | 차 1대·2005년식; 요즘 차(이중 접합 유리, EV)는 다를 수 있다. 읽은 값이라 ±2 dB. 25 Hz 아래·8 kHz 위는 끝값 유지 |
| 실내 주행 소음 스펙트럼(옥타브) | G. Staneva, R. Ivanov, G. Kadikyanov, "Octave band analysis of car noise emissions at different speeds and on different pavements", *Transport Problems* 18(2), 2023, pp. 63–70, DOI 10.20858/tp.2023.18.2.06 — 그림 19(60 km/h)·그림 21(90 km/h), 매끈한 아스팔트, GV(Nissan Qashqai 1.6 DIG-T) | 옥타브 대역 레벨 dB(가중 없음), 그래프에서 읽음(±1 dB). 60 km/h: 31.5 Hz 40, 63 Hz 47, 125 Hz 48, 250 Hz 49, 500 Hz 48, 1 kHz 47, 2 kHz 43, 4 kHz 38, 8 kHz 41. **90 km/h**(100 km/h 조건에 그대로 씀 — 가장 가까운 공개 값): 42, 46, 48, 54, 52, 52, 42, 38, 41 | 100 km/h 측정은 없음(90 km/h 로 대용; 바람 소음은 속도와 함께 커지므로 실제 100 km/h 는 조금 더 나쁠 것). 4~16 kHz 의 38~43 dB 는 속도와 무관해 측정기 바닥으로 보이나 읽은 대로 둠(고음 소음이 조금 과함 = 보수적). 절대 레벨은 쓰지 않고 **모양만** 써서 백색 가우스 잡음을 물들인 정상 잡음 — 바람·엔진 변동·음악·대화·에어컨 없음 |
| SNR 정의 | IEC 61672 A 가중 | 사이렌(차 안 조건은 필터 거친 뒤) A 가중 RMS ÷ 그 자리 배경 A 가중 RMS. +10 / 0 / −5 dB | 실내 소음은 저주파가 세서 가중 없는 RMS 비로 0 dB 를 맞추면 실제보다 쉬운 조건이 된다. 기존 표(`streams.py`)는 가중 없는 비라 '0 dB' 의 뜻이 다르다 |
| 마이크·이득 | — | **unknown** — 소음 없는 조건은 사이렌을 −26 dBFS 로 다시 맞춰 음색 차이만 본다 | 실차 마이크 위치·AGC 는 모른다 |
찾아봤으나 못 쓴 것: Potter·Fidell·Myles·Keast 1977(DOT-TSC-OST-77-38, 자동차 삽입 손실 측정) — 스캔 PDF 라 수치를 못 읽음; Corliss & Jones 1976(삽입 손실 약 30 dB 한 값) — 주파수별 값 없음.
