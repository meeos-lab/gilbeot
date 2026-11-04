# 충전기 고장 공유 실측(두 에뮬레이터): 앞차(5554, 내장 허브)가 기흥휴게소(s 27119)에 서서 꽂았는데 90초 동안 충전이 안 됨 → 뒷차(5556)에 안내
# 준비: README "시연 순서: 두 차 라이브"대로 두 APK 설치·adb forward. 앞차 Virtual Console 은 기어 P·내기순환 끔
A=emulator-5554; B=emulator-5556; APP=ai.meeos.tago/.MainActivity
adb -s $B shell am force-stop ai.meeos.tago; adb -s $A shell am force-stop ai.meeos.tago; sleep 2
adb -s $A logcat -c; adb -s $A shell am start -n $APP >/dev/null 2>&1; sleep 9
echo "== 앞차: 기흥휴게소에 정차(출발 간격 +9119) + 링크 시작 + 가족 그룹"
adb -s $A shell am start -n $APP --ei link_offset 9119 --ez road_start true --ez group_start true >/dev/null 2>&1; sleep 7
CODE=$(adb -s $A logcat -d -s Meeos 2>/dev/null | grep -o "code=[0-9A-Za-z]*" | tail -1 | cut -d= -f2); echo "가족 코드: $CODE"
echo "== 앞차: 충전구 열고 꽂음, 충전 안 됨 → 90초"; adb -s $A shell am start -n $APP --es ev_sim "port=1,charge=0,soc=40" >/dev/null 2>&1; sleep 97
adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "감지: 충전" | cut -c33-120 | tail -2
echo "== 뒷차: 18000 에서 출발, 코드 합류, 시연 주행"
adb -s $B logcat -c; adb -s $B shell am start -n $APP --ei link_offset 0 --es link_name 엄마 --ez road_start true --ez convoy_sim true --es link_code "$CODE" >/dev/null 2>&1; sleep 18
echo "-- 뒷차 음성"; adb -s $B logcat -d -s Meeos 2>/dev/null | grep -E "\[음성\]" | cut -c33-230 | head -6
echo "== 앞차: 충전 시작(해제)"; adb -s $A shell am start -n $APP --es ev_sim "port=1,charge=1,soc=41" >/dev/null 2>&1; sleep 6
adb -s $A logcat -d -s Meeos 2>/dev/null | grep -E "충전 시작" | cut -c33-120 | tail -1
adb -s $A shell am start -n $APP --es ev_sim off >/dev/null 2>&1
