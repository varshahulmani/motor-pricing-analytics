PY ?= python

.PHONY: all demo load prep tariff eda frequency severity pricing tableau validate clean

all: load prep tariff eda frequency severity pricing tableau validate

load:      ; $(PY) src/load.py
prep:      ; $(PY) src/prep.py
tariff:    ; $(PY) src/tariff.py
eda:       ; $(PY) src/eda.py
frequency: ; $(PY) src/frequency.py
severity:  ; $(PY) src/severity.py
pricing:   ; $(PY) src/pricing.py
tableau:   ; $(PY) src/export_tableau.py
validate:  ; $(PY) src/validate.py

# end-to-end test on synthetic data with the same columns (no download)
demo:
	$(PY) scripts/make_synthetic.py --rows 120000 --out data/demo_raw
	MTPL_RAW=data/demo_raw MTPL_DB=data/demo.duckdb $(MAKE) all

clean:
	rm -rf outputs reports/*.md reports/*.png tableau/data data/*.duckdb data/demo_raw
