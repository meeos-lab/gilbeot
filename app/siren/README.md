# 사이렌 감지 모델

`yamnet.tflite` — YAMNet 소리 분류(AudioSet 521종) TFLite, 학습 없이 그대로 쓴다.
- 받은 곳: https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite (TF Hub `lite-model/yamnet/classification/tflite/1`)
- sha256: `10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de`, 4,126,810 바이트
- 라이선스: Apache License 2.0 (TensorFlow Models, https://github.com/tensorflow/models/tree/master/research/audioset/yamnet)
- 입력 `waveform_binary` float32 [15600](16 kHz 모노, −1..1, 0.975초), 출력 [1, 521] 점수
- 앱이 보는 종류(`yamnet_class_map.csv` 번호): 316 Emergency vehicle, 317 Police car (siren), 318 Ambulance (siren), 319 Fire engine, fire truck (siren), 390 Siren, 391 Civil defense siren

쓰는 곳: `app/src/main/java/ai/meeos/tago/SirenYamnet.kt`. 길벗·전체 판 APK 의 `assets/siren/` 에만 들어간다(타고 픽업 판에는 없음).
문턱·평가: `tools/siren_eval/README.md`, `docs/dev/60-test-quality.md` 1-2 절.
