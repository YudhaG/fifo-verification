"""cocotb testbench for rtl/sync_fifo.sv.

Structure (UVM-flavoured, in plain Python):
  - FifoEnv.cycle()    : driver  - applies one cycle of stimulus
  - FifoEnv._monitor() : monitor + scoreboard - samples the DUT pins every
                         clock edge, runs a reference model (a deque) in
                         lock-step, and checks count/full/empty/data
  - Coverage           : functional coverage bins, closed in the random test

Knobs (environment variables, all optional):
  DEPTH, DATA_WIDTH : must match what the DUT was compiled with (Makefile does this)
  SEED              : reproduce a random run, e.g.  make SEED=1234
  RANDOM_CYCLES     : cycles per random phase (default 3000)
"""

import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

DEPTH = int(os.environ.get("DEPTH", "16"))
WIDTH = int(os.environ.get("DATA_WIDTH", "8"))
MASK = (1 << WIDTH) - 1
RANDOM_CYCLES = int(os.environ.get("RANDOM_CYCLES", "3000"))


class Coverage:
    """Functional coverage: named corner-case bins plus every occupancy level."""

    BINS = (
        "reached_full",
        "reached_empty",
        "write_when_full",
        "read_when_empty",
        "simul_rw",
        "simul_rw_at_full",
        "simul_rw_at_empty",
        "wptr_wrap",
        "rptr_wrap",
    )

    def __init__(self):
        self.hits = dict.fromkeys(self.BINS, 0)
        self.levels = set()

    def hit(self, name):
        self.hits[name] += 1

    def holes(self):
        holes = [b for b, n in self.hits.items() if n == 0]
        holes += [f"count=={c}" for c in range(DEPTH + 1) if c not in self.levels]
        return holes

    def report(self, log):
        log.info("---- functional coverage ----")
        for name, n in self.hits.items():
            log.info(f"  {name:<20} {n:>8}  {'HIT' if n else 'MISSING'}")
        seen = len(self.levels)
        log.info(f"  occupancy levels     {seen:>3}/{DEPTH + 1}")
        log.info(f"  holes: {self.holes() or 'none'}")


class FifoEnv:
    def __init__(self, dut):
        self.dut = dut
        self.seed = int(os.environ.get("SEED", random.SystemRandom().randrange(2**32)))
        self.rng = random.Random(self.seed)
        self.model = deque()  # reference model: what the FIFO should hold
        self.cov = Coverage()
        self.total_wr = 0
        self.total_rd = 0
        self.checks = 0
        dut._log.info(f"DEPTH={DEPTH} DATA_WIDTH={WIDTH} SEED={self.seed}")

    # ---- driver ---------------------------------------------------------
    async def reset(self):
        dut = self.dut
        dut.wr_en.value = 0
        dut.rd_en.value = 0
        dut.wr_data.value = 0
        dut.rst_n.value = 0
        cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
        await ClockCycles(dut.clk, 3)
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)
        cocotb.start_soon(self._monitor())

    async def pulse_reset(self):
        """Assert reset in the middle of a test (monitor clears its model)."""
        dut = self.dut
        dut.wr_en.value = 0
        dut.rd_en.value = 0
        dut.rst_n.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)

    async def cycle(self, wr=False, rd=False, data=None):
        if data is None:
            data = self.rng.getrandbits(WIDTH)
        self.dut.wr_en.value = int(wr)
        self.dut.rd_en.value = int(rd)
        self.dut.wr_data.value = data
        await RisingEdge(self.dut.clk)

    async def idle(self, n=1):
        for _ in range(n):
            await self.cycle()

    async def drain(self):
        while self.model:
            await self.cycle(rd=True)
        await self.idle(2)

    # ---- monitor + scoreboard ------------------------------------------
    async def _monitor(self):
        dut, model, cov = self.dut, self.model, self.cov
        while True:
            await RisingEdge(dut.clk)
            # Values read here are the ones the DUT samples at this edge
            # (pre-update), so the model can be advanced in lock-step.
            if not int(dut.rst_n.value):
                model.clear()
                self.total_wr = self.total_rd = 0
                continue

            n = len(model)
            count = int(dut.count.value)
            full = int(dut.full.value)
            empty = int(dut.empty.value)
            assert count == n, f"count mismatch: dut={count} model={n}"
            assert full == int(n == DEPTH), f"full mismatch: dut={full} model_count={n}"
            assert empty == int(n == 0), f"empty mismatch: dut={empty} model_count={n}"

            wr = int(dut.wr_en.value)
            rd = int(dut.rd_en.value)
            do_wr = bool(wr) and n < DEPTH
            do_rd = bool(rd) and n > 0

            # coverage sampling
            cov.levels.add(n)
            if full:
                cov.hit("reached_full")
            if empty:
                cov.hit("reached_empty")
            if wr and n == DEPTH:
                cov.hit("write_when_full")
            if rd and n == 0:
                cov.hit("read_when_empty")
            if wr and rd:
                cov.hit("simul_rw")
                if n == DEPTH:
                    cov.hit("simul_rw_at_full")
                if n == 0:
                    cov.hit("simul_rw_at_empty")

            # scoreboard: oldest entry must be on rd_data, in order
            if do_rd:
                got = int(dut.rd_data.value)
                exp = model.popleft()
                assert got == exp, f"data mismatch: dut=0x{got:x} expected=0x{exp:x}"
                self.total_rd += 1
                if self.total_rd >= DEPTH:
                    cov.hit("rptr_wrap")
            if do_wr:
                model.append(int(dut.wr_data.value) & MASK)
                self.total_wr += 1
                if self.total_wr >= DEPTH:
                    cov.hit("wptr_wrap")
            self.checks += 1


