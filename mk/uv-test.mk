TESTS ?=
TESTS += test-deptry
test-deptry:
	uvx deptry .
TESTS += test-pyright
test-pyright:
	$(PYRIGHT)
TESTS += test-ruff-check
test-ruff-check:
	$(RUFF) check --ignore-noqa
TESTS += test-ruff-format
test-ruff-format:
	$(RUFF) format --check
TESTS += test-uv
test-uv:
	uv lock --check
.PHONY: test $(TESTS)
test: $(TESTS)
