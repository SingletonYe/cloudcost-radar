PY ?= python3

.PHONY: help collect build qa test daily publish serve clean

help:
	@echo "make collect   - fetch today's AWS prices into data/ and api/"
	@echo "make build     - rebuild the static site into site/"
	@echo "make qa        - quality gate; non-zero exit blocks a publish"
	@echo "make test      - regression tests"
	@echo "make daily     - collect + build + qa (what CI runs)"
	@echo "make publish   - capture a cover and redeploy the hosted site"
	@echo "make serve     - local preview on http://localhost:8000"

collect:
	$(PY) src/fetch_data.py --if-missing

build:
	$(PY) src/build_site.py --out site

qa:
	$(PY) src/qa_check.py --out site

test:
	$(PY) -m unittest discover tests

daily: collect
	$(PY) src/check_providers.py || true
	$(PY) src/build_site.py --out site
	$(PY) src/qa_check.py --out site

publish: build qa
	mkdir -p generated/previews
	okou host screenshot site --out ./generated/previews/cover.png
	okou host site --site cloudcost-radar --preview ./generated/previews/cover.png --json

serve:
	$(PY) -m http.server 8000 --directory site

clean:
	rm -rf site .cache generated
