export TAGO_STEP=0.25 TAGO_TAU=0.5 TAGO_TINC=900 TAGO_GAWK="1:13,2:13" TAGO_ATTN_P=0.65 TAGO_PROCS=22
python -X utf8 -u results/_parity_rb.py
TAGO_COMPLY="0.15,0.18,0.22" python -X utf8 -u tago_sim.py robust comply 24
python -X utf8 -u tago_sim.py robust design 24
TAGO_REPLAY_TAG=_v2 python -X utf8 -u replay.py run
echo RB_PC_DONE
