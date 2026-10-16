#!/usr/bin/env bash
#
# install-deps.sh — check the meter's dependencies and offer to resolve the
# ones that can be resolved.
#
#   ./scripts/install-deps.sh              check, then offer to fix what it can
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

# --- 2. secret-tool (libsecret-tools) — recommended, never fatal ------------
secret_tool_bin="$(command -v secret-tool 2>/dev/null || true)"
if [ -z "$secret_tool_bin" ]; then
    say ""
    say "secret-tool: not found — optional (libsecret-tools)"
    detail "without it the app offers to keep API keys in a private local file instead of the OS keyring"
    if [ "$CHECK_ONLY" = 0 ] && [ -t 0 ] && command -v apt-get >/dev/null 2>&1; then
        printf '  Install libsecret-tools now? [y/N] '
        reply=""
        read -r reply || true
        case "$reply" in
            y|Y|yes|YES)
                sudo apt-get install -y libsecret-tools \
                    || detail "install did not complete; the app will keep using the local file"
                secret_tool_bin="$(command -v secret-tool 2>/dev/null || true)"
                ;;
            *)
                detail "skipped; install it later with: sudo apt-get install -y libsecret-tools"
                ;;
        esac
    else
        detail "install it: sudo apt-get install -y libsecret-tools"
    fi
fi

# --- 3. opencode CLI — optional (the applet's login button) -----------------
opencode_bin="$(command -v opencode 2>/dev/null || true)"
if [ -z "$opencode_bin" ]; then
    home_dir="${HOME:-}"
    for candidate in \
        "$home_dir/.opencode/bin/opencode" \
        "$home_dir/.local/bin/opencode" \
        "$home_dir/bin/opencode" \
        "$home_dir/.bun/bin/opencode" \
        "$home_dir/.npm-global/bin/opencode" \
        /usr/local/bin/opencode \
        /usr/bin/opencode \
        /snap/bin/opencode; do
        if [ -x "$candidate" ]; then
            opencode_bin="$candidate"
            break
        fi
    done
fi
if [ -z "$opencode_bin" ]; then
    say ""
    say "opencode CLI: not found — optional"
    detail "needed only by the applet's \"Log in with OpenCode…\" button; never installed automatically"
    detail "install it from https://opencode.ai"
fi

# --- 4. glib-compile-schemas — needed by 'make install' (GNOME) -------------
glib_bin="$(command -v glib-compile-schemas 2>/dev/null || true)"
if [ -z "$glib_bin" ]; then
    say ""
    say "glib-compile-schemas: not found — 'make install' needs it (GNOME)"
    detail "install it: sudo apt install libglib2.0-bin    (Linux Mint / Ubuntu)"
fi

# --- summary ----------------------------------------------------------------
present=0
[ -n "$python3_bin" ] && present=$((present + 1))
[ -n "$secret_tool_bin" ] && present=$((present + 1))
[ -n "$opencode_bin" ] && present=$((present + 1))
[ -n "$glib_bin" ] && present=$((present + 1))

say ""
say "dependency summary ($present of 4 present)"
summary_line() { printf '  %-8s %-21s %s\n' "$1" "$2" "$3"; }

if [ -n "$python3_bin" ]; then
    summary_line "ok" "python3 (required)" "${python3_version:-unknown version} at $python3_bin"
else
    summary_line "missing" "python3 (required)" "the helper cannot run; install with: sudo apt install python3"
fi
if [ -n "$secret_tool_bin" ]; then
    summary_line "ok" "secret-tool" "$secret_tool_bin"
else
    summary_line "missing" "secret-tool" "the app offers a private local file instead of the OS keyring (optional)"
fi
if [ -n "$opencode_bin" ]; then
    summary_line "ok" "opencode CLI" "$opencode_bin"
else
    summary_line "missing" "opencode CLI" "the \"Log in with OpenCode…\" button needs it — https://opencode.ai (optional)"
fi
if [ -n "$glib_bin" ]; then
    summary_line "ok" "glib-compile-schemas" "$glib_bin"
else
    summary_line "missing" "glib-compile-schemas" "'make install' cannot compile the GNOME schema — sudo apt install libglib2.0-bin"
fi

exit "$exit_fail"
