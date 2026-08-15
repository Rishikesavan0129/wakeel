// wakeel_alu.v
// Small, registered, parameterized ALU -- deliberately minimal so a full
// OpenLane synth/place/route cycle finishes in minutes, not hours, making
// it a fast proof-of-concept target for testing the Wakeel flow end to end
// on a design other than hafiz_core.
//
// Design choices, and why:
// - WIDTH parameterized (default 16) so you can trivially make it smaller
//   (8) for an even faster first run, or larger to stress the flow more.
// - Output is REGISTERED (not combinational passthrough) on purpose: an
//   ALU with a purely combinational datapath and no register at all gives
//   OpenLane's STA nothing to check between clock edges, which defeats the
//   point of a "run this at N MHz" proof of concept. One register stage
//   after the combinational ALU core gives a real, meaningful timing path
//   (operand -> mux -> adder/logic -> register) for the frequency-aware
//   physical_profile logic to actually be tested against.
// - Flags (zero/carry/overflow) computed alongside result, registered
//   together -- a realistic small-ALU feature set, not a toy adder.
// - Synchronous active-low reset (rst_n), matching the clk/rst_n
//   convention already assumed elsewhere in this codebase (mujeeb_router,
//   etc.) for consistency across your own designs.

module wakeel_alu #(
    parameter WIDTH = 16
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  valid_in,
    input  wire [3:0]            opcode,
    input  wire [WIDTH-1:0]      operand_a,
    input  wire [WIDTH-1:0]      operand_b,

    output reg  [WIDTH-1:0]      result,
    output reg                   result_valid,
    output reg                   flag_zero,
    output reg                   flag_carry,
    output reg                   flag_overflow
);

    localparam OP_ADD  = 4'h0;
    localparam OP_SUB  = 4'h1;
    localparam OP_AND  = 4'h2;
    localparam OP_OR   = 4'h3;
    localparam OP_XOR  = 4'h4;
    localparam OP_NOT  = 4'h5;
    localparam OP_SLL  = 4'h6;
    localparam OP_SRL  = 4'h7;
    localparam OP_SRA  = 4'h8;
    localparam OP_SLT  = 4'h9;
    localparam OP_SLTU = 4'hA;
    localparam OP_PASS = 4'hB;

    reg  [WIDTH-1:0] alu_result;
    reg              alu_carry;
    reg              alu_overflow;

    wire [WIDTH:0] add_ext  = {1'b0, operand_a} + {1'b0, operand_b};
    wire [WIDTH:0] sub_ext  = {1'b0, operand_a} - {1'b0, operand_b};
    wire           add_ovf  = (operand_a[WIDTH-1] == operand_b[WIDTH-1]) &&
                               (add_ext[WIDTH-1] != operand_a[WIDTH-1]);
    wire           sub_ovf  = (operand_a[WIDTH-1] != operand_b[WIDTH-1]) &&
                               (sub_ext[WIDTH-1] != operand_a[WIDTH-1]);

    always @(*) begin
        alu_carry    = 1'b0;
        alu_overflow = 1'b0;
        case (opcode)
            OP_ADD:  begin alu_result = add_ext[WIDTH-1:0]; alu_carry = add_ext[WIDTH]; alu_overflow = add_ovf; end
            OP_SUB:  begin alu_result = sub_ext[WIDTH-1:0]; alu_carry = sub_ext[WIDTH]; alu_overflow = sub_ovf; end
            OP_AND:  alu_result = operand_a & operand_b;
            OP_OR:   alu_result = operand_a | operand_b;
            OP_XOR:  alu_result = operand_a ^ operand_b;
            OP_NOT:  alu_result = ~operand_a;
            OP_SLL:  alu_result = operand_a << operand_b[$clog2(WIDTH)-1:0];
            OP_SRL:  alu_result = operand_a >> operand_b[$clog2(WIDTH)-1:0];
            OP_SRA:  alu_result = $signed(operand_a) >>> operand_b[$clog2(WIDTH)-1:0];
            OP_SLT:  alu_result = ($signed(operand_a) < $signed(operand_b)) ? {{(WIDTH-1){1'b0}}, 1'b1} : {WIDTH{1'b0}};
            OP_SLTU: alu_result = (operand_a < operand_b) ? {{(WIDTH-1){1'b0}}, 1'b1} : {WIDTH{1'b0}};
            OP_PASS: alu_result = operand_a;
            default: alu_result = {WIDTH{1'b0}};
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result        <= {WIDTH{1'b0}};
            result_valid  <= 1'b0;
            flag_zero     <= 1'b0;
            flag_carry    <= 1'b0;
            flag_overflow <= 1'b0;
        end else begin
            result        <= alu_result;
            result_valid  <= valid_in;
            flag_zero     <= (alu_result == {WIDTH{1'b0}});
            flag_carry    <= alu_carry;
            flag_overflow <= alu_overflow;
        end
    end

endmodule
