TESTS ?=
TESTS += test-chktex
test-chktex:
	chktex -q $(IN_TEX)
TESTS += test-latexindent
test-latexindent:
	$(LATEXINDENT) -kv $(IN_TEX)
TESTS += test-texlog
test-texlog: $(OUT_PDF)
	texloganalyser $(OUT_DIR)/$(basename $(notdir $(IN_TEX))).log | grep -q 'The log contained 0 warnings.'
.PHONY: test $(TESTS)
test: $(TESTS)
