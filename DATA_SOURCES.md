# 데이터 출처와 이용 조건

이 저장소에 들어 있는 지도·공공데이터·모델·에셋과, README 그림에 렌더로만 쓰인 3D 에셋의 출처와 출처 표시 의무를 정리한다. 앱 지도 화면 오른쪽 아래에도 같은 출처를 표시한다. 소프트웨어 라이브러리는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 에 있다. 마지막 확인: 2026-11-11.

## 1. 저장소에 들어 있는 데이터

| 데이터 | 쓰인 곳 | 출처 | 이용 조건 |
|---|---|---|---|
| 경부고속도로 하행(양재 → 천안) 경로 선·나들목·터널·교량 | `server/link/gyeongbu_route.json` (`server/link/fetch_highway_osm.py`·`build_highway_route.py`·`build_junctions.py`·`build_zones.py`) | © OpenStreetMap contributors (Overpass API, 2026-10-25) | ODbL 1.0 — 출처 표시, 파생 데이터베이스 공유 시 같은 조건 |
| 사고 다발 구간(경부선 하행 이 경로 103건, 2023~2025) | `server/link/gyeongbu_route.json` zones (`server/link/build_zones.py`) | 한국도로공사 「고속도로 교통사고 상세현황」, 공공데이터포털 15145192 | 이용허락범위 제한 없음(공공데이터포털 파일 페이지, 2026-11-11 확인) |
| 나들목 공식 이정(사고 이정 → 경로 위치 기준점) | `server/link/build_zones.py` | 위키백과 「경부고속도로」 나들목 표 | 이정 숫자(사실 정보)만 사용, 출처 표시 |
| 고속도로 휴게소 전기차 충전소 9곳 좌표(충전소 단위)·충전기 목록 — 충전기 고장 신고의 충전소 반경 · 충전기 상태(stat, `server/link/fetch_ev_status.py` 가 허브에 올림) | `server/link/gyeongbu_route.json` evStations (`server/link/fetch_ev_stations.py`, 2026-11-06) | 한국환경공단 「전기자동차 충전소 정보」, 공공데이터포털 15076352 | 공공누리 제1유형(출처 표시) |
| 앱 공용 지역 지도: 도로, 버스정류장, 횡단보도, 신호 교차로, 학교, 편의점·카페·약국·주차장·지하철 출구 | `server/daechi_map.json` | © OpenStreetMap contributors (Overpass API) | ODbL 1.0 |
| 앱 공용 지역 지도: 건물 주소(도로명+번지) — 단속 CCTV 주소를 좌표로 바꾸는 데만 사용 | `server/daechi_cctv.json` 좌표 | © OpenStreetMap contributors, 일부 OSM Nominatim 검색 | ODbL 1.0 |
| 앱 공용 지역 지도: 소화전 위치 179개 | `server/daechi_map.json` | 서울특별시 소방재난본부 「소방용수시설」(2025-12-31), 서울 열린데이터광장 OA-21306 | 공공누리 제1유형(출처 표시) |
| 앱 공용 지역 지도: 불법주정차 단속 고정형 CCTV 46대 | `server/daechi_cctv.json` | 서울특별시 강남구청 「강남구_불법주정차 단속 고정형 CCTV 현황(2026.8.3)」(구청 주차 안내 페이지 공개 자료) | 공개 행정자료 — 출처 표시. 좌표는 주소를 변환한 근사값 |
| 앱 공용 지역 지도: 공영주차장 6곳(운영 시간·요금) | `server/daechi_map.json` publicParking | 서울특별시 강남구 「공영주차장 정보」(2025-09-05), 공공데이터포털 15115393 | 공공누리 제1유형 |
| 앱 공용 지역 지도: 역 화장실(대치역) | `server/daechi_map.json` toilets | 서울교통공사 「역사공중화장실정보」(2026-02-12), 공공데이터포털 15044453 | 이용허락범위 제한 없음. 좌표 오류가 있어 위치는 OSM 출입구 사용 |
| 앱 공용 지역 지도: 방범 시설 26곳(보안등·안심벨·CCTV·112 안내) | `server/daechi_map.json` safety | 서울특별시 「안심귀갓길 안전시설물 통합데이터」(2023), 서울 열린데이터광장 OA-21696 | 공공누리 제1유형 |
| 앱 공용 해외 지역 지도(어바인·마컴·구루그람) | `server/global/*_map.json` | © OpenStreetMap contributors (`server/global/fetch_city_osm.py`) | ODbL 1.0 |
| 지도 아이콘 ORBIT 24종 | `server/icons/orbit` → 웹 SVG·안드로이드 벡터 | 외부에서 받은 에셋이 아닌 원본 심볼 세트(`server/icons/orbit/README.txt`) | 출품작 자체 자산 |
| 3D 차 모델 Kenney Car Kit 3.1 (glb 11개 + 공용 텍스처) | `server/link/models/` → 3D 관제 화면(`server/link/world.html`) | Kenney (https://kenney.nl). 2026-10-26 OpenGameArt 미러(https://opengameart.org/content/car-kit)에서 받음. 라이선스 원문 `server/link/models/LICENSE-kenney.txt` | CC0 1.0 — 출처 표시 선택(의무 없음) |
| 사이렌 분류 모델 YAMNet | `app/siren/yamnet.tflite` | 출처·평가 자료는 `tools/siren_eval/DATA_SOURCES.md` | Apache-2.0 |
| 지도 바탕(웹 화면·앱 지도) | `server/link/link.html`·`server/link/ambulance.html` | OpenFreeMap 스타일 + OpenMapTiles + © OpenStreetMap contributors(화면 출처 줄), 키가 있으면 TMAP 지도 | OSM 데이터 ODbL. OpenFreeMap 스타일·TMAP 지도의 이용 조건은 미확인(THIRD_PARTY_NOTICES.md 2.1) |

## 2. README 그림에 렌더로만 쓰인 3D 에셋 (파일은 이 저장소에 없음)

`docs/readme/unreal-ambulance.webp` 는 Unreal Engine 렌더 영상이다. 에셋 파일은 이용 조건상 재배포할 수 없어 저장소에 넣지 않았다.

| 에셋 | 출처 | 이용 조건 |
|---|---|---|
| 119 구급차 3D 모델 "Staria Ambulance Korea 2025" | 3DModels.org, 2026-10-28 구매(구매 기록은 제작자 계정에 있음) | 스탠다드 라이선스 — 영상·실시간 데모 사용 가능(판매처 메일 확인), 모델 파일 배포 금지 |
| 도시 배경(건물·도로·가로등) | Epic Games 「City Sample」(Unreal Engine 무료 샘플 프로젝트) | Epic 콘텐츠 이용 조건을 따른다 — 세부 조항은 이 문서에서 미확인. 에셋 파일은 재배포하지 않는다 |

