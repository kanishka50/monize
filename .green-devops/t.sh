#!/bin/bash
# usage: t.sh LABEL cmd...  -> "RESULT LABEL rc=N secs=S"; full log in $LOGDIR/LABEL.log
label=$1; shift
LOGDIR=${LOGDIR:-$RUNNER_TEMP/logs}; mkdir -p "$LOGDIR"
s=$(date +%s%N)
"$@" > "$LOGDIR/$label.log" 2>&1
rc=$?
e=$(date +%s%N)
ms=$(( (e - s) / 1000000 ))
printf 'RESULT %s rc=%d secs=%d.%03d\n' "$label" "$rc" $((ms/1000)) $((ms%1000))
grep -m1 -o "heap out of memory\|SIGKILL" "$LOGDIR/$label.log" | sed "s/^/RESULT $label crash: /"
exit 0
