// Synchronous FIFO, first-word-fall-through (FWFT).
//
//  - rd_data always shows the oldest entry; it is valid whenever !empty.
//  - A write while full and a read while empty are silently ignored.
//  - Simultaneous write + read is allowed in the same cycle.
//  - Asynchronous active-low reset (rst_n) clears the pointers and count.
//
// DEPTH must be a power of two and >= 2 so the pointers wrap naturally.
module sync_fifo #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH      = 16
) (
    input  logic                    clk,
    input  logic                    rst_n,

    input  logic                    wr_en,
    input  logic [DATA_WIDTH-1:0]   wr_data,

    input  logic                    rd_en,
    output logic [DATA_WIDTH-1:0]   rd_data,

    output logic                    full,
    output logic                    empty,
    output logic [$clog2(DEPTH):0]  count
);

  localparam int AW = $clog2(DEPTH);

  logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];
  logic [AW-1:0]         wr_ptr;
  logic [AW-1:0]         rd_ptr;

  wire do_write = wr_en && !full;
  wire do_read  = rd_en && !empty;

  assign full    = (count == DEPTH);
  assign empty   = (count == 0);
  assign rd_data = mem[rd_ptr];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      count  <= '0;
    end else begin
      if (do_write) begin
        mem[wr_ptr] <= wr_data;
        wr_ptr      <= wr_ptr + 1'b1;
      end
      if (do_read) begin
        rd_ptr <= rd_ptr + 1'b1;
      end
      case ({do_write, do_read})
        2'b10:   count <= count + 1'b1;
        2'b01:   count <= count - 1'b1;
        default: ;  // idle, or write+read together: occupancy unchanged
      endcase
    end
  end

endmodule
