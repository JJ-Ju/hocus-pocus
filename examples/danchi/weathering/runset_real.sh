#!/bin/sh
# runset_real.sh <tag> : the presets and seeds on the real building, four at a time
GATE=../../../scripts/weathering/weather_gate.py
OUT=${WX_OUT:-builds}
mkdir -p $OUT
tag=$1
run() {
  name=$1; shift
  out=$OUT/${tag}_${name}
  rm -rf $out
  python -I run_real.py $out "$@" > $out.log 2>&1
  python -I $GATE check $out --json $out/gate.json > $out.gate.txt 2>&1
  echo "$name: $(tail -1 $out.gate.txt)"
}
run typical_s1 typical --seed 1 &
run typical_s2 typical --seed 2 &
run kept kept &
run worn worn &
wait
run neglected neglected &
run new new &
run typical_s3 typical --seed 3 &
wait
