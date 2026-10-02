#!/usr/bin/env bash
# Stress test for bin/bgjob on a private tmux server and state directory.
#   test/bgjob-test.sh
set -uo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
B=$here/bin/bgjob
export BGJOB_SOCKET=bgjob-test-$$ BGJOB_DIR=/tmp/opencode/bgjob-test-$$
mkdir -p /tmp/opencode
pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $*"; }
no() { fail=$((fail + 1)); echo "FAIL $*"; }
check() { local what=$1; shift; if "$@"; then ok "$what"; else no "$what"; fi; }
not() { ! "$@"; }
idof() { awk '{print $1}'; }
finish() { tmux -L "$BGJOB_SOCKET" kill-server 2>/dev/null; rm -rf "$BGJOB_DIR" "${TMUX_TMPDIR:-/tmp}/tmux-$(id -u)/$BGJOB_SOCKET"; }
trap finish EXIT

echo "== basics"
id=$($B start hello -- 'echo first; echo second; exit 3' | idof)
out=$($B wait "$id" -t 10); code=$?
check "exit status 3 ($out)" [ "$code" = 3 ]
check "status line says exited 3" grep -q "exited 3 after" <<<"$out"
check "first line logged (go gate)" grep -qx first <($B log "$id")
check "last line logged" grep -qx second <($B log "$id")
timeout 2 "$B" wait "$id" -t 30 >/dev/null; code=$?
check "wait again returns at once with the same status ($code)" [ "$code" = 3 ]
check "NAME resolves to newest job" grep -q "^$id " <($B wait hello -t 1)

echo "== immediate output, many times (log head/tail races)"
bad=0
for i in $(seq 40); do
  id=$($B start race -- "echo begin-$i; seq 1 300; echo end-$i" | idof)
  $B wait "$id" -t 10 >/dev/null
  log=$($B log "$id" -n 1000)
  grep -qx "begin-$i" <<<"$log" && grep -qx "end-$i" <<<"$log" && [ "$(grep -cx '[0-9]*' <<<"$log")" = 300 ] || { bad=$((bad + 1)); echo "  run $i lost output"; }
done
check "40 quick jobs: no lost first/last/middle lines" [ "$bad" = 0 ]

echo "== concurrent starts on a cold server"
tmux -L "$BGJOB_SOCKET" kill-server 2>/dev/null
ids=$(for i in $(seq 20); do ("$B" start par -- "sleep 0.$((RANDOM % 9)); echo done-$i" | idof) & done; wait)
check "20 parallel starts all got IDs" [ "$(wc -w <<<"$ids")" = 20 ]
check "IDs are unique" [ "$(tr ' ' '\n' <<<"$ids" | sed '/^$/d' | sort -u | wc -l)" = 20 ]
bad=0
for id in $ids; do
  $B wait "$id" -t 20 >/dev/null || bad=$((bad + 1))
  grep -q "^done-" <($B log "$id") || bad=$((bad + 1))
done
check "all 20 finished with output" [ "$bad" = 0 ]

echo "== wait timeout while running"
id=$($B start slow -- 'sleep 30' | idof)
t0=$(date +%s%N); out=$($B wait "$id" -t 1); code=$?; t1=$(date +%s%N)
check "running → exit 75 ($out)" [ "$code" = 75 ]
check "returned after ~1 s ($(( (t1 - t0) / 1000000 )) ms)" [ $(( (t1 - t0) / 1000000 )) -lt 2500 ]

echo "== kill takes the whole process group"
id=$($B start tree -- 'sleep 1001 & sleep 1002 & (sleep 1003; echo x) & wait' | idof)
sleep 0.5
pid=$(tmux -L "$BGJOB_SOCKET" display-message -p -t "=$id:" '#{pane_pid}')
check "children are running" [ "$(pgrep -g "$pid" | wc -l)" -ge 4 ]
out=$($B kill "$id")
check "status killed ($out)" grep -q "killed after" <<<"$out"
sleep 0.3
check "no process left in the group" [ -z "$(pgrep -g "$pid")" ]
$B wait "$id" -t 1 >/dev/null; check "wait on killed → 137" [ $? = 137 ]

