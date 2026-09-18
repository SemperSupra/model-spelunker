module tb;
  logic clk = 0;
  logic reset = 0;
  logic wr_en = 0;
  logic rd_en = 0;
  logic [7:0] wr_data = 0;
  logic [7:0] rd_data;
  logic full;
  logic empty;

  integer failures = 0;
  integer m_head = 0;
  integer m_tail = 0;
  integer m_count = 0;
  integer i;
  reg [31:0] lfsr = 32'h1ACEB00C;
  reg [7:0] model_mem [0:511];

  fifo4 dut(
    .clk(clk),
    .reset(reset),
    .wr_en(wr_en),
    .rd_en(rd_en),
    .wr_data(wr_data),
    .rd_data(rd_data),
    .full(full),
    .empty(empty)
  );

  always #5 clk = ~clk;

  task check_flags;
    begin
      if (empty !== (m_count == 0)) begin
        $display("FAIL empty=%b expected=%b count=%0d", empty, (m_count == 0), m_count);
        failures = failures + 1;
      end
      if (full !== (m_count == 4)) begin
        $display("FAIL full=%b expected=%b count=%0d", full, (m_count == 4), m_count);
        failures = failures + 1;
      end
    end
  endtask

  task cycle;
    input integer we;
    input integer re;
    input [7:0] wd;
    integer write_accept;
    integer read_accept;
    reg [7:0] expected_read;
    begin
      @(negedge clk);
      wr_en = we;
      rd_en = re;
      wr_data = wd;

      write_accept = we && (m_count < 4);
      read_accept = re && (m_count > 0);
      if (read_accept)
        expected_read = model_mem[m_head];

      @(posedge clk);
      #1;

      if (read_accept && rd_data !== expected_read) begin
        $display("FAIL read data=%02x expected=%02x count_before=%0d", rd_data, expected_read, m_count);
        failures = failures + 1;
      end

      if (read_accept) begin
        m_head = m_head + 1;
        m_count = m_count - 1;
      end
      if (write_accept) begin
        model_mem[m_tail] = wd;
        m_tail = m_tail + 1;
        m_count = m_count + 1;
      end

      check_flags();
    end
  endtask

  initial begin
    reset = 1;
    wr_en = 0;
    rd_en = 0;
    @(posedge clk);
    #1;
    m_head = 0;
    m_tail = 0;
    m_count = 0;
    check_flags();

    @(negedge clk);
    reset = 0;

    // Fill and full-write blocking.
    cycle(1, 0, 8'hA0);
    cycle(1, 0, 8'hA1);
    cycle(1, 0, 8'hA2);
    cycle(1, 0, 8'hA3);
    cycle(1, 0, 8'hEE);

    // Full + simultaneous: read only under this specification.
    cycle(1, 1, 8'hB0);

    // Now simultaneous read/write is accepted both ways.
    cycle(1, 1, 8'hB1);

    // Drain and empty-read blocking.
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);

    // Empty + simultaneous: write only.
    cycle(1, 1, 8'hC0);
    cycle(0, 1, 8'h00);

    // Force pointer wrap-around.
    cycle(1, 0, 8'hC1);
    cycle(1, 0, 8'hC2);
    cycle(0, 1, 8'h00);
    cycle(1, 0, 8'hC3);
    cycle(1, 0, 8'hC4);
    cycle(1, 0, 8'hC5);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);
    cycle(0, 1, 8'h00);

    // Deterministic pseudo-random mixed traffic with scoreboard.
    for (i = 0; i < 96; i = i + 1) begin
      lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
      cycle(lfsr[0], lfsr[1], lfsr[15:8]);
    end

    // Drain anything remaining and verify terminal empty state.
    while (m_count > 0)
      cycle(0, 1, 8'h00);

    cycle(0, 1, 8'h00);

    if (failures == 0) begin
      $display("PASS");
      $finish(0);
    end else begin
      $display("FAILURES=%0d", failures);
      $finish(1);
    end
  end
endmodule
