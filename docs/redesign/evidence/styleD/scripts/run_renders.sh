#!/bin/sh
# round D: all full renders, sequential (one Karma at a time; other Houdini runs share the box)
D="/c/Users/jujun/AppData/Local/Temp/claude/C--Users-jujun-DEV-hocus-pocus/d956ad22-ff1d-47a8-a6c1-b1930b7bee4a/scratchpad/roundD"
HIP="C:/Users/jujun/AppData/Local/Temp/claude/C--Users-jujun-DEV-hocus-pocus/d956ad22-ff1d-47a8-a6c1-b1930b7bee4a/scratchpad/sk3-out/work/danchi_v005.hiplc"
OUT="$D/out/full"; mkdir -p "$OUT"
run() { tag=$1; shift; echo "== $tag $(date +%T)"; "$D/hy.sh" "$D/apply_painterly.py" "$HIP" "$@" "$OUT" --tag "$tag" --spp 32 2>&1 | grep -iv "minmax\|Error Summary\|PID:\|Command:\|total errors\|^---"; }
for job in "$@"; do
  case $job in
    base) run base none ;;
    t1) run t1 t1 ;;
    t2) run t2 t2 ;;
    t2_nodrift) run t2_nodrift t2 --no-drift ;;
    t2_nolift) run t2_nolift t2 --no-lift ;;
    t2_nodetail) run t2_nodetail t2 --no-detail ;;
    t2_keyfill) run t2_keyfill t2 --keyfill ;;
    t1_keyfill) run t1_keyfill t1 --keyfill ;;
    t1_x2) run t1_x2 t1 --set t1_val=0.06 --set t1_hue=8 --set t1_sat=0.10 --set t1_temp=0.02 --set t1_bump=0.003 --set t1_rough=0.08 ;;
    t2_strong) run t2_strong t2 --set lift=0.07 --set det_val=0.10 --set det_hue=20 --set det_sat=0.25 --set det_temp=0.05 --set det_floor=0.7 --set drift_amt=1.5 ;;
  esac
done
echo "== done $(date +%T)"
