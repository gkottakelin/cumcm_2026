$(OUT_PDF): $(IN_TEX) $(IN_DEPS) | $(OUT_DIR)
	latexmk -auxdir=$(OUT_DIR) -jobname=$(basename $(notdir $@)) -outdir=$(OUT_DIR) -quiet -xelatex $<
