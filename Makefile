REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UUID := opencode-go-meter@martin.local
BIN_LINK := $(HOME)/.local/bin/ocgo
EXT_LINK := $(HOME)/.local/share/gnome-shell/extensions/$(UUID)

.PHONY: test install uninstall

test:
	cd core && python3 -m unittest discover -s tests -v

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
