`timescale 1ns/1ps
module tb_wakeel_alu;
    reg clk = 0, rst_n = 0, valid_in = 0;
    reg [3:0] opcode;
    reg [15:0] a, b;
    wire [15:0] result;
    wire result_valid, flag_zero, flag_carry, flag_overflow;
    integer errors = 0;

    wakeel_alu #(.WIDTH(16)) dut (
        .clk(clk), .rst_n(rst_n), .valid_in(valid_in), .opcode(opcode),
        .operand_a(a), .operand_b(b), .result(result), .result_valid(result_valid),
        .flag_zero(flag_zero), .flag_carry(flag_carry), .flag_overflow(flag_overflow)
    );

    always #5 clk = ~clk;

    task check(input [15:0] expected, input [127:0] label);
        begin
            if (result !== expected) begin
                $display("FAIL [%0s]: expected=%0d got=%0d", label, expected, result);
                errors = errors + 1;
            end else begin
                $display("PASS [%0s]: %0d", label, result);
            end
        end
    endtask

    initial begin
        rst_n = 0; valid_in = 0; opcode = 0; a = 0; b = 0;
        @(posedge clk); @(posedge clk);
        rst_n = 1;

        // ADD
        @(negedge clk); opcode=4'h0; a=16'd100; b=16'd50; valid_in=1;
        @(posedge clk); @(negedge clk); check(150, "ADD 100+50");

        // SUB
        opcode=4'h1; a=16'd100; b=16'd50;
        @(posedge clk); @(negedge clk); check(50, "SUB 100-50");

        // AND
        opcode=4'h2; a=16'hFF00; b=16'h0FF0;
        @(posedge clk); @(negedge clk); check(16'h0F00, "AND");

        // OR
        opcode=4'h3; a=16'hFF00; b=16'h00FF;
        @(posedge clk); @(negedge clk); check(16'hFFFF, "OR");

        // XOR
        opcode=4'h4; a=16'hFFFF; b=16'h0F0F;
        @(posedge clk); @(negedge clk); check(16'hF0F0, "XOR");

        // SLL
        opcode=4'h6; a=16'h0001; b=16'd4;
        @(posedge clk); @(negedge clk); check(16'h0010, "SLL");

        // SRL
        opcode=4'h7; a=16'h0010; b=16'd4;
        @(posedge clk); @(negedge clk); check(16'h0001, "SRL");

        // SLT (signed): -1 < 1 -> true
        opcode=4'h9; a=16'hFFFF; b=16'h0001;
        @(posedge clk); @(negedge clk); check(16'h0001, "SLT -1<1");

        // SLTU (unsigned): 0xFFFF < 1 -> false
        opcode=4'hA; a=16'hFFFF; b=16'h0001;
        @(posedge clk); @(negedge clk); check(16'h0000, "SLTU 65535<1");

        if (errors == 0)
            $display("ALL TESTS PASSED");
        else
            $display("%0d TEST(S) FAILED", errors);
        $finish;
    end
endmodule
