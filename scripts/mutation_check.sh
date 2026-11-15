#!/usr/bin/env bash
# Mutation check: inject one bug at a time into a COPY of the RTL and confirm
# the testbench FAILS. A mutant that survives means the testbench has a blind
# spot. The real RTL in rtl/ is never modified.
#
# Usage: scripts/mutation_check.sh        (run from the repo root)
set -u
cd "$(dirname "$0")/.."

SRC=rtl/sync_fifo.sv
OUT=mutants
rm -rf "$OUT" && mkdir -p "$OUT"

# name | sed expression
MUTANTS=(
  "full_off_by_one|s/count == DEPTH/count == DEPTH - 1/"
  "write_ignores_full|s/wire do_write = wr_en \&\& !full;/wire do_write = wr_en;/"
  "read_ignores_empty|s/wire do_read  = rd_en \&\& !empty;/wire do_read  = rd_en;/"
  "simul_rw_counts_up|s/default: ;/2'b11: count <= count + 1'b1;/"
  "data_bit0_corrupt|s/mem\[wr_ptr\] <= wr_data;/mem[wr_ptr] <= wr_data ^ 1'b1;/"
  "read_ptr_stuck|s/rd_ptr <= rd_ptr + 1'b1;/rd_ptr <= rd_ptr;/"
)

# Sanity: the unmodified RTL must pass, otherwise "killed" means nothing.
echo "== baseline (unmutated RTL) =="
rm -rf sim_build_base results.xml
if ! make SIM_BUILD=sim_build_base RANDOM_CYCLES=500 >"$OUT/baseline.log" 2>&1 \
   || grep -q "<failure" results.xml; then
  echo "BASELINE FAILS - fix the design/testbench first. See $OUT/baseline.log"
  exit 2
fi
echo "baseline passes"
echo

killed=0
survived=0
for entry in "${MUTANTS[@]}"; do
  name="${entry%%|*}"
  expr="${entry#*|}"
  mkdir -p "$OUT/$name"
  sed "$expr" "$SRC" > "$OUT/$name/sync_fifo.sv"

  if cmp -s "$SRC" "$OUT/$name/sync_fifo.sv"; then
    echo "ERROR: mutant '$name' did not change the RTL (sed pattern is stale)"
    exit 2
  fi

  rm -rf "sim_build_$name" results.xml
  make VERILOG_SOURCES="$PWD/$OUT/$name/sync_fifo.sv" SIM_BUILD="sim_build_$name" \
       RANDOM_CYCLES=500 >"$OUT/$name/sim.log" 2>&1
  rc=$?

  # Killed = simulator/make errored, or any testcase reported a failure/error.
  if [ $rc -ne 0 ] || [ ! -f results.xml ] || grep -qE "<(failure|error)" results.xml; then
    echo "KILLED    $name"
    killed=$((killed + 1))
  else
    echo "SURVIVED  $name   <-- testbench did not catch this bug"
    survived=$((survived + 1))
  fi
  rm -rf "sim_build_$name"
done

rm -rf sim_build_base
echo
echo "mutants killed: $killed / $((killed + survived))"
[ "$survived" -eq 0 ]
