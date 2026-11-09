PYTHON ?= python3

.PHONY: all deb test install uninstall clean

all: deb

deb:
	dpkg-buildpackage -us -uc -b

test:
	$(PYTHON) -m unittest discover -s tests -v

install: deb
	sudo dpkg -i ../pristar-p15-driver_*.deb

uninstall:
	sudo dpkg -r pristar-p15-driver

clean:
	rm -f p15-leconnect
	rm -rf debian/.debhelper debian/pristar-p15-driver debian/debhelper-build-stamp \
		debian/files debian/*.substvars
	find . -name __pycache__ -type d -exec rm -rf {} +