echo "== TERM-ignoring job is still killed"
id=$($B start stubborn -- "trap '' TERM; sleep 1004" | idof)
sleep 0.3
pid=$(tmux -L "$BGJOB_SOCKET" display-message -p -t "=$id:" '#{pane_pid}')
$B kill "$id" >/dev/null
sleep 0.3
check "SIGKILL fallback" [ -z "$(pgrep -g "$pid")" ]

echo "== died: the runner is killed -9 behind bgjob's back"
id=$($B start victim -- 'sleep 1005' | idof)
sleep 0.3
pid=$(tmux -L "$BGJOB_SOCKET" display-message -p -t "=$id:" '#{pane_pid}')
kill -KILL -- "-$pid"
out=$($B wait "$id" -t 5); code=$?
check "status died ($out)" grep -q "died after" <<<"$out"
check "wait → 70" [ "$code" = 70 ]

echo "== environment, cwd, quoting"
export BGJOB_TEST_VAR='hello world $HOME'
mkdir -p "$BGJOB_DIR/some dir"
id=$($B start env -C "$BGJOB_DIR/some dir" -- 'printf "%s|%s\n" "$BGJOB_TEST_VAR" "$PWD"' | idof)
$B wait "$id" -t 10 >/dev/null
check "exported env carried" grep -qF 'hello world $HOME|' <($B log "$id")
check "-C dir with a space" grep -qF "|$BGJOB_DIR/some dir" <($B log "$id")
id=$($B start argv -- printf '<%s>\n' 'a b' "it's" '$x' '"q"' | idof)
$B wait "$id" -t 10 >/dev/null
check "argv form keeps every argument intact" [ "$($B log "$id" | tr -d '\n')" = "<a b><it's><\$x><\"q\">" ]
id=$($B start pipe -- 'seq 1 10 | awk "{s+=\$1} END {print s}" && echo and-then' | idof)
$B wait "$id" -t 10 >/dev/null
check "single string is a shell line" [ "$($B log "$id" | tr '\n' ' ')" = "55 and-then " ]
id=$($B start nodir -C / -- 'true' | idof)
check "-C missing dir is rejected" not "$B" start bad -C /nonexistent/x -- true 2>/dev/null
check "bad NAME is rejected" not "$B" start 'a b' -- true 2>/dev/null

echo "== interactive: peek and send"
id=$($B start ask -- 'read -r -p "Continue? " a; echo "got:$a"' | idof)
for _ in $(seq 30); do $B peek "$id" | grep -q 'Continue?' && break; sleep 0.1; done
check "peek shows the prompt" grep -q 'Continue?' <($B peek "$id")
$B send "$id" yes Enter
$B wait "$id" -t 5 >/dev/null
check "send answered it" grep -qx 'got:yes' <($B log "$id")

echo "== progress bars and colors"
id=$($B start bar -- 'for i in $(seq 0 10 100); do printf "\r%3d%%" $i; sleep 0.02; done; printf "\n\033[31mred\033[0m done\n"' | idof)
$B wait "$id" -t 10 >/dev/null
log=$($B log "$id")
check "\\r redraws collapse to the final 100%" grep -qx '100%' <<<"$log"
check "colors stripped" grep -qx 'red done' <<<"$log"
check "no escape bytes left" not grep -q $'\x1b' <<<"$log"

echo "== large output"
id=$($B start big -- 'seq 1 200000' | idof)
$B wait "$id" -t 60 >/dev/null
n=$($B log "$id" -n 300000 | grep -cx '[0-9]*')
check "200000 lines all logged ($n)" [ "$n" = 200000 ]
check "last line is 200000" [ "$($B log "$id" -n 1)" = 200000 ]

echo "== outlives its caller"
id=$(bash -c "$B start orphan -- 'sleep 1; echo survived'" | idof)
$B wait "$id" -t 10 >/dev/null
check "job finished after the starting shell exited" grep -qx survived <($B log "$id")

echo "== ls"
check "ls lists every job" [ "$($B ls | wc -l)" -ge 70 ]

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
