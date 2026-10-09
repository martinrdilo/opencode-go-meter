// OpenCode Go Meter — Cinnamon panel applet (Cinnamon 6.4, legacy imports).
// Reads the ocgo cache written by the core CLI; it never touches credentials.

const Applet = imports.ui.applet;
const Mainloop = imports.mainloop;
const Util = imports.misc.util;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;

const CACHE_DIR = 'ocgo';
const CACHE_FILE = 'status.json';
const ACCOUNTS_DIR = 'accounts';
const CONFIG_DIR = 'ocgo';
const REGISTRY_FILE = 'accounts.json';
const REFRESH_SECONDS = 300;
const TICK_SECONDS = 30;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;

const ACCOUNTS_SCHEMA = 2;
const DEFAULT_ACCOUNT_ID = 'default';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

const WINDOWS = [
    {key: 'rolling', short: '5h'},
    {key: 'weekly', short: '7d'},
    {key: 'monthly', short: '30d'},
];

// Adwaita palette variants chosen for the dark Cinnamon panel.
const COLORS = {
    green: '#8ff0a4',
    amber: '#f9c440',
    red: '#ff7b63',
};

function logError(message, error) {
    console.error(`[opencode-go-meter] ${message}${error ? `: ${error}` : ''}`);
}

function parseDate(value) {
    if (typeof value !== 'string' || value.trim() === '')
        return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatAgo(value, now) {
    const date = parseDate(value);
    if (!date)
        return null;
    const minutes = Math.max(0, Math.floor((now.getTime() - date.getTime()) / 60000));
    if (minutes < 1)
        return 'just now';
    if (minutes < 60)
        return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24)
        return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

function truncate(text, max) {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function percentText(percent) {
    return Number.isFinite(percent) ? `${Math.round(percent)}%` : '—';
}

function colorFor(percent) {
    if (percent >= RED_AT)
        return COLORS.red;
    if (percent >= AMBER_AT)
        return COLORS.amber;
    return COLORS.green;
}

function windowsOf(cache) {
    const windows = cache && typeof cache === 'object' ? cache.windows : null;
    if (!windows || typeof windows !== 'object' || Array.isArray(windows))
        return {};
    return windows;
}

function windowOf(windows, key) {
    const window = windows[key];
    return window && typeof window === 'object' && !Array.isArray(window) ? window : {};
}

function parseRegistry(text) {
    if (typeof text !== 'string' || text.trim() === '')
        return null;
    let payload = null;
    try {
        payload = JSON.parse(text);
    } catch (error) {
        return null;
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload))
        return null;
    if (payload.version !== ACCOUNTS_SCHEMA || !Array.isArray(payload.accounts))
        return null;

    const accounts = [];
    const seen = new Set();
    for (const entry of payload.accounts) {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry))
            return null;
        const id = entry.id;
        if (typeof id !== 'string' || !ACCOUNT_ID_RE.test(id) || seen.has(id))
            return null;
        seen.add(id);
        accounts.push({
            id,
            label: typeof entry.label === 'string' && entry.label.trim() !== ''
                ? entry.label
                : id,
        });
    }

    // Same effective-active rule as the core: the stored id when listed,
    // otherwise the first account; no accounts means no active account.
    const requested = typeof payload.active === 'string' ? payload.active : null;
    let active = requested !== null && seen.has(requested) ? requested : null;
    if (active === null && accounts.length > 0)
        active = accounts[0].id;
    const activeAccount = accounts.find(account => account.id === active) || null;
    return {
        active,
        activeLabel: activeAccount ? activeAccount.label : null,
    };
}

