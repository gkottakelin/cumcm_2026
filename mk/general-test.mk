TESTS ?=
TESTS += test-checkmake
test-checkmake:
	checkmake makefile mk/*
TESTS += test-ls-lint
test-ls-lint:
	bunx @ls-lint/ls-lint
TESTS += test-prettier
test-prettier:
	$(PRETTIER) --check .
TESTS += test-taplo-format
test-taplo-format:
	$(TAPLO) format --check
TESTS += test-taplo-lint
test-taplo-lint:
	$(TAPLO) lint
.PHONY: test $(TESTS)
test: $(TESTS)
