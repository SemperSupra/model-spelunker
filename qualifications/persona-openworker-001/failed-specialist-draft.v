module fifo4(
  input  logic       clk,
  input  logic       reset,
  input  logic       wr_en,
  input  logic       rd_en,
  input  logic [7:0] wr_data,
  output logic [7:0] rd_data,
  output logic       full,
  output logic       empty
);

  reg [7:0] mem [0:3];
  reg [1:0] wr_ptr;
  reg [1:0] rd_ptr;
  reg [1:0] occupancy;

  always @(posedge clk) begin
    if (reset) begin
      wr_ptr <= 2'b00;
      rd_ptr <= 2'b00;
      occupancy <= 2'b00;
    end else begin
      if (wr_en && !full) begin
        mem[wr_ptr] <= wr_data;
        wr_ptr <= wr_ptr + 1;
        occupancy <= occupancy + 1;
      end
      if (rd_en && !empty) begin
        rd_data <= mem[rd_ptr];
        rd_ptr <= rd_ptr + 1;
        occupancy <= occupancy - 1;
      end
    end
  end

  assign full = (occupancy == 2'b100);
  assign empty = (occupancy == 2'b00);

endmodule
