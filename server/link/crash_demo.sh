# 사고 판단 실측(두 에뮬레이터): 앞차(5554) 시속 90 주행 → 충돌(impact_sim 25,0) → "괜찮으세요?" 30초 무응답 → 뒷차(5556, 1.2km 뒤) "사고 의심 · 교통 막힘 주의"
A=emulator-5554; B=emulator-5556; APP=ai.meeos.tago/.MainActivity; VC=http://127.0.0.1:8088
OUT=${TAGO_CRASH_OUT:-/tmp/tago_crash}
mkdir -p $OUT
( while true; do curl -s -m 1 -X POST "$VC/browser/session?client=tago-crash" >/dev/null; sleep 1; done ) & HB=$!; trap "kill $HB 2>/dev/null" EXIT
sleep 1.5
put() { curl -s -m 3 -X PUT "$VC/vehicle/$1" >/dev/null; }
put "hvac?recirc_on=0"; put "body?frunk=0"; put "gear?gear=Drive"; sleep 1; put "controls?speed=90&accelerator=30&brake=0"
adb -s $B shell am force-stop ai.meeos.tago; adb -s $A shell am force-stop ai.meeos.tago; sleep 2
adb -s $A logcat -c; adb -s $A shell am start -n $APP >/dev/null 2>&1; sleep 9
echo "== 앞차 링크 시작 + 그룹"; adb -s $A shell am start -n $APP --ez road_start true --ez group_start true >/dev/null 2>&1; sleep 7
CODE=$(adb -s $A logcat -d -s Meeos 2>/dev/null | grep -o "code=[0-9A-Za-z]*" | tail -1 | cut -d= -f2); echo "코드 $CODE"
echo "== 뒷차 출발(1.2km 뒤) + 합류"; adb -s $B logcat -c; adb -s $B shell am start -n $APP --ei link_offset -4500 --es link_name 엄마 --ez road_start true --ez convoy_sim true --es link_code "$CODE" >/dev/null 2>&1; sleep 10
echo "== 앞차 충돌: VC 시속 90 → 0 순간(10Hz 표본에 단계 변화)"; put "controls?speed=0&accelerator=0&brake=100"
sleep 4; adb -s $A exec-out screencap -p > $OUT/a1.png; adb -s $B exec-out screencap -p > $OUT/b1.png
echo "-- 앞차 로그"; adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "감지: 충돌|괜찮|\[음성\]" | cut -c7-18,33-200 | tail -4
echo "-- 뒷차 로그(4초 뒤)"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "사고|\[음성\]" | cut -c7-18,33-220 | tail -3
echo "== 30초 무응답 대기"; sleep 30
adb -s $A exec-out screencap -p > $OUT/a2.png; adb -s $B exec-out screencap -p > $OUT/b2.png
echo "-- 앞차 로그"; adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "무응답|응급|\[음성\]" | cut -c7-18,33-200 | tail -4
echo "-- 뒷차 로그"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "\[음성\]" | cut -c7-18,33-220 | tail -4