# =========================================================================
# Tests
# =========================================================================
@cocotb.test()
async def test_reset_state(dut):
    """Reset leaves the FIFO empty; a mid-test reset discards contents."""
    env = FifoEnv(dut)
    await env.reset()
    await env.idle(2)
    assert int(dut.empty.value) == 1
    assert int(dut.full.value) == 0
    assert int(dut.count.value) == 0

    for _ in range(DEPTH // 2 + 1):
        await env.cycle(wr=True)
    await env.idle(1)
    assert int(dut.count.value) == DEPTH // 2 + 1

    await env.pulse_reset()
    await env.idle(1)
    assert int(dut.empty.value) == 1
    assert int(dut.count.value) == 0

    # still usable after reset: one entry in, same entry out
    await env.cycle(wr=True, data=0xA5 & MASK)
    await env.cycle(rd=True)
    await env.idle(2)
    assert int(dut.empty.value) == 1


@cocotb.test()
async def test_fill_and_drain(dut):
    """Fill to full, overflow attempts ignored, drain in order, underflow ignored."""
    env = FifoEnv(dut)
    await env.reset()

    for _ in range(DEPTH):
        await env.cycle(wr=True)
    await env.idle(1)
    assert int(dut.full.value) == 1
    assert int(dut.count.value) == DEPTH

    for _ in range(3):  # overflow attempts: must not change anything
        await env.cycle(wr=True)
    await env.idle(1)
    assert int(dut.count.value) == DEPTH

    for _ in range(DEPTH):  # scoreboard checks every word and its order
        await env.cycle(rd=True)
    await env.idle(1)
    assert int(dut.empty.value) == 1

    for _ in range(3):  # underflow attempts: must not change anything
        await env.cycle(rd=True)
    await env.idle(1)
    assert int(dut.count.value) == 0
    assert not env.model


@cocotb.test()
async def test_simultaneous_rw(dut):
    """Write and read in the same cycle: mid-level, at full, and at empty."""
    env = FifoEnv(dut)
    await env.reset()

    half = DEPTH // 2
    for _ in range(half):
        await env.cycle(wr=True)
    for _ in range(4 * DEPTH):  # steady state: occupancy must not move
        await env.cycle(wr=True, rd=True)
    await env.idle(1)
    assert int(dut.count.value) == half

    for _ in range(DEPTH - half):  # go to full
        await env.cycle(wr=True)
    for _ in range(6):  # at full: write is blocked, read still happens
        await env.cycle(wr=True, rd=True)

    await env.drain()  # go to empty
    for _ in range(6):  # at empty: read is blocked, write still happens
        await env.cycle(wr=True, rd=True)
    await env.drain()


@cocotb.test()
async def test_random(dut):
    """Constrained-random traffic in several bias phases, then close coverage."""
    env = FifoEnv(dut)
    await env.reset()

    phases = [  # (P(write), P(read)) per cycle
        (0.80, 0.20),  # write-heavy: hits full
        (0.20, 0.80),  # read-heavy: hits empty
        (0.50, 0.50),  # balanced
        (0.95, 0.95),  # back-to-back both ways
        (1.00, 0.30),
        (0.30, 1.00),
        (0.00, 1.00),  # flush
    ]
    for p_wr, p_rd in phases:
        for _ in range(RANDOM_CYCLES):
            await env.cycle(
                wr=env.rng.random() < p_wr,
                rd=env.rng.random() < p_rd,
            )
    await env.drain()

    env.cov.report(dut._log)
    dut._log.info(f"scoreboard checked {env.checks} cycles, "
                  f"{env.total_wr} writes / {env.total_rd} reads since last reset")
    holes = env.cov.holes()
    assert not holes, f"coverage holes: {holes}"
