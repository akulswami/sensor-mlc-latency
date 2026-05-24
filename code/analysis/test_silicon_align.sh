#!/usr/bin/env bash
# test_silicon_align.sh
#
# Synthetic-fixture unit tests for silicon_align.py.
#
# Covers:
#   1. Happy path: a 3-window host + uniform silicon polls →
#      correct alignment, last-poll-wins.
#   2. Pre-t0 polls are dropped (clock_offset_s < 0 case from session 4).
#   3. Empty window → fatal error (non-zero exit, error message on stderr).
#   4. A within-window class transition is captured by the LAST poll,
#      not the first or majority — proves we're using rule (c).
#   5. Header-schema validation: silicon_raw.csv with wrong column header
#      is rejected.
#   6. Strict ordering: out-of-order silicon polls produce a clear error.
#
# Exits 0 if all PASS, non-zero on first failure.

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/silicon_align.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { echo "PASS: $1"; }

# -------------------------------------------------------------------
# Fixture builders.
# -------------------------------------------------------------------
# session.json with one class block; imu_t0 controls the time-offset math.
make_session_json() {
    local out="$1"; local imu_t0="$2"; local class_name="$3"
    cat > "$out" <<EOF
{
  "session_date": "2026-05-23",
  "classes": [
    { "class": "$class_name",
      "imu_t0_monotonic_s": $imu_t0,
      "mlc_t_start_monotonic_s": $(python3 -c "print($imu_t0 - 0.5)"),
      "clock_offset_s": -0.5 }
  ]
}
EOF
}

# host_decisions.csv: a list of t_window_end_s values (one per row).
make_host_csv() {
    local out="$1"; shift
    echo "window_idx,t_window_end_s,var_norm,p2p_norm,class" > "$out"
    local i=0
    for t in "$@"; do
        printf "%d,%s,0.000000e+00,0.000000e+00,0\n" "$i" "$t" >> "$out"
        i=$((i+1))
    done
}

# silicon_raw.csv: poll timestamps are passed as "t_abs:class" pairs.
make_silicon_csv() {
    local out="$1"; shift
    cat > "$out" <<EOF
# mlc_poller v1
# poll_hz = 50
# duration_sec = 5
t_monotonic_s, mlc_src
EOF
    for pair in "$@"; do
        local t="${pair%%:*}"; local c="${pair##*:}"
        printf "%s, %s\n" "$t" "$c" >> "$out"
    done
}

# -------------------------------------------------------------------
# Test 1: happy path.
# -------------------------------------------------------------------
# imu_t0 = 1000.0; three host windows ending at 0.5, 1.0, 1.5 s relative.
# Silicon polls at absolute t = 1000.1, 1000.2, 1000.3, 1000.4, 1000.6,
#   1000.8, 1000.9, 1000.11, 1000.13, 1000.14, 1000.16, 1001.4, 1001.6.
# In accel-relative:  0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 0.9, ..., 1.4, 1.6.
# Window 0 (0, 0.5]: polls at 0.1, 0.2, 0.3, 0.4. Last=0.4, class=0.
# Window 1 (0.5, 1.0]: polls at 0.6, 0.8, 0.9. Last=0.9, class=4 (we'll
#   set this poll to class=4 to make the last-wins behavior testable).
# Window 2 (1.0, 1.5]: polls at 1.11, 1.13, 1.14, 1.16, 1.4. Last=1.4,
#   class=0.
make_session_json "$TMP/session1.json" 1000.0 still
make_host_csv "$TMP/host1.csv" 0.5 1.0 1.5
make_silicon_csv "$TMP/silicon1.csv" \
    "1000.1:0" "1000.2:0" "1000.3:0" "1000.4:0" \
    "1000.6:0" "1000.8:0" "1000.9:4" \
    "1001.11:0" "1001.13:0" "1001.14:0" "1001.16:0" "1001.4:0"

OUT="$TMP/out1.csv"
python3 "$SCRIPT" --host-decisions "$TMP/host1.csv" \
                  --silicon-raw "$TMP/silicon1.csv" \
                  --session-json "$TMP/session1.json" \
                  --class-name still \
                  --quiet > "$OUT" || fail "test1 script error"

# Expected:
#   0,0.500000,...,0
#   1,1.000000,...,4
#   2,1.500000,...,0
grep -q '^0,0.500000,0.000000e+00,0.000000e+00,0$' "$OUT" || fail "test1 window 0 class"
grep -q '^1,1.000000,0.000000e+00,0.000000e+00,4$' "$OUT" || fail "test1 window 1 class (last-poll-wins)"
grep -q '^2,1.500000,0.000000e+00,0.000000e+00,0$' "$OUT" || fail "test1 window 2 class"
[ "$(grep -c '^[0-9]' "$OUT")" = "3" ] || fail "test1 row count: expected 3, got $(grep -c '^[0-9]' "$OUT")"
pass "1. Happy path: last-poll-wins, row count, class assignment"

# -------------------------------------------------------------------
# Test 2: pre-t0 polls dropped (session 4 condition).
# -------------------------------------------------------------------
# imu_t0 = 1000.0. Silicon polls start at 999.5 (== -0.5s relative);
# 5 pre-t0 polls, then 3 post-t0 polls inside one host window ending at 0.5.
# All pre-t0 polls should be silently dropped; post-t0 polls should
# determine the class.
make_session_json "$TMP/session2.json" 1000.0 still
make_host_csv "$TMP/host2.csv" 0.5
make_silicon_csv "$TMP/silicon2.csv" \
    "999.5:4" "999.6:4" "999.7:4" "999.8:4" "999.9:4" \
    "1000.1:0" "1000.2:0" "1000.4:0"

