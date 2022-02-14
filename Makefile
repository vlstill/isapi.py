PY = $(wildcard *.py) upload-zip

-include local.make

MYPY ?= mypy
FLAKE8 ?= flake8

check : $(PY:%=%.mypy)
	$(FLAKE8)
	
%.mypy : %
	$(MYPY) --check-untyped-defs --warn-redundant-casts --warn-return-any $<

.PHONY: %.mypy
