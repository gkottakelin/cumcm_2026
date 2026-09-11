FIXES ?=
FIXES += fix-bibtex-tidy
fix-bibtex-tidy:
	bunx bibtex-tidy $(IN_BIB) --modify --v2
FIXES += fix-latexindent
fix-latexindent:
	$(LATEXINDENT) --overwriteIfDifferent $(IN_TEX)
.PHONY: fix $(FIXES)
fix: $(FIXES)
