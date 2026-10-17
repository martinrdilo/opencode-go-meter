#!/usr/bin/env bash
#
# install-deps.sh — check the meter's dependencies and report what is missing.
#
#   ./scripts/install-deps.sh              check and report the dependency status
#   ./scripts/install-deps.sh --check      read-only report (never installs, never prompts)
#   SKIP_DEPS=1 ./scripts/install-deps.sh  skip the check (exit 0)
#
# Exit status is 1 only when python3 is missing or older than 3.10 — the one
# hard requirement. Everything else is reported and advised, never fatal.

set -u

PYTHON_MIN="3.10"

CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=1 ;;
        *) printf 'usage: %s [--check]\n' "$0" >&2; exit 2 ;;
    esac
done

if [ "${SKIP_DEPS:-0}" = "1" ]; then
    echo "dependency check skipped (SKIP_DEPS=1)"
    exit 0
fi

say()    { printf '%s\n' "$*"; }
detail() { printf '  %s\n' "$*"; }

if [ "$CHECK_ONLY" = 1 ]; then
    say "dependency check (read-only)"
else
    say "dependency check"
fi

exit_fail=0

# --- 1. python3 >= 3.10 — required ------------------------------------------
python3_bin=""
python3_version=""
resolved="$(command -v python3 2>/dev/null || true)"
if [ -n "$resolved" ] \
    && "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
    python3_bin="$resolved"
    python3_version="$("$resolved" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
else
    say ""
    if [ -z "$resolved" ]; then
        say "python3: not found — required"
    else
        say "python3: found at $resolved, but $PYTHON_MIN or newer is required"
    fi
    detail "install or upgrade it: sudo apt install python3    (Linux Mint / Ubuntu)"
    exit_fail=1
fi

# --- 2. glib-compile-schemas — needed by 'make install' (GNOME) -------------
glib_bin="$(command -v glib-compile-schemas 2>/dev/null || true)"
if [ -z "$glib_bin" ]; then
    say ""
    say "glib-compile-schemas: not found — 'make install' needs it (GNOME)"
    detail "install it: sudo apt install libglib2.0-bin    (Linux Mint / Ubuntu)"
fi

# --- summary ----------------------------------------------------------------
present=0
[ -n "$python3_bin" ] && present=$((present + 1))
[ -n "$glib_bin" ] && present=$((present + 1))

say ""
say "dependency summary ($present of 2 present)"
summary_line() { printf '  %-8s %-21s %s\n' "$1" "$2" "$3"; }

if [ -n "$python3_bin" ]; then
    summary_line "ok" "python3 (required)" "${python3_version:-unknown version} at $python3_bin"
else
    summary_line "missing" "python3 (required)" "the helper cannot run; install with: sudo apt install python3"
fi
if [ -n "$glib_bin" ]; then
    summary_line "ok" "glib-compile-schemas" "$glib_bin"
else
    summary_line "missing" "glib-compile-schemas" "'make install' cannot compile the GNOME schema — sudo apt install libglib2.0-bin"
fi

exit "$exit_fail"
