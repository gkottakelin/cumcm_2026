include mk/vars.mk

DATA_DIR := data
FIGURE_DIR := figure
OUT_DIR := out
PYTHON_CODE_DIR := python-code
TEX_DIR := tex

LATEXINDENT := latexindent --logfile=/dev/null --modifylinebreaks --silent --yaml="modifyLineBreaks:{oneSentencePerLine:{manipulateSentences:1}}"
PRETTIER := bunx prettier
PYRIGHT := bunx pyright
RUFF := uvx ruff
TAPLO := bunx @taplo/cli

export BUN_CONFIG_REGISTRY := https://registry.npmmirror.com

BIB := reference.bib
FINAL = $(OUT_DIR)/$(FINAL_NAME).pdf

.PHONY: all artifacts clean
all: $(FINAL)
artifacts: $(ARTIFACTS)
$(OUT_DIR):
	mkdir -p $@
clean:
	rm -rf $(OUT_DIR)
clean-all:
	$(MAKE) clean
	rm -rf .venv

IN_PY := $(PYTHON_CODE_DIR)/main.py
IN_DEPS := $(wildcard $(DATA_DIR)/*) $(wildcard $(PYTHON_CODE_DIR)/*) matplotlibrc
OUT_ARTIFACTS := $(ARTIFACTS)
include mk/uv-run.mk

IN_TEX := $(TEX_DIR)/main.tex
IN_DEPS := $(ARTIFACTS) $(BIB) $(wildcard $(FIGURE_DIR)/*)
OUT_PDF := $(FINAL)
include mk/tex-to-pdf.mk

IN_BIB := $(BIB)
IN_TEX := $(wildcard $(TEX_DIR)/*.tex)
include mk/tex-test.mk
include mk/tex-fix.mk

include mk/general-test.mk
include mk/general-fix.mk
include mk/uv-test.mk
include mk/uv-fix.mk
