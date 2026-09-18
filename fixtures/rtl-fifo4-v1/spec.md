# rtl-fifo4-v1

Implement a synthesizable SystemVerilog module:

```systemverilog
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
```

Behavior:

- FIFO depth is exactly 4 entries; each entry is 8 bits.
- `reset` is synchronous and active high. On the rising edge while `reset=1`, the FIFO becomes empty.
- A write is accepted on a rising edge iff `wr_en=1` and the FIFO is not full immediately before that edge.
- A read is accepted on a rising edge iff `rd_en=1` and the FIFO is not empty immediately before that edge.
- If both operations are accepted on the same edge, FIFO occupancy is unchanged.
- If the FIFO is full immediately before an edge with both `wr_en=1` and `rd_en=1`, only the read is accepted.
- If the FIFO is empty immediately before an edge with both `wr_en=1` and `rd_en=1`, only the write is accepted.
- On an accepted read, `rd_data` is updated to the value removed from the FIFO.
- Reads from empty and writes to full are ignored.
- `empty` is asserted exactly when occupancy is zero.
- `full` is asserted exactly when occupancy is four.
- Preserve FIFO ordering across pointer wrap-around.

No vendor primitives or external dependencies.
