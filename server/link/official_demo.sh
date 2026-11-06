#!/usr/bin/env bash
# 공식 확인 실측(두 에뮬레이터): crash_demo 의 충돌 뒤 앞차에 순정 내비 돌발 정보(official_sim)를 넣는다 → 뒷차 "사고 구간(도로 정보 확인)" → 90초 뒤 공식 해제로 사고 의심이 거둬진다
# 대상 APK: 기본 ai.meeos.tago(두 기능 debug·픽업판). 길벗판은 TAGO_PKG=ai.meeos.gilbeot bash <이 대본> — 액티비티 이름은 판과 무관하게 ai.meeos.tago.MainActivity
A=emulator-5554; B=emulator-5556; PKG=${TAGO_PKG:-ai.meeos.tago}; APP=$PKG/ai.meeos.tago.MainActivity; VC=http://127.0.0.1:8088
OUT=${TAGO_OFFICIAL_OUT:-/tmp/tago_official}
mkdir -p $OUT
( while true; do curl -s -m 1 -X POST "$VC/browser/session?client=tago-official" >/dev/null; sleep 1; done ) & HB=$!; trap "kill $HB 2>/dev/null" EXIT
sleep 1.5
put() { curl -s -m 3 -X PUT "$VC/vehicle/$1" >/dev/null; }
put "hvac?recirc_on=0"; put "body?frunk=0"; put "gear?gear=Drive"; sleep 1; put "controls?speed=90&accelerator=30&brake=0"
adb -s $B shell am force-stop $PKG; adb -s $A shell am force-stop $PKG; sleep 2
adb -s $A logcat -c; adb -s $A shell am start -n $APP >/dev/null 2>&1; sleep 9
echo "== 앞차 링크 시작 + 그룹"; adb -s $A shell am start -n $APP --ez road_start true --ez group_start true >/dev/null 2>&1; sleep 7
CODE=$(adb -s $A logcat -d -s Meeos 2>/dev/null | grep -o "code=[0-9A-Za-z]*" | tail -1 | cut -d= -f2); echo "코드 $CODE"
echo "== 뒷차 출발(4.5km 뒤) + 합류"; adb -s $B logcat -c; adb -s $B shell am start -n $APP --ei link_offset -4500 --es link_name 엄마 --ez road_start true --ez convoy_sim true --es link_code "$CODE" >/dev/null 2>&1; sleep 10
echo "== 앞차 충돌: VC 시속 90 → 0"; put "controls?speed=0&accelerator=0&brake=100"
sleep 4; adb -s $A exec-out screencap -p > $OUT/a1.png; adb -s $B exec-out screencap -p > $OUT/b1.png
echo "-- 뒷차 1단계"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "\[음성\]" | cut -c7-18,33-220 | tail -2
echo "== 앞차: 순정 내비 돌발 정보(공식 사고, 내 자리, 90초 뒤 해제) 흉내"; adb -s $A shell am start -n $APP --es official_sim "ACCIDENT,0,end=90" >/dev/null 2>&1
sleep 5; adb -s $A exec-out screencap -p > $OUT/a2.png; adb -s $B exec-out screencap -p > $OUT/b2.png
echo "-- 앞차 로그"; adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "공식|official" | cut -c7-18,33-200 | tail -2
echo "-- 뒷차 2단계(공식 확인)"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "\[음성\]" | cut -c7-18,33-220 | tail -2
echo "== 공식 해제까지 95초 대기"; sleep 95
adb -s $A exec-out screencap -p > $OUT/a3.png; adb -s $B exec-out screencap -p > $OUT/b3.png
S0=$(adb -s $A logcat -d -s Meeos 2>/dev/null | grep -o "공식 돌발 시연: ACCIDENT s=[0-9]*" | tail -1 | grep -o "[0-9]*$")
echo "-- 공식 사고 자리(s=$S0) ±2km 의 사고 의심이 거둬졌는지(시연 익명 차들이 만든 다른 사고 의심은 남는다) + 허브 보기"
curl -s -m 3 "http://127.0.0.1:8791/api/road" | python -X utf8 -c "import sys,json; v=json.load(sys.stdin); hz=v.get('hazards', []); print('공식 자리 사고 의심:', [h['id'] for h in hz if h['type']=='INCIDENT' and abs(h['s']-$S0)<=2000] or '없음(해제됨)'); print([(h['type'], h['s'], h.get('cars')) for h in hz])"
