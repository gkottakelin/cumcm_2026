FIXES ?=
FIXES += fix-ruff
fix-ruff:
	$(RUFF) check --fix
FIXES += fix-ruff-format
fix-ruff-format:
	$(RUFF) format
.PHONY: fix $(FIXES)
fix: $(FIXES)
