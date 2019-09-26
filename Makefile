PY = $(wildcard *.py)

-include local.make

MYPY ?= mypy

check : $(PY:%=%.mypy)
	
%.mypy : %
	$(MYPY) --check-untyped-defs --warn-redundant-casts --warn-unused-ignores --warn-return-any $<

.PHONY: %.mypy