class OpenCodeGoMeterApplet extends Applet.TextApplet {
    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);
        this._removed = false;
        this._refreshInProgress = false;
        this._refreshTimerId = 0;
        this._tickTimerId = 0;
        this._activeAccountId = null;
        this._activeAccountLabel = null;

        this._updateDisplay();
        this._startTimers();
        this._triggerRefresh();
    }

    on_applet_clicked(event) {
        this._triggerRefresh();
    }

    on_applet_removed_from_panel(deleteConfig) {
        this._removed = true;
        if (this._refreshTimerId) {
            Mainloop.source_remove(this._refreshTimerId);
            this._refreshTimerId = 0;
        }
        if (this._tickTimerId) {
            Mainloop.source_remove(this._tickTimerId);
            this._tickTimerId = 0;
        }
    }

    // -- rendering -----------------------------------------------------------

    _updateDisplay() {
        if (this._removed)
            return;
        try {
            const registry = this._readRegistry();
            this._activeAccountId = registry ? registry.active : null;
            this._activeAccountLabel = registry ? registry.activeLabel : null;
            const cache = this._readCache();
            this._renderLabel(this._activeAccountId !== null, windowsOf(cache));
            this._renderTooltip(cache);
        } catch (error) {
            logError('could not render the usage cache', error);
        }
    }

    _renderLabel(hasAccount, windows) {
        if (!hasAccount) {
            this._applet_label.clutter_text.set_markup('—');
            return;
        }
        const parts = WINDOWS.map(window => {
            const percent = windowOf(windows, window.key).percent;
            if (!Number.isFinite(percent))
                return `${window.short} ${percentText(percent)}`;
            return `${window.short} <span foreground="${colorFor(percent)}">${percentText(percent)}</span>`;
        });
        this._applet_label.clutter_text.set_markup(parts.join(' · '));
    }

    _renderTooltip(cache) {
        const now = new Date();
        const lines = [];
        if (!this._activeAccountId) {
            lines.push('OpenCode Go');
            lines.push('No accounts configured');
        } else {
            lines.push(this._activeAccountId === DEFAULT_ACCOUNT_ID
                ? 'OpenCode Go'
                : `OpenCode Go · ${this._activeAccountLabel || this._activeAccountId}`);
            const updated = cache ? formatAgo(cache.fetched_at, now) : null;
            lines.push(updated ? `Updated ${updated}` : 'Updated —');
            const lastError = cache && typeof cache.last_error === 'string'
                ? cache.last_error.trim()
                : '';
            if (lastError) {
                const suffix = updated ? ` · data from ${updated}` : '';
                lines.push(`Last refresh failed: ${truncate(lastError, MAX_WARNING_CHARS)}${suffix}`);
            }
        }
        this.set_applet_tooltip(lines.join('\n'));
    }

    // -- cache ---------------------------------------------------------------

    _registryPath() {
        return GLib.build_filenamev([GLib.get_user_config_dir(), CONFIG_DIR, REGISTRY_FILE]);
    }

    _readRegistry() {
        try {
            const file = Gio.File.new_for_path(this._registryPath());
            const [ok, contents] = file.load_contents(null);
            if (!ok)
                return null;
            return parseRegistry(new TextDecoder().decode(contents));
        } catch (error) {
            return null; // missing or unreadable registry: show the empty state
        }
    }

    _cachePath() {
        if (!this._activeAccountId)
            return null;
        const parts = [GLib.get_user_cache_dir(), CACHE_DIR];
        if (this._activeAccountId !== DEFAULT_ACCOUNT_ID)
            parts.push(ACCOUNTS_DIR, this._activeAccountId, CACHE_FILE);
        else
            parts.push(CACHE_FILE);
        return GLib.build_filenamev(parts);
    }

    _readCache() {
        const path = this._cachePath();
        if (!path)
            return null;
        try {
            const file = Gio.File.new_for_path(path);
            const [ok, contents] = file.load_contents(null);
            if (!ok)
                return null;
            const cache = JSON.parse(new TextDecoder().decode(contents));
            if (!cache || typeof cache !== 'object' || Array.isArray(cache))
                return null;
            return cache;
        } catch (error) {
            return null; // no cache yet or unreadable JSON: show the empty values
        }
    }

    // -- refresh -------------------------------------------------------------

    // Default resolution mirrors the GNOME extension; T4 adds the settings
    // override (checked before this fallback there).
    _ocgoPath() {
        const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
        if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
            return local;
        return GLib.find_program_in_path('ocgo');
    }

    _startTimers() {
        this._refreshTimerId = Mainloop.timeout_add_seconds(REFRESH_SECONDS, () => {
            try {
                this._triggerRefresh();
            } catch (error) {
                logError('scheduled refresh failed', error);
            }
            return true;
        });
        this._tickTimerId = Mainloop.timeout_add_seconds(TICK_SECONDS, () => {
            try {
                this._updateDisplay();
            } catch (error) {
                logError('display tick failed', error);
            }
            return true;
        });
    }

    _triggerRefresh() {
        if (this._removed || this._refreshInProgress)
            return;
        if (!this._activeAccountId)
            return; // empty registry: there is no account to refresh
        const binary = this._ocgoPath();
        if (!binary) {
            logError('ocgo not found; keeping the current values');
            return;
        }
        this._refreshInProgress = true;
        try {
            // argv form (opts.argv) so a binary path with spaces needs no shell quoting.
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                this._refreshInProgress = false;
                if (this._removed)
                    return;
                if (exitCode !== 0) {
                    const detail = typeof stderr === 'string' ? stderr.trim() : '';
                    logError(`refresh exited with status ${exitCode}`, detail || null);
                }
                // Re-read the cache either way: on failure the CLI keeps the
                // last good values (plus last_error), so nothing is invented.
                this._updateDisplay();
            }, {argv: [binary, 'refresh']});
        } catch (error) {
            this._refreshInProgress = false;
            logError('could not start the refresh', error);
        }
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new OpenCodeGoMeterApplet(metadata, orientation, panel_height, instance_id);
}
