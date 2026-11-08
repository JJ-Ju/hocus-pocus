#!/bin/sh
# sweep_grime_fine.sh <tag> <gains> : the grime (soiling) control at 0.1-0.6 in 0.1 steps, the range the
# rules accept around Typical's own amount (0.38); 0.75 and up failed D1/F3, 0 failed A2/D1.
GATE=../../../scripts/weathering/weather_gate.py
OUT=${WX_OUT:-builds}
mkdir -p $OUT
tag=$1; gains=$2
run() {
  v=$1; out=$OUT/${tag}_grime_$v
  rm -rf $out
  python -I run_real.py $out typical --override soiling=$v --gains $gains > $out.log 2>&1
  python -I $GATE check $out --sweep --json $out/gate.json > $out.gate.txt 2>&1
  echo "$out: $(tail -1 $out.gate.txt)"
}
run 0.1 & run 0.2 & run 0.3 & run 0.4 &
wait
run 0.5 & run 0.6 &
wait