OUT="$TMP/out2.csv"
STDERR="$TMP/err2.txt"
python3 "$SCRIPT" --host-decisions "$TMP/host2.csv" \
                  --silicon-raw "$TMP/silicon2.csv" \
                  --session-json "$TMP/session2.json" \
                  --class-name still \
                  > "$OUT" 2> "$STDERR" || fail "test2 script error"

grep -q '^0,0.500000,0.000000e+00,0.000000e+00,0$' "$OUT" || \
    fail "test2 pre-t0 polls (class=4) should be dropped; last in-window poll (class=0) should win"
grep -q 'dropped_pre_t0=5' "$STDERR" || \
    fail "test2 should report dropped_pre_t0=5; got: $(cat "$STDERR")"
pass "2. Pre-t0 polls dropped: 5 silenced, post-t0 last poll wins"

# -------------------------------------------------------------------
# Test 3: empty window → fatal error.
# -------------------------------------------------------------------
# Host has 2 windows ending at 0.5 and 1.0; silicon polls only at 0.1
# and 0.2 (both fall in window 0). Window 1 is empty; alignment must fail.
make_session_json "$TMP/session3.json" 1000.0 still
make_host_csv "$TMP/host3.csv" 0.5 1.0
make_silicon_csv "$TMP/silicon3.csv" "1000.1:0" "1000.2:0"

if python3 "$SCRIPT" --host-decisions "$TMP/host3.csv" \
                    --silicon-raw "$TMP/silicon3.csv" \
                    --session-json "$TMP/session3.json" \
                    --class-name still \
                    --quiet > "$TMP/out3.csv" 2> "$TMP/err3.txt"; then
    fail "test3 should have exited non-zero on empty window"
fi
grep -q 'zero silicon polls' "$TMP/err3.txt" || \
    fail "test3 should report 'zero silicon polls'; got: $(cat "$TMP/err3.txt")"
pass "3. Empty window: fatal error with explanatory message"

# -------------------------------------------------------------------
# Test 4: rule (c) — last poll wins over a majority of opposite class.
# -------------------------------------------------------------------
# This is the key methodology test. Window has 5 polls; 4 are class=0,
# but the LAST one is class=4. Rule (c) "last poll wins" gives class=4.
# Rule (b) "mode" would give class=0. The test fails if anyone changes
# the rule without updating this test.
make_session_json "$TMP/session4.json" 1000.0 still
make_host_csv "$TMP/host4.csv" 0.5
make_silicon_csv "$TMP/silicon4.csv" \
    "1000.05:0" "1000.10:0" "1000.20:0" "1000.30:0" "1000.49:4"

OUT="$TMP/out4.csv"
python3 "$SCRIPT" --host-decisions "$TMP/host4.csv" \
                  --silicon-raw "$TMP/silicon4.csv" \
                  --session-json "$TMP/session4.json" \
                  --class-name still \
                  --quiet > "$OUT" || fail "test4 script error"
grep -q '^0,0.500000,0.000000e+00,0.000000e+00,4$' "$OUT" || \
    fail "test4 rule(c): last poll (class=4) should win over mode (class=0); got: $(cat "$OUT")"
pass "4. Rule (c): last-poll wins over 4-of-5 majority"

# -------------------------------------------------------------------
# Test 5: header schema validation.
# -------------------------------------------------------------------
make_session_json "$TMP/session5.json" 1000.0 still
make_host_csv "$TMP/host5.csv" 0.5
cat > "$TMP/silicon5_bad.csv" <<EOF
# mlc_poller v1
# poll_hz = 50
# duration_sec = 5
timestamp, class
1000.1, 0
EOF
if python3 "$SCRIPT" --host-decisions "$TMP/host5.csv" \
                    --silicon-raw "$TMP/silicon5_bad.csv" \
                    --session-json "$TMP/session5.json" \
                    --class-name still \
                    --quiet > "$TMP/out5.csv" 2> "$TMP/err5.txt"; then
    fail "test5 should have rejected bad header"
fi
grep -q 'unexpected column header' "$TMP/err5.txt" || \
    fail "test5 should report 'unexpected column header'; got: $(cat "$TMP/err5.txt")"
pass "5. Header schema validation: wrong column names rejected"

# -------------------------------------------------------------------
# Test 6: out-of-order silicon polls → strict-ordering error.
# -------------------------------------------------------------------
make_session_json "$TMP/session6.json" 1000.0 still
make_host_csv "$TMP/host6.csv" 0.5
make_silicon_csv "$TMP/silicon6.csv" "1000.1:0" "1000.05:0" "1000.2:0"

if python3 "$SCRIPT" --host-decisions "$TMP/host6.csv" \
                    --silicon-raw "$TMP/silicon6.csv" \
                    --session-json "$TMP/session6.json" \
                    --class-name still \
                    --quiet > "$TMP/out6.csv" 2> "$TMP/err6.txt"; then
    fail "test6 should have rejected out-of-order silicon polls"
fi
grep -q 'silicon_polls not ascending' "$TMP/err6.txt" || \
    fail "test6 should report 'silicon_polls not ascending'; got: $(cat "$TMP/err6.txt")"
pass "6. Strict ordering: out-of-order silicon polls rejected"

echo ""
echo "All 6 tests PASS"
