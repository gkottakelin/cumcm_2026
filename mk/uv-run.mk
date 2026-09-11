$(OUT_ARTIFACTS) &: $(IN_PY) $(IN_DEPS) | $(OUT_DIR)
	uv run $<
