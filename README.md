# Synchronous FIFO: Verification with cocotb

[![regression](https://github.com/YudhaG/fifo-verification/actions/workflows/regression.yml/badge.svg)](https://github.com/YudhaG/fifo-verification/actions/workflows/regression.yml)

A parameterized synchronous FIFO (SystemVerilog) with a self-checking,
constrained-random testbench written in Python with
[cocotb](https://www.cocotb.org/), run on the open-source Icarus Verilog
simulator. Every push triggers a regression on GitHub Actions across multiple
FIFO configurations, plus a mutation check that proves the testbench catches
injected bugs.

## What is in here

```
rtl/sync_fifo.sv             DUT: FWFT sync FIFO, params DATA_WIDTH and DEPTH (power of 2)
tb/test_sync_fifo.py         testbench: driver, monitor, scoreboard, coverage, 4 tests
Makefile                     cocotb + Icarus flow
scripts/mutation_check.sh    injects 6 bugs, expects the testbench to fail on each
.github/workflows/           CI: config matrix + mutation job
```

## Design under test

- First-word-fall-through: `rd_data` shows the oldest entry whenever `!empty`.
- Write while `full` and read while `empty` are ignored (no corruption).
- Write and read in the same cycle are both honored.
- Asynchronous active-low reset (`rst_n`).
- Outputs: `full`, `empty`, `count` (occupancy).

## Verification environment

| Piece | What it does |
|---|---|
| Driver (`FifoEnv.cycle`) | Drives `wr_en`, `rd_en`, `wr_data` for one clock cycle |
| Monitor + scoreboard | Samples the pins on every clock edge, advances a reference model (a Python `deque`) in lock-step, and checks `count`, `full`, `empty`, and every data word and its order |
| Functional coverage | Named bins plus every occupancy level 0..DEPTH, closed by the random test |
| Reproducibility | Each test logs its seed. Re-run a failure with `make SEED=<n>` |

### Tests

| Test | Purpose |
|---|---|
| `test_reset_state` | Empty after reset. Mid-test async reset discards contents. FIFO usable afterwards |
| `test_fill_and_drain` | Fill to full, overflow attempts ignored, drain in order, underflow attempts ignored |
| `test_simultaneous_rw` | Write + read same cycle: mid-level, at full, at empty |
| `test_random` | Constrained-random traffic in 7 bias phases (write-heavy, read-heavy, balanced, back-to-back...), then asserts zero coverage holes |

### Coverage bins

`reached_full`, `reached_empty`, `write_when_full`, `read_when_empty`,
`simul_rw`, `simul_rw_at_full`, `simul_rw_at_empty`, `wptr_wrap`,
`rptr_wrap`, and every `count == 0..DEPTH`.

### Mutation check

`scripts/mutation_check.sh` copies the RTL, injects one bug at a time, and
fails if any mutant passes the testbench. Current bugs injected:

| Mutant | Bug |
|---|---|
| `full_off_by_one` | `full` asserts one entry early |
| `write_ignores_full` | writes accepted while full |
| `read_ignores_empty` | reads accepted while empty |
| `simul_rw_counts_up` | simultaneous write+read changes occupancy |
| `data_bit0_corrupt` | bit 0 of stored data flipped |
| `read_ptr_stuck` | read pointer never advances |

## Run it locally

### macOS

```bash
brew install icarus-verilog
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make
```

### Ubuntu / Debian

```bash
sudo apt-get install -y iverilog
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make
```

### Useful variations

```bash
make DEPTH=64 DATA_WIDTH=32     # different configuration
make SEED=1234                  # reproduce a specific random run
make RANDOM_CYCLES=20000        # longer random phases
make WAVES=1                    # waveform in sim_build/sync_fifo.fst (open with GTKWave or Surfer)
./scripts/mutation_check.sh     # prove the testbench catches bugs
make clean
```

## Limitations and next steps

- This is a cocotb testbench with UVM-style roles (driver, monitor,
  scoreboard, coverage), not UVM itself. Real UVM needs a commercial simulator
  (VCS, Questa, Xcelium).
- Functional coverage is hand-rolled counters. SystemVerilog covergroups and
  SVA assertions need a simulator that supports them.
- Ideas to extend: SVA properties bound to the DUT, an asynchronous (dual-clock)
  FIFO with gray-code pointers, a registered-output variant, and a coverage
  report in CI.
