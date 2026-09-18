module fifo4(
  input logic clk, input logic reset, input logic wr_en, input logic rd_en,
  input logic [7:0] wr_data, output logic [7:0] rd_data,
  output logic full, output logic empty
);
  logic [7:0] mem [0:3];
  logic [1:0] wptr, rptr;
  logic [2:0] count;
  assign empty = (count == 0);
  assign full = (count == 4);
  always_ff @(posedge clk) begin
    if (reset) begin
      wptr <= 0; rptr <= 0; count <= 0; rd_data <= 0;
    end else begin
      case ({(wr_en && !full),(rd_en && !empty)})
        2'b10: begin mem[wptr] <= wr_data; wptr <= wptr + 1'b1; count <= count + 1'b1; end
        2'b01: begin rd_data <= mem[rptr]; rptr <= rptr + 1'b1; count <= count - 1'b1; end
        2'b11: begin
          mem[wptr] <= wr_data; wptr <= wptr + 1'b1;
          rd_data <= mem[rptr]; rptr <= rptr + 1'b1;
        end
        default: begin end
      endcase
    end
  end
endmodule
