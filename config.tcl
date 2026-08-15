# ===== WAKEEL GENERATED OPENLANE CONFIG.TCL (schema-driven, dynamically expandable) =====
set ::env(CELL_PAD) 4.0
set ::env(CLOCK_PERIOD) 20.0
set ::env(CLOCK_PORT) "clk"
set ::env(CTS_MAX_CAP) 1.0
set ::env(CTS_TARGET_SKEW) 200.0
set ::env(DIE_AREA) "0 0 1500 1500"
set ::env(DIODE_INSERTION_STRATEGY) 3
set ::env(DRT_OPT_ITERS) 64
set ::env(FP_ASPECT_RATIO) 1.0
set ::env(FP_CORE_UTIL) 45.0
set ::env(FP_IO_HMETAL) 4
set ::env(FP_IO_MODE) "random_equidistant"
set ::env(FP_IO_VMETAL) 3
set ::env(FP_PDN_CORE_RING) 0
set ::env(FP_PDN_ENABLE_RAILS) 1
set ::env(FP_PDN_HALO) "10 10"
set ::env(FP_PDN_HPITCH) 153.6
set ::env(FP_PDN_HWIDTH) 1.6
set ::env(FP_PDN_VPITCH) 153.18
set ::env(FP_PDN_VWIDTH) 1.6
set ::env(FP_SIZING) "relative"
set ::env(FP_TAPCELL_DIST) 20.0
set ::env(GLB_RESIZER_DESIGN_OPTIMIZATIONS) 0
set ::env(GLB_RESIZER_HOLD_SLACK_MARGIN) 0.1
set ::env(GLB_RESIZER_MAX_CAP_MARGIN) 0.1
set ::env(GLB_RESIZER_MAX_SLEW_MARGIN) 0.1
set ::env(GLB_RESIZER_TIMING_OPTIMIZATIONS) 0
set ::env(GND_NETS) "VGND"
set ::env(GRT_ADJUSTMENT) 0.15
set ::env(GRT_ANT_ITERS) 3
set ::env(GRT_MAX_DIODE_INS_ITERS) 3
set ::env(GRT_OVERFLOW_ITERS) 50
set ::env(LVS_INSERT_POWER_PINS) 1
set ::env(MACRO_PLACEMENT_STATUS) "INFERRED"
set ::env(MAGIC_DRC_USE_GDS) 0
set ::env(MAGIC_EXT_USE_GDS) 0
set ::env(MAGIC_GENERATE_GDS) 1
set ::env(MAGIC_ZEROIZE_ORIGIN) 1
set ::env(MAX_FANOUT_CONSTRAINT) 20
set ::env(MAX_ROUTING_LAYER) "met5"
set ::env(MAX_WIRE_LENGTH) 0.0
set ::env(MIN_ROUTING_LAYER) "met1"
set ::env(PDK) "sky130A"
set ::env(PL_RANDOM_GLB_PLACEMENT) 0
set ::env(PL_RESIZER_DESIGN_OPTIMIZATIONS) 0
set ::env(PL_RESIZER_HOLD_MAX_BUFFER_PERCENT) 20
set ::env(PL_RESIZER_HOLD_SLACK_MARGIN) 0.1
set ::env(PL_RESIZER_MAX_CAP_MARGIN) 0.1
set ::env(PL_RESIZER_MAX_SLEW_MARGIN) 0.1
set ::env(PL_RESIZER_TIMING_OPTIMIZATIONS) 0
set ::env(PL_TARGET_DENSITY) 0.55
set ::env(QUIT_ON_MAGIC_DRC) 0
set ::env(QUIT_ON_WARNINGS) 0
set ::env(ROUTING_CORES) 4
set ::env(RUN_CVC) 0
set ::env(RUN_FILL_INSERTION) 1
set ::env(RUN_KLAYOUT) 1
set ::env(RUN_LINTER) 0
set ::env(RUN_LVS) 1
set ::env(RUN_MAGIC_DRC) 1
set ::env(RUN_SPEF_EXTRACTION) 1
set ::env(RUN_TAP_DECAP_INSERTION) 1
set ::env(SPEF_EXTRACTOR) "openroad"
set ::env(STD_CELL_LIBRARY) "sky130_fd_sc_hd"
set ::env(SYNTH_BUFFERING) 1
set ::env(SYNTH_CLOCK_TRANSITION) 0.15
set ::env(SYNTH_CLOCK_UNCERTAINTY) 0.25
set ::env(SYNTH_ELABORATE_ONLY) 0
set ::env(SYNTH_FLAT_TOP) 0
set ::env(SYNTH_MAX_FANOUT) 20
set ::env(SYNTH_NO_FLAT) 0
set ::env(SYNTH_READ_BLACKBOX_LIB) 0
set ::env(SYNTH_STRATEGY) "AREA 0"
set ::env(SYNTH_TIMING_DERATE) 0.05
set ::env(USE_ARC_ANTENNA_CHECK) 1
set ::env(VDD_NETS) "VPWR"
set ::env(VERILATOR_RELAX) 0
# WARN: 'BOTTOM_MARGIN_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(BOTTOM_MARGIN_MULT) "4"
# WARN: 'CLOCK_BUFFER_FANOUT' not in schema for tool=openlane -- emitted best-effort
set ::env(CLOCK_BUFFER_FANOUT) "16"
# WARN: 'CTS_CLK_MAX_WIRE_LENGTH' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_CLK_MAX_WIRE_LENGTH) "0"
# WARN: 'CTS_DISABLE_POST_PROCESSING' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_DISABLE_POST_PROCESSING) "0"
# WARN: 'CTS_DISTANCE_BETWEEN_BUFFERS' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_DISTANCE_BETWEEN_BUFFERS) "0"
# WARN: 'CTS_MULTICORNER_LIB' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_MULTICORNER_LIB) "1"
# WARN: 'CTS_REPORT_TIMING' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_REPORT_TIMING) "1"
# WARN: 'CTS_SINK_CLUSTERING_MAX_DIAMETER' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_SINK_CLUSTERING_MAX_DIAMETER) "50"
# WARN: 'CTS_SINK_CLUSTERING_SIZE' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_SINK_CLUSTERING_SIZE) "25"
# WARN: 'CTS_TOLERANCE' not in schema for tool=openlane -- emitted best-effort
set ::env(CTS_TOLERANCE) "100"
# WARN: 'DESIGN_IS_CORE' not in schema for tool=openlane -- emitted best-effort
set ::env(DESIGN_IS_CORE) "1"
# WARN: 'DIODE_PADDING' not in schema for tool=openlane -- emitted best-effort
set ::env(DIODE_PADDING) "2"
# WARN: 'FP_IO_HEXTEND' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_HEXTEND) "0"
# WARN: 'FP_IO_HLENGTH' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_HLENGTH) "4"
# WARN: 'FP_IO_HTHICKNESS_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_HTHICKNESS_MULT) "2"
# WARN: 'FP_IO_MIN_DISTANCE' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_MIN_DISTANCE) "3"
# WARN: 'FP_IO_UNMATCHED_ERROR' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_UNMATCHED_ERROR) "1"
# WARN: 'FP_IO_VEXTEND' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_VEXTEND) "0"
# WARN: 'FP_IO_VLENGTH' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_VLENGTH) "4"
# WARN: 'FP_IO_VTHICKNESS_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_IO_VTHICKNESS_MULT) "2"
# WARN: 'FP_PDN_AUTO_ADJUST' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_AUTO_ADJUST) "1"
# WARN: 'FP_PDN_CHECK_NODES' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_CHECK_NODES) "1"
# WARN: 'FP_PDN_ENABLE_GLOBAL_CONNECTIONS' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_ENABLE_GLOBAL_CONNECTIONS) "1"
# WARN: 'FP_PDN_ENABLE_MACROS_GRID' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_ENABLE_MACROS_GRID) "1"
# WARN: 'FP_PDN_HORIZONTAL_HALO' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_HORIZONTAL_HALO) "10"
# WARN: 'FP_PDN_IRDROP' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_IRDROP) "1"
# WARN: 'FP_PDN_SKIPTRIM' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_PDN_SKIPTRIM) "0"
# WARN: 'FP_TAP_HORIZONTAL_HALO' not in schema for tool=openlane -- emitted best-effort
set ::env(FP_TAP_HORIZONTAL_HALO) "10"
# WARN: 'GLB_OPTIMIZE_MIRRORING' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_OPTIMIZE_MIRRORING) "1"
# WARN: 'GLB_RESIZER_ALLOW_SETUP_VIOS' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_RESIZER_ALLOW_SETUP_VIOS) "0"
# WARN: 'GLB_RESIZER_HOLD_MAX_BUFFER_PERCENT' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_RESIZER_HOLD_MAX_BUFFER_PERCENT) "50"
# WARN: 'GLB_RESIZER_MAX_WIRE_LENGTH' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_RESIZER_MAX_WIRE_LENGTH) "0"
# WARN: 'GLB_RESIZER_SETUP_MAX_BUFFER_PERCENT' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_RESIZER_SETUP_MAX_BUFFER_PERCENT) "50"
# WARN: 'GLB_RESIZER_SETUP_SLACK_MARGIN' not in schema for tool=openlane -- emitted best-effort
set ::env(GLB_RESIZER_SETUP_SLACK_MARGIN) "0.025"
# WARN: 'GRT_ALLOW_CONGESTION' not in schema for tool=openlane -- emitted best-effort
set ::env(GRT_ALLOW_CONGESTION) "0"
# WARN: 'GRT_ANT_MARGIN' not in schema for tool=openlane -- emitted best-effort
set ::env(GRT_ANT_MARGIN) "10"
# WARN: 'GRT_ESTIMATE_PARASITICS' not in schema for tool=openlane -- emitted best-effort
set ::env(GRT_ESTIMATE_PARASITICS) "1"
# WARN: 'GRT_MACRO_EXTENSION' not in schema for tool=openlane -- emitted best-effort
set ::env(GRT_MACRO_EXTENSION) "0"
# WARN: 'GRT_REPAIR_ANTENNAS' not in schema for tool=openlane -- emitted best-effort
set ::env(GRT_REPAIR_ANTENNAS) "1"
# WARN: 'HEURISTIC_ANTENNA_INSERTION_MODE' not in schema for tool=openlane -- emitted best-effort
set ::env(HEURISTIC_ANTENNA_INSERTION_MODE) "source"
# WARN: 'HEURISTIC_ANTENNA_THRESHOLD' not in schema for tool=openlane -- emitted best-effort
set ::env(HEURISTIC_ANTENNA_THRESHOLD) "90"
# WARN: 'IO_PCT' not in schema for tool=openlane -- emitted best-effort
set ::env(IO_PCT) "0.2"
# WARN: 'KLAYOUT_DRC_KLAYOUT_GDS' not in schema for tool=openlane -- emitted best-effort
set ::env(KLAYOUT_DRC_KLAYOUT_GDS) "0"
# WARN: 'KLAYOUT_XOR_GDS' not in schema for tool=openlane -- emitted best-effort
set ::env(KLAYOUT_XOR_GDS) "1"
# WARN: 'KLAYOUT_XOR_IGNORE_LAYERS' not in schema for tool=openlane -- emitted best-effort
set ::env(KLAYOUT_XOR_IGNORE_LAYERS) ""
# WARN: 'KLAYOUT_XOR_THREADS' not in schema for tool=openlane -- emitted best-effort
set ::env(KLAYOUT_XOR_THREADS) "1"
# WARN: 'KLAYOUT_XOR_XML' not in schema for tool=openlane -- emitted best-effort
set ::env(KLAYOUT_XOR_XML) "1"
# WARN: 'LEC_ENABLE' not in schema for tool=openlane -- emitted best-effort
set ::env(LEC_ENABLE) "0"
# WARN: 'LEFT_MARGIN_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(LEFT_MARGIN_MULT) "12"
# WARN: 'LINTER_INCLUDE_PDK_MODELS' not in schema for tool=openlane -- emitted best-effort
set ::env(LINTER_INCLUDE_PDK_MODELS) "0"
# WARN: 'LINTER_RELATIVE_INCLUDES' not in schema for tool=openlane -- emitted best-effort
set ::env(LINTER_RELATIVE_INCLUDES) "1"
# WARN: 'LVS_CONNECT_BY_LABEL' not in schema for tool=openlane -- emitted best-effort
set ::env(LVS_CONNECT_BY_LABEL) "0"
# WARN: 'MAGIC_CONVERT_DRC_TO_RDB' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_CONVERT_DRC_TO_RDB) "1"
# WARN: 'MAGIC_DEF_LABELS' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_DEF_LABELS) "1"
# WARN: 'MAGIC_DEF_NO_BLOCKAGES' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_DEF_NO_BLOCKAGES) "1"
# WARN: 'MAGIC_DISABLE_HIER_GDS' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_DISABLE_HIER_GDS) "1"
# WARN: 'MAGIC_GDS_ALLOW_ABSTRACT' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_GDS_ALLOW_ABSTRACT) "0"
# WARN: 'MAGIC_GDS_POLYGON_SUBCELLS' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_GDS_POLYGON_SUBCELLS) "0"
# WARN: 'MAGIC_GENERATE_LEF' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_GENERATE_LEF) "1"
# WARN: 'MAGIC_GENERATE_MAGLEF' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_GENERATE_MAGLEF) "1"
# WARN: 'MAGIC_INCLUDE_GDS_POINTERS' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_INCLUDE_GDS_POINTERS) "0"
# WARN: 'MAGIC_LEF_WRITE_USE_GDS' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_LEF_WRITE_USE_GDS) "0"
# WARN: 'MAGIC_PAD' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_PAD) "0"
# WARN: 'MAGIC_WRITE_FULL_LEF' not in schema for tool=openlane -- emitted best-effort
set ::env(MAGIC_WRITE_FULL_LEF) "0"
# WARN: 'PL_BASIC_PLACEMENT' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_BASIC_PLACEMENT) "0"
# WARN: 'PL_ESTIMATE_PARASITICS' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_ESTIMATE_PARASITICS) "1"
# WARN: 'PL_MAX_DISPLACEMENT_X' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_MAX_DISPLACEMENT_X) "500"
# WARN: 'PL_MAX_DISPLACEMENT_Y' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_MAX_DISPLACEMENT_Y) "100"
# WARN: 'PL_OPTIMIZE_MIRRORING' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_OPTIMIZE_MIRRORING) "1"
# WARN: 'PL_RANDOM_INITIAL_PLACEMENT' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RANDOM_INITIAL_PLACEMENT) "0"
# WARN: 'PL_RESIZER_ALLOW_SETUP_VIOS' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_ALLOW_SETUP_VIOS) "0"
# WARN: 'PL_RESIZER_BUFFER_INPUT_PORTS' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_BUFFER_INPUT_PORTS) "1"
# WARN: 'PL_RESIZER_BUFFER_OUTPUT_PORTS' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_BUFFER_OUTPUT_PORTS) "1"
# WARN: 'PL_RESIZER_MAX_WIRE_LENGTH' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_MAX_WIRE_LENGTH) "0"
# WARN: 'PL_RESIZER_REPAIR_TIE_FANOUT' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_REPAIR_TIE_FANOUT) "1"
# WARN: 'PL_RESIZER_SETUP_MAX_BUFFER_PERCENT' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_SETUP_MAX_BUFFER_PERCENT) "50"
# WARN: 'PL_RESIZER_SETUP_SLACK_MARGIN' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_SETUP_SLACK_MARGIN) "0.05"
# WARN: 'PL_RESIZER_TIE_SEPERATION' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_RESIZER_TIE_SEPERATION) "0"
# WARN: 'PL_ROUTABILITY_DRIVEN' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_ROUTABILITY_DRIVEN) "1"
# WARN: 'PL_SKIP_INITIAL_PLACEMENT' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_SKIP_INITIAL_PLACEMENT) "0"
# WARN: 'PL_TIME_DRIVEN' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_TIME_DRIVEN) "1"
# WARN: 'PL_WIRELENGTH_COEF' not in schema for tool=openlane -- emitted best-effort
set ::env(PL_WIRELENGTH_COEF) "0.25"
# WARN: 'QUIT_ON_ASSIGN_STATEMENTS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_ASSIGN_STATEMENTS) "0"
# WARN: 'QUIT_ON_HOLD_VIOLATIONS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_HOLD_VIOLATIONS) "1"
# WARN: 'QUIT_ON_ILLEGAL_OVERLAPS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_ILLEGAL_OVERLAPS) "1"
# WARN: 'QUIT_ON_LINTER_ERRORS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_LINTER_ERRORS) "1"
# WARN: 'QUIT_ON_LINTER_WARNINGS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_LINTER_WARNINGS) "0"
# WARN: 'QUIT_ON_LONG_WIRE' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_LONG_WIRE) "0"
# WARN: 'QUIT_ON_LVS_ERROR' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_LVS_ERROR) "1"
# WARN: 'QUIT_ON_SETUP_VIOLATIONS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_SETUP_VIOLATIONS) "1"
# WARN: 'QUIT_ON_SYNTH_CHECKS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_SYNTH_CHECKS) "1"
# WARN: 'QUIT_ON_TIMING_VIOLATIONS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_TIMING_VIOLATIONS) "1"
# WARN: 'QUIT_ON_TR_DRC' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_TR_DRC) "1"
# WARN: 'QUIT_ON_UNMAPPED_CELLS' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_UNMAPPED_CELLS) "1"
# WARN: 'QUIT_ON_XOR_ERROR' not in schema for tool=openlane -- emitted best-effort
set ::env(QUIT_ON_XOR_ERROR) "False"
# WARN: 'RCX_MERGE_VIA_WIRE_RES' not in schema for tool=openlane -- emitted best-effort
set ::env(RCX_MERGE_VIA_WIRE_RES) "1"
# WARN: 'RIGHT_MARGIN_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(RIGHT_MARGIN_MULT) "12"
# WARN: 'RSZ_DONT_TOUCH' not in schema for tool=openlane -- emitted best-effort
set ::env(RSZ_DONT_TOUCH) ""
# WARN: 'RSZ_DONT_TOUCH_RX' not in schema for tool=openlane -- emitted best-effort
set ::env(RSZ_DONT_TOUCH_RX) "$^"
# WARN: 'RSZ_MULTICORNER_LIB' not in schema for tool=openlane -- emitted best-effort
set ::env(RSZ_MULTICORNER_LIB) "1"
# WARN: 'RUN_CTS' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_CTS) "1"
# WARN: 'RUN_DRT' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_DRT) "1"
# WARN: 'RUN_HEURISTIC_DIODE_INSERTION' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_HEURISTIC_DIODE_INSERTION) "0"
# WARN: 'RUN_IRDROP_REPORT' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_IRDROP_REPORT) "1"
# WARN: 'RUN_KLAYOUT_DRC' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_KLAYOUT_DRC) "0"
# WARN: 'RUN_KLAYOUT_XOR' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_KLAYOUT_XOR) "False"
# WARN: 'RUN_MAGIC' not in schema for tool=openlane -- emitted best-effort
set ::env(RUN_MAGIC) "1"
# WARN: 'STA_MULTICORNER_READ_LIBS' not in schema for tool=openlane -- emitted best-effort
set ::env(STA_MULTICORNER_READ_LIBS) "0"
# WARN: 'SYNTH_ADDER_TYPE' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_ADDER_TYPE) "YOSYS"
# WARN: 'SYNTH_BUFFER_DIRECT_WIRES' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_BUFFER_DIRECT_WIRES) "1"
# WARN: 'SYNTH_CHECKS_ALLOW_TRISTATE' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_CHECKS_ALLOW_TRISTATE) "1"
# WARN: 'SYNTH_EXTRA_MAPPING_FILE' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_EXTRA_MAPPING_FILE) ""
# WARN: 'SYNTH_SHARE_RESOURCES' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_SHARE_RESOURCES) "1"
# WARN: 'SYNTH_SIZING' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_SIZING) "0"
# WARN: 'SYNTH_SPLITNETS' not in schema for tool=openlane -- emitted best-effort
set ::env(SYNTH_SPLITNETS) "1"
# WARN: 'TAKE_LAYOUT_SCROT' not in schema for tool=openlane -- emitted best-effort
set ::env(TAKE_LAYOUT_SCROT) "0"
# WARN: 'TOP_MARGIN_MULT' not in schema for tool=openlane -- emitted best-effort
set ::env(TOP_MARGIN_MULT) "4"
# WARN: 'USE_GPIO_PADS' not in schema for tool=openlane -- emitted best-effort
set ::env(USE_GPIO_PADS) "0"
# WARN: 'WRITE_VIEWS_NO_GLOBAL_CONNECT' not in schema for tool=openlane -- emitted best-effort
set ::env(WRITE_VIEWS_NO_GLOBAL_CONNECT) "0"
# WARN: 'YOSYS_REWRITE_VERILOG' not in schema for tool=openlane -- emitted best-effort
set ::env(YOSYS_REWRITE_VERILOG) "0"
set ::env(DESIGN_NAME) "wakeel_alu"
set ::env(VERILOG_FILES) [glob -nocomplain $::env(DESIGN_DIR)/src/*.v $::env(DESIGN_DIR)/src/*.sv]
