#!/bin/sh
# sweeps_all.sh <tag> <gains gs,ga,k> : the four control sweeps on the real building at fixed gains
# (from the accepted Typical), four builds at a time; each step gated with --sweep, then each
# sweep's series rules (L1, L2, and K2 for damage).
GATE=../../../scripts/weathering/weather_gate.py
OUT=${WX_OUT:-builds}
mkdir -p $OUT
tag=$1; gains=$2
run() {
  out=$1; layer=$2; v=$3
  rm -rf $out
  python -I run_real.py $out typical --override $layer=$v --gains $gains > $out.log 2>&1
  python -I $GATE check $out --sweep --json $out/gate.json > $out.gate.txt 2>&1
  echo "$out: $(tail -1 $out.gate.txt)"
}
n=0
for spec in streaks:streaks damage:damage grime:soiling stain_fields:stains; do
  c=${spec%%:*}; l=${spec##*:}
  for v in 0 0.25 0.5 0.75 1.0; do
    run $OUT/${tag}_${c}_$v $l $v &
    n=$((n + 1))
    [ $((n % 4)) -eq 0 ] && wait
  done
done
wait
for spec in streaks:streaks damage:damage grime:soiling stain_fields:stains; do
  c=${spec%%:*}; l=${spec##*:}
  dirs=""
  for v in 0 0.25 0.5 0.75 1.0; do dirs="$dirs $OUT/${tag}_${c}_$v"; done
  python -I $GATE series sweep:$l $dirs --json $OUT/${tag}_${c}_series.json > $OUT/${tag}_${c}_series.txt 2>&1
  echo "$c series: $(tail -1 $OUT/${tag}_${c}_series.txt)"
done
