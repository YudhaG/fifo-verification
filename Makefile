# Run with:  make                      (defaults: DEPTH=16, DATA_WIDTH=8)
#            make DEPTH=64 DATA_WIDTH=32
#            make SEED=1234            (reproduce a random run)
#            make WAVES=1              (dump waveform into sim_build/)
#            make clean

SIM                 ?= icarus
TOPLEVEL_LANG       := verilog
COCOTB_TOPLEVEL     := sync_fifo
COCOTB_TEST_MODULES := test_sync_fifo

DEPTH      ?= 16
DATA_WIDTH ?= 8
VERILOG_SOURCES ?= $(CURDIR)/rtl/sync_fifo.sv

# The testbench reads DEPTH / DATA_WIDTH from the environment so it always
# matches the DUT build.
export DEPTH DATA_WIDTH

COMPILE_ARGS += -g2012 -Psync_fifo.DEPTH=$(DEPTH) -Psync_fifo.DATA_WIDTH=$(DATA_WIDTH)

export PYTHONPATH := $(CURDIR)/tb:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
