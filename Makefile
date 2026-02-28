.PHONY: check fix test lint install install-mcp install-swiftbar help

help:
	@echo "proxy-doctor — AI editor proxy diagnostic tool"
	@echo ""
	@echo "Usage:"
	@echo "  make check          Run proxy diagnosis (JSON output)"
	@echo "  make check-human    Run proxy diagnosis (human-readable)"
	@echo "  make fix             Show recommended fixes"
	@echo "  make test            Run tests"
	@echo "  make lint            Run linter"
	@echo "  make install         Install CLI (pip install -e .)"
	@echo "  make install-mcp     Install with MCP support"
	@echo "  make install-swiftbar  Install SwiftBar plugin"

check:
	python3 -m proxy_doctor.cli check

check-human:
	python3 -m proxy_doctor.cli check --human

fix:
	python3 -m proxy_doctor.cli fix

test:
	python3 -m pytest tests/ -v

lint:
	python3 -m ruff check src/ tests/

install:
	pip install -e .

install-mcp:
	pip install -e ".[mcp]"

install-swiftbar:
	@if [ -z "$$SWIFTBAR_PLUGINS_PATH" ]; then \
		echo "Set SWIFTBAR_PLUGINS_PATH or copy manually:"; \
		echo "  cp plugins/swiftbar/proxy-doctor.5m.sh ~/Library/Application\\ Support/SwiftBar/Plugins/"; \
	else \
		cp plugins/swiftbar/proxy-doctor.5m.sh "$$SWIFTBAR_PLUGINS_PATH/"; \
		chmod +x "$$SWIFTBAR_PLUGINS_PATH/proxy-doctor.5m.sh"; \
		echo "Installed to $$SWIFTBAR_PLUGINS_PATH"; \
	fi
