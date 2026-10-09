// OpenCode Go Meter — Cinnamon panel applet (Cinnamon 6.4, legacy imports).
// Reads the ocgo cache written by the core CLI; it never touches credentials.

const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const Util = imports.misc.util;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const St = imports.gi.St;

const CACHE_DIR = 'ocgo';
const CACHE_FILE = 'status.json';
const ACCOUNTS_DIR = 'accounts';
const CONFIG_DIR = 'ocgo';
const REGISTRY_FILE = 'accounts.json';
const DEFAULT_REFRESH_SECONDS = 300;
const MIN_REFRESH_SECONDS = 30;
const TICK_SECONDS = 30;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;

const ACCOUNTS_SCHEMA = 2;
const DEFAULT_ACCOUNT_ID = 'default';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

const WINDOWS = [
    {key: 'rolling', label: 'Rolling usage', short: '5h'},
    {key: 'weekly', label: 'Weekly usage', short: '7d'},
    {key: 'monthly', label: 'Monthly usage', short: '30d'},
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

function formatCountdown(target, now) {
    const date = parseDate(target);
    if (!date)
        return '—';
    const seconds = Math.max(0, Math.floor((date.getTime() - now.getTime()) / 1000));
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0)
        return `${days}d ${hours}h`;
    if (hours > 0)
        return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function formatRenewal(value) {
    const date = parseDate(value);
    if (!date)
        return null;
    try {
        return date.toLocaleDateString('en-US', {month: 'short', day: 'numeric'});
    } catch (error) {
        logError('could not format the renewal date', error);
        return null;
    }
}

function truncate(text, max) {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function escapeMarkup(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function expandHome(path) {
    if (path === '~')
        return GLib.get_home_dir();
    if (path.startsWith('~/'))
        return GLib.build_filenamev([GLib.get_home_dir(), path.slice(2)]);
    return path;
}

function resolveExecutable(path) {
    if (!path)
        return null;
    if (!path.includes('/'))
        return GLib.find_program_in_path(path);
    return GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE) ? path : null;
}

function percentText(percent) {
    return Number.isFinite(percent) ? `${Math.round(percent)}%` : '—';
}

function percentMarkup(percent) {
    if (!Number.isFinite(percent))
        return percentText(percent);
    return `<span foreground="${colorFor(percent)}">${percentText(percent)}</span>`;
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

function parseAccountList(text) {
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
    if (payload.schema !== ACCOUNTS_SCHEMA || !Array.isArray(payload.accounts))
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
            active: false,
        });
    }
    const requested = typeof payload.active === 'string' ? payload.active : null;
    const active = requested !== null && seen.has(requested) ? requested : null;
    for (const account of accounts)
        account.active = account.id === active;
    return {accounts, active};
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
        this._accounts = [];
        this._accountsLoaded = false;
        this._accountsLoading = false;
        this._accountsErrorLogged = false;
        this._accountsGeneration = 0;
        this._accountsPending = null;
        this._accountMenuSignature = null;

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);
        this.settings.bind('refresh-interval', 'refresh_interval', () => this._onRefreshIntervalChanged());
        this.settings.bind('ocgo-path', 'ocgo_path', null);

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menuManager.addMenu(this.menu);
        this._buildMenu();

        this._updateDisplay();
        this._startTimers();
        this._loadAccounts();
        this._triggerRefresh();
    }

    on_applet_clicked(event) {
        this.menu.toggle();
    }

    on_applet_removed_from_panel(deleteConfig) {
        this._removed = true;
        if (this.settings) {
            this.settings.finalize();
            this.settings = null;
        }
        if (this._refreshTimerId) {
            Mainloop.source_remove(this._refreshTimerId);
            this._refreshTimerId = 0;
        }
        if (this._tickTimerId) {
            Mainloop.source_remove(this._tickTimerId);
            this._tickTimerId = 0;
        }
        if (this.menu) {
            this.menu.destroy();
            this.menu = null;
        }
        this.menuManager = null;
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
            const windows = windowsOf(cache);
            this._renderLabel(this._activeAccountId !== null, windows);
            this._renderMenu(cache, windows);
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
            return `${window.short} ${percentMarkup(percent)}`;
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

    // -- popup menu ----------------------------------------------------------

    _buildMenu() {
        this._headerItem = new PopupMenu.PopupMenuItem('OpenCode Go', {reactive: false});
        this.menu.addMenuItem(this._headerItem);

        this._warningItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._warningItem.actor.visible = false;
        this.menu.addMenuItem(this._warningItem);

        this._menuRows = new Map();
        for (const window of WINDOWS) {
            const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
            const name = new St.Label({
                text: window.label,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const percent = new St.Label({
                text: '—',
                y_align: Clutter.ActorAlign.CENTER,
            });
            const countdown = new St.Label({
                text: 'Resets in —',
                y_align: Clutter.ActorAlign.CENTER,
            });
            item.addActor(name, {expand: true});
            item.addActor(percent);
            item.addActor(countdown);
            this.menu.addMenuItem(item);
            this._menuRows.set(window.key, {percent, countdown});
        }

        this._accountSubMenuItem = new PopupMenu.PopupSubMenuMenuItem('Account');
        this.menu.addMenuItem(this._accountSubMenuItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._refreshItem = new PopupMenu.PopupMenuItem('Updated — · Refresh');
        this._refreshItem.connect('activate', () => this._triggerRefresh());
        this.menu.addMenuItem(this._refreshItem);

        this.menu.connect('open-state-changed', (menu, isOpen) => {
            if (isOpen)
                this._loadAccounts();
        });
    }

    _renderMenu(cache, windows) {
        const now = new Date();
        const renewal = cache ? formatRenewal(cache.renewal_ends_at) : null;

        let header;
        if (!this._activeAccountId) {
            header = 'OpenCode Go';
        } else if (this._activeAccountId === DEFAULT_ACCOUNT_ID) {
            header = renewal ? `OpenCode Go — Renews ${renewal}` : 'OpenCode Go';
        } else {
            const label = this._activeAccountLabel || this._activeAccountId;
            header = renewal
                ? `OpenCode Go · ${label} — Renews ${renewal}`
                : `OpenCode Go · ${label}`;
        }
        this._headerItem.label.clutter_text.set_markup(`<b>${escapeMarkup(header)}</b>`);

        const lastError = cache && typeof cache.last_error === 'string'
            ? cache.last_error.trim()
            : '';
        if (lastError) {
            const ago = formatAgo(cache.fetched_at, now);
            const suffix = ago ? ` · data from ${ago}` : '';
            const warning = `Last refresh failed: ${truncate(lastError, MAX_WARNING_CHARS)}${suffix}`;
            this._warningItem.label.clutter_text.set_markup(
                `<span foreground="${COLORS.amber}">${escapeMarkup(warning)}</span>`);
            this._warningItem.actor.visible = true;
        } else {
            this._warningItem.actor.visible = false;
        }

        for (const window of WINDOWS) {
            const row = this._menuRows.get(window.key);
            const data = windowOf(windows, window.key);
            row.percent.clutter_text.set_markup(percentMarkup(data.percent));
            // The month meter has no resetsAt; the console counts down to renewal.
            const target = window.key === 'monthly'
                ? (cache ? cache.renewal_ends_at : null)
                : data.resets_at;
            row.countdown.set_text(`Resets in ${formatCountdown(target, now)}`);
        }

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._refreshItem.label.set_text(`Updated ${updated || '—'} · Refresh`);
    }

    _renderAccountMenu() {
        if (!this._accountSubMenuItem)
            return;
        const accounts = this._accounts || [];
        const signature = accounts.map(account =>
            `${account.id}\u0000${account.label}\u0000${account.active ? 1 : 0}`).join('\u0001');
        if (signature === this._accountMenuSignature)
            return;
        if (this._accountSubMenuItem.menu.isOpen)
            return; // never destroy items while the submenu is open
        this._accountMenuSignature = signature;

        const submenu = this._accountSubMenuItem.menu;
        submenu.removeAll();
        if (accounts.length === 0) {
            submenu.addMenuItem(new PopupMenu.PopupMenuItem('No accounts configured', {
                reactive: false,
            }));
        } else {
            for (const account of accounts) {
                const item = new PopupMenu.PopupMenuItem(account.label);
                item.setOrnament(PopupMenu.OrnamentType.DOT, account.active);
                item.connect('activate', () => this._switchAccount(account.id));
                submenu.addMenuItem(item);
            }
        }
    }

    // -- accounts ------------------------------------------------------------

    _loadAccounts(onComplete = null) {
        const generation = ++this._accountsGeneration;
        if (this._accountsLoading) {
            this._accountsPending = {generation, onComplete};
            return;
        }
        this._startAccountLoad(generation, onComplete);
    }

    _startAccountLoad(generation, onComplete) {
        const binary = this._ocgoPath();
        if (!binary) {
            this._finishAccountLoad(
                generation, onComplete, null,
                'ocgo not found; keeping the current account list');
            return;
        }
        this._accountsLoading = true;
        try {
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                this._accountsLoading = false;
                if (this._removed) {
                    this._accountsPending = null;
                    return;
                }
                let errorMessage = null;
                let error = null;
                if (exitCode !== 0) {
                    errorMessage = 'ocgo account list failed; keeping the current account list';
                    error = typeof stderr === 'string' ? stderr.trim() : null;
                }
                const parsed = errorMessage ? null : parseAccountList(stdout);
                if (!errorMessage && !parsed)
                    errorMessage = 'unexpected account list output; keeping the current account list';
                this._finishAccountLoad(generation, onComplete, parsed, errorMessage, error);
            }, {argv: [binary, 'account', 'list', '--json']});
        } catch (error) {
            this._accountsLoading = false;
            this._finishAccountLoad(
                generation, onComplete, null,
                'could not start the account list; keeping the current account list', error);
        }
    }

    _finishAccountLoad(generation, onComplete, parsed, errorMessage, error = null) {
        if (this._removed) {
            this._accountsPending = null;
            return;
        }
        if (generation === this._accountsGeneration) {
            // Newest request: apply the result (or the fallback) and run its
            // callback on both paths, so a queued action is never dropped.
            if (parsed) {
                this._accounts = parsed.accounts;
                this._accountsLoaded = true;
                this._accountsErrorLogged = false;
            } else {
                if (!this._accountsLoaded)
                    this._accounts = [];
                this._accountsLoaded = true;
                if (!this._accountsErrorLogged) {
                    this._accountsErrorLogged = true;
                    logError(errorMessage, error);
                }
            }
            this._renderAccountMenu();
            if (onComplete)
                onComplete();
        }
        // A stale result is discarded, never applied; if a newer request was
        // coalesced while this one was in flight, start it now.
        const pending = this._accountsPending;
        this._accountsPending = null;
        if (pending)
            this._startAccountLoad(pending.generation, pending.onComplete);
    }

    _switchAccount(accountId) {
        if (!accountId || accountId === this._activeAccountId)
            return;
        const binary = this._ocgoPath();
        if (!binary) {
            logError('ocgo not found; cannot switch accounts');
            return;
        }
        try {
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                if (this._removed)
                    return;
                if (exitCode !== 0) {
                    const detail = typeof stderr === 'string' ? stderr.trim() : '';
                    logError(`could not switch to account '${accountId}'`, detail || null);
                    return;
                }
                // The CLI already switched the registry: reflect it now,
                // refresh, then reconcile the submenu from the CLI.
                this._updateDisplay();
                this._triggerRefresh();
                this._loadAccounts();
            }, {argv: [binary, 'account', 'use', accountId]});
        } catch (error) {
            logError(`could not start the account switch to '${accountId}'`, error);
        }
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

    // The configured path is authoritative: an unresolvable explicit path is an
    // error, never a silent fallback. An empty setting falls back to
    // ~/.local/bin/ocgo and then PATH, mirroring the GNOME extension.
    _ocgoPath() {
        const configured = typeof this.ocgo_path === 'string' ? this.ocgo_path.trim() : '';
        if (configured)
            return resolveExecutable(expandHome(configured));
        const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
        if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
            return local;
        return GLib.find_program_in_path('ocgo');
    }

    _refreshSeconds() {
        try {
            const value = this.refresh_interval;
            if (Number.isInteger(value) && value >= MIN_REFRESH_SECONDS)
                return value;
        } catch (error) {
            logError('could not read refresh-interval; using the default', error);
        }
        return DEFAULT_REFRESH_SECONDS;
    }

    _onRefreshIntervalChanged() {
        if (this._removed)
            return;
        this._restartRefreshTimer();
    }

    _startTimers() {
        this._startRefreshTimer();
        this._tickTimerId = Mainloop.timeout_add_seconds(TICK_SECONDS, () => {
            try {
                this._updateDisplay();
            } catch (error) {
                logError('display tick failed', error);
            }
            return true;
        });
    }

    _startRefreshTimer() {
        this._refreshTimerId = Mainloop.timeout_add_seconds(this._refreshSeconds(), () => {
            try {
                this._triggerRefresh();
            } catch (error) {
                logError('scheduled refresh failed', error);
            }
            return true;
        });
    }

    _restartRefreshTimer() {
        if (this._refreshTimerId) {
            Mainloop.source_remove(this._refreshTimerId);
            this._refreshTimerId = 0;
        }
        this._startRefreshTimer();
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
