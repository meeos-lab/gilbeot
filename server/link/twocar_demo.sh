#!/usr/bin/env bash
# 두 차 라이브 시연 자동 재현: 앞차 = emulator-5554(내장 허브, VC 8088 로 실제 속도), 뒷차 = emulator-5556(허브 = 10.0.2.2:8791, 시연 주행)
# usage: bash twocar_demo.sh [brake]   — brake 를 주면 앞차가 급제동(VC 속도 90→20 km/h)까지 한다
# 시연 훅은 adb 셸 전용 방송(DemoHookReceiver, DUMP 권한)으로만 보낸다(2026-11-13) — `am start` 는 앱을 띄울 때만.
# 대상 APK: 기본 ai.meeos.tago(두 기능 debug 판). 길벗판은 TAGO_PKG=ai.meeos.gilbeot bash <이 대본> — 액티비티 이름은 판과 무관하게 ai.meeos.tago.MainActivity
A=emulator-5554; B=emulator-5556; PKG=${TAGO_PKG:-ai.meeos.tago}; APP=$PKG/ai.meeos.tago.MainActivity; HOOK="$PKG/ai.meeos.tago.app.DemoHookReceiver -a ai.meeos.tago.DEMO_HOOK"; VC=http://127.0.0.1:8088
OUT=${TAGO_TWOCAR_OUT:-/tmp/tago_twocar}
mkdir -p $OUT
# VC 심장박동(없으면 PUT 이 503 emulator_inactive)
( while true; do curl -s -m 1 -X POST "$VC/browser/session?client=tago-twocar" >/dev/null; sleep 1; done ) & HB=$!
trap "kill $HB 2>/dev/null" EXIT
sleep 1.5
put() { curl -s -m 3 -X PUT "$VC/vehicle/$1" | head -c 120; echo; }
echo "== 앞차 준비: 프렁크 닫힘·내기순환 끔·기어 D·속도 90"; put "body?frunk=0" >/dev/null; put "hvac?recirc_on=0" >/dev/null; put "gear?gear=Drive"; sleep 1; put "controls?speed=90&accelerator=30&brake=0"
for d in $A $B; do adb -s $d logcat -c; done
echo "== 앞차 링크 시작 + 가족 그룹"; adb -s $A shell am broadcast -n $HOOK --ez road_start true --ez group_start true >/dev/null 2>&1
sleep 6
CODE=$(adb -s $A logcat -d -s Meeos 2>/dev/null | grep -o "code=[0-9A-Za-z]*" | tail -1 | cut -d= -f2)
echo "가족 코드: $CODE"
echo "== 뒷차 링크 시작(1.2km 뒤) + 코드 합류 + 시연 주행"; adb -s $B shell am broadcast -n $HOOK --ei link_offset -1200 --es link_name 엄마 --ez road_start true --ez convoy_sim true --es link_code "$CODE" >/dev/null 2>&1
sleep 8
adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "도로 링크|합류|실패|\[음성\]" | cut -c33-200 | tail -6
adb -s $A exec-out screencap -p > $OUT/a1.png; adb -s $B exec-out screencap -p > $OUT/b1.png
if [ "$1" = "brake" ]; then
  echo "== 앞차 급제동: 90 → 20 km/h"
  put "controls?speed=60&accelerator=0&brake=90"; sleep 1; put "controls?speed=35&accelerator=0&brake=90"; sleep 1; put "controls?speed=20&accelerator=0&brake=60"; sleep 2
  echo "== 앞차 다시 90 으로"; put "controls?speed=70&accelerator=40&brake=0"; sleep 1; put "controls?speed=90&accelerator=30&brake=0"
  sleep 8
  echo "-- 앞차 로그"; adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "감지|급제동|\[음성\]" | cut -c33-200 | tail -4
  echo "-- 뒷차 로그"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "급제동|\[음성\]|위험" | cut -c33-200 | tail -6
  adb -s $A exec-out screencap -p > $OUT/a2.png; adb -s $B exec-out screencap -p > $OUT/b2.png
fi
