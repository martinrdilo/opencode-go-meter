REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UUID := opencode-go-meter@martin.local
BIN_LINK := $(HOME)/.local/bin/ocgo
EXT_LINK := $(HOME)/.local/share/gnome-shell/extensions/$(UUID)
APPLET_LINK := $(HOME)/.local/share/cinnamon/applets/$(UUID)

.PHONY: test check-gnome check-cinnamon install uninstall install-cinnamon uninstall-cinnamon

test:
	cd core && python3 -m unittest discover -s tests -v

check-gnome:
	python3 gnome/scripts/check_collisions.py

check-cinnamon:
	python3 cinnamon/scripts/check_applet.py

install:
	mkdir -p $(dir $(BIN_LINK)) $(dir $(EXT_LINK))
	ln -sfn $(REPO)/core/bin/ocgo $(BIN_LINK)
	ln -sfn $(REPO)/gnome $(EXT_LINK)
	glib-compile-schemas $(REPO)/gnome/schemas
	@echo "installed: $(BIN_LINK) -> $(REPO)/core/bin/ocgo"
	@echo "installed: $(EXT_LINK) -> $(REPO)/gnome"
	@echo "enable with: gnome-extensions enable $(UUID)"

uninstall:
	@target="$$(readlink -f $(BIN_LINK) 2>/dev/null || true)"; \
	if [ "$$target" = "$(REPO)/core/bin/ocgo" ]; then \
		rm -f $(BIN_LINK); echo "removed $(BIN_LINK)"; \
	fi
	@target="$$(readlink -f $(EXT_LINK) 2>/dev/null || true)"; \
	case "$$target" in \
		$(REPO)/*) rm -f $(EXT_LINK); echo "removed $(EXT_LINK)" ;; \
		*) [ -z "$$target" ] || echo "kept $(EXT_LINK) (not from this repo)" ;; \
	esac

install-cinnamon:
	mkdir -p $(dir $(BIN_LINK)) $(dir $(APPLET_LINK))
	ln -sfn $(REPO)/core/bin/ocgo $(BIN_LINK)
	ln -sfn $(REPO)/cinnamon $(APPLET_LINK)
	@echo "installed: $(BIN_LINK) -> $(REPO)/core/bin/ocgo"
	@echo "installed: $(APPLET_LINK) -> $(REPO)/cinnamon"
	@echo "add it with: right-click the panel -> Add applets to the panel"
	@echo "   (or Cinnamon Settings -> Applets), then pick \"OpenCode Go Meter\""

uninstall-cinnamon:
	@target="$$(readlink -f $(BIN_LINK) 2>/dev/null || true)"; \
	if [ "$$target" = "$(REPO)/core/bin/ocgo" ]; then \
		rm -f $(BIN_LINK); echo "removed $(BIN_LINK)"; \
	fi
	@target="$$(readlink -f $(APPLET_LINK) 2>/dev/null || true)"; \
	case "$$target" in \
		$(REPO)/*) rm -f $(APPLET_LINK); echo "removed $(APPLET_LINK)" ;; \
		*) [ -z "$$target" ] || echo "kept $(APPLET_LINK) (not from this repo)" ;; \
	esac
