FIXES ?=
FIXES += fix-prettier
fix-prettier:
	$(PRETTIER) --write .
FIXES += fix-taplo-format
fix-taplo-format:
	$(TAPLO) format
.PHONY: fix $(FIXES)
fix: $(FIXES)
