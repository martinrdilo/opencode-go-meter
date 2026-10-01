.PHONY: test

test:
	cd core && python3 -m unittest discover -s tests -v
