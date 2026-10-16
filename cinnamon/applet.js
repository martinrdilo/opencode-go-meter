// OpenCode Go Meter — Cinnamon panel applet (Cinnamon 5.4+, legacy imports).
// Reads the ocgo cache written by the core CLI; it never touches credentials.

const Applet = imports.ui.applet;
const Main = imports.ui.main;
const ModalDialog = imports.ui.modalDialog;
const PopupMenu = imports.ui.popupMenu;
const RadioButton = imports.ui.radioButton;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const Util = imports.misc.util;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Pango = imports.gi.Pango;
const St = imports.gi.St;

const CACHE_DIR = 'ocgo';
const CACHE_FILE = 'status.json';
const ACCOUNTS_DIR = 'accounts';
const DEFAULT_REFRESH_SECONDS = 300;
const MIN_REFRESH_SECONDS = 30;
const TICK_SECONDS = 30;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;
const LOGIN_POLL_SECONDS = 4;
const LOGIN_POLL_TICKS = 75; // ~5 minutes

const ACCOUNTS_SCHEMA = 2;
const DISCOVER_SCHEMA = 1;
const DEFAULT_ACCOUNT_ID = 'default';
const KIND_OPENCODE_DB = 'opencode-db';
const KIND_API_KEY = 'api-key';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const AUTO_CREDENTIAL_LABEL = 'Auto (follows the active account)';
// The CLI owns the full keyring error (core/ocgo/accounts.py); the applet
// only matches this stable substring to offer the explicit file backend
// instead of surfacing the CLI's terminal-level instruction.
const SECRET_TOOL_UNAVAILABLE_MARKER = 'secret-tool is not available';
// A keyring that resolves but cannot store (no Secret Service on the session
// bus, a stalled `secret-tool`): the CLI reports the store failure with this
// fragment, and the offer's message must not claim the tool is missing.
const SECRET_TOOL_STORE_FAILED_MARKER = 'secret-tool could not store the secret';

const WINDOWS = [
    {key: 'rolling', label: 'Rolling usage', short: '5h'},
    {key: 'weekly', label: 'Weekly usage', short: '7d'},
    {key: 'monthly', label: 'Monthly usage', short: '30d'},
];

const CREDITS_ROWS = [
    {key: 'credits', label: 'Credits'},
    {key: 'extra_usage', label: 'Extra usage'},
    {key: 'auto_recharge', label: 'Auto-recharge'},
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

// Cinnamon 6.4 added imports.ui.dialog (MessageDialogContent); Cinnamon 5.4
// (Linux Mint 21) has no such module. This local replacement mirrors the 6.4
// component: same style classes and the same title/description accessors.
// The extra 'confirm-dialog-title'/'run-dialog-description' classes are what
// the 5.4 theme styles (the message-dialog-* ones exist only from 6.4).
//
// A factory, not a GObject subclass: re-importing applet.js (ReloadXlet) must
// not re-register a GObject type name — 'Type name ... is already registered'
// fails the import and kills the reload — so the component is a plain box
// with title/description accessor properties.
function MessageContent(params = {}) {
    const content = new St.BoxLayout({
        style_class: 'message-dialog-content',
        vertical: true,
        x_expand: true,
    });
    const titleLabel = new St.Label({style_class: 'message-dialog-title'});
    titleLabel.add_style_class_name('confirm-dialog-title');
    const descriptionLabel = new St.Label({style_class: 'message-dialog-description'});
    descriptionLabel.add_style_class_name('run-dialog-description');
    descriptionLabel.clutter_text.line_wrap = true;
    descriptionLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    content.add_child(titleLabel);
    content.add_child(descriptionLabel);

    let titleText = '';
    let descriptionText = '';
    Object.defineProperty(content, 'title', {
        get: () => titleText,
        set: value => {
            titleText = value || '';
            titleLabel.set_text(titleText);
        },
    });
    Object.defineProperty(content, 'description', {
        get: () => descriptionText,
        set: value => {
            descriptionText = value || '';
            descriptionLabel.set_text(descriptionText);
        },
    });
    // Seed the accessors from the parameters, like the 6.4 component does.
    content.title = params.title || '';
    content.description = params.description || '';
    return content;
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

// StBoxLayout has no 'spacing' property on Cinnamon 5.4 or 6.4 (5.4 reads it
// from the CSS 'spacing' property, 6.4 keeps it on the layout manager), so
// spacing is set through the inner Clutter.BoxLayout.
function setBoxSpacing(box, spacing) {
    if (box.layout_manager instanceof Clutter.BoxLayout)
        box.layout_manager.spacing = spacing;
}

function expandHome(path) {
    if (path === '~')
        return GLib.get_home_dir();
    if (path.startsWith('~/'))
        return GLib.build_filenamev([GLib.get_home_dir(), path.slice(2)]);
    return path;
}

// Display form of a credential-store path: a home prefix shortens to '~' so
// the dialog line stays readable.
function shortenHomePath(path) {
    const home = GLib.get_home_dir();
    if (home && path.startsWith(`${home}/`))
        return `~${path.slice(home.length)}`;
    return path;
}

function resolveExecutable(path) {
    if (!path)
        return null;
    if (!path.includes('/'))
        return GLib.find_program_in_path(path);
    return GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE) ? path : null;
}

// Deliberate copy: keep in sync with gnome/prefs.js and gnome/extension.js.
// The CLI names itself in its output — `ocgo: ...` warning prefixes,
// `(ocgo_…1234)` masked-key hints and config paths with an `ocgo` segment
// (`~/.config/ocgo/...`); strip or neutralize every such occurrence so no
// tool token reaches the UI. Clean strings pass through untouched.
function stripToolToken(text) {
    let detail = typeof text === 'string' ? text : '';
    if (!detail.includes('ocgo'))
        return detail;
    detail = detail.replace(/ocgo:\s*/g, ' ');
    detail = detail.replace(/\(ocgo_[^)]*\)/g, '');
    // `... at <ocgo-path>` reads fine without the fragment; any other
    // ocgo-bearing path (a token with a slash and the name) becomes a
    // neutral reference.
    detail = detail.replace(/\s+at\s+(?=[^\s:'"]*ocgo)(?=[^\s:'"]*\/)[^\s:'"]*/g, '');
    detail = detail.replace(/(?=[^\s:'"]*ocgo)(?=[^\s:'"]*\/)[^\s:'"]*/g, 'its config file');
    return detail.replace(/\s{2,}/g, ' ').trim();
}

// One plain-language rewrite for CLI or cache failure details, shared by the
// dialog failure path and the cached last_error render sites: strip the tool
// token first, then map the known terminal-level messages to actionable
// copy. Unknown details pass through token-stripped.
function formatFailureDetail(text) {
    let detail = stripToolToken(typeof text === 'string' ? text.trim() : '');
    if (detail.includes('No OpenCode credential found')) {
        detail = 'No OpenCode login found on this machine — use '
            + '"Log in with OpenCode…" or the API key type.';
    } else if (detail.includes('no OpenCode credential matches')) {
        detail = 'That credential is no longer available — reload the list '
            + 'and pick another one.';
    } else if (detail.includes('no secret found for account')) {
        detail = "The account's stored key is missing — add the key again "
            + 'in settings.';
    }
    return detail;
}

// Candidates to run the OpenCode login, in order: the session PATH first
// (like a terminal would), then the install locations the official
// installers use — the desktop-session PATH normally misses ~/.opencode/bin.
const OPENCODE_BINARY_CANDIDATES = [
    '~/.opencode/bin/opencode',
    '~/.local/bin/opencode',
    '~/bin/opencode',
    '~/.bun/bin/opencode',
    '~/.npm-global/bin/opencode',
    '/usr/local/bin/opencode',
    '/usr/bin/opencode',
    '/snap/bin/opencode',
];

function resolveOpenCodeBinary() {
    const onPath = GLib.find_program_in_path('opencode');
    if (onPath)
        return onPath;
    for (const candidate of OPENCODE_BINARY_CANDIDATES) {
        const resolved = resolveExecutable(expandHome(candidate));
        if (resolved)
            return resolved;
    }
    return null;
}

// Candidates to open a terminal running the login script, in order. The
// portable Debian/Mint interface comes first; the rest cover common terminals
// with their native syntax. Only a candidate whose binary resolves is tried.
function loginTerminalCandidates(script) {
    return [
        {binary: 'x-terminal-emulator', args: ['-e', 'sh', script]},
        {binary: 'gnome-terminal', args: ['--', 'sh', script]},
        {binary: 'mate-terminal', args: ['-x', 'sh', script]},
        {binary: 'xfce4-terminal', args: ['-x', 'sh', script]},
        {binary: 'konsole', args: ['-e', 'sh', script]},
        {binary: 'xterm', args: ['-e', 'sh', script]},
    ];
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

function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function creditValueMarkup(text, color) {
    return color
        ? `<span foreground="${color}">${escapeMarkup(text)}</span>`
        : escapeMarkup(text);
}

function dollarsText(value) {
    if (typeof value !== 'number' || !Number.isFinite(value))
        return null;
    return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

function creditsAmountText(available) {
    if (typeof available !== 'number' || !Number.isFinite(available))
        return '—';
    if (available > 0 && available < 0.01)
        return '<$0.01';
    return `$${available.toFixed(2)}`;
}

function creditsSuffix(state) {
    if (state === 'low')
        return {text: 'Running low', color: COLORS.amber};
    if (state === 'empty')
        return {text: 'No credits left', color: COLORS.red};
    return {text: '', color: null};
}

function autoRechargeValue(auto) {
    if (auto.failed)
        return {text: 'Failed', color: COLORS.red};
    if (auto.pending)
        return {text: 'Recharging…', color: null};
    if (auto.enabled) {
        const amount = dollarsText(auto.amount_usd);
        const threshold = dollarsText(auto.threshold_usd);
        if (amount === null || threshold === null)
            return {text: 'On', color: null};
        return {text: `Adds ${amount} below ${threshold}`, color: null};
    }
    return {text: 'Off', color: null};
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
            kind: typeof entry.kind === 'string' ? entry.kind : '',
            // Additive field (the payload keeps schema 2): null means the
            // account is not pinned to a database credential.
            credential_id: typeof entry.credential_id === 'string' &&
                entry.credential_id !== ''
                ? entry.credential_id
                : null,
            active: false,
        });
    }
    const requested = typeof payload.active === 'string' ? payload.active : null;
    const active = requested !== null && seen.has(requested) ? requested : null;
    for (const account of accounts)
        account.active = account.id === active;
    return {accounts, active};
}

// The discover payload's store block: where the CLI looked for a login and
// whether it found one. All six fields must be present with their exact
// types; anything missing or wrong sanitizes to null and callers fall back
// to the credential list alone.
function parseDiscoverStore(payload) {
    if (!isObject(payload))
        return null;
    if (typeof payload.db_path !== 'string' || payload.db_path === '')
        return null;
    if (typeof payload.db_exists !== 'boolean')
        return null;
    if (typeof payload.auth_json_path !== 'string' ||
            payload.auth_json_path === '')
        return null;
    if (typeof payload.auth_json_exists !== 'boolean')
        return null;
    if (typeof payload.auth_json_login !== 'boolean')
        return null;
    if (typeof payload.has_login !== 'boolean')
        return null;
    return {
        db_path: payload.db_path,
        db_exists: payload.db_exists,
        auth_json_path: payload.auth_json_path,
        auth_json_exists: payload.auth_json_exists,
        auth_json_login: payload.auth_json_login,
        has_login: payload.has_login,
    };
}

function parseDiscoverJson(text) {
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
    if (payload.schema !== DISCOVER_SCHEMA || !Array.isArray(payload.credentials))
        return null;

    const credentials = [];
    const seen = new Set();
    for (const entry of payload.credentials) {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry))
            return null;
        const id = entry.id;
        if (typeof id !== 'string' || id.trim() === '' || seen.has(id))
            return null;
        seen.add(id);
        credentials.push({
            id,
            label: typeof entry.label === 'string' && entry.label.trim() !== ''
                ? entry.label
                : id,
            active: entry.active === true,
            email: typeof entry.email === 'string' && entry.email.trim() !== ''
                ? entry.email
                : null,
            org_name: typeof entry.org_name === 'string' &&
                entry.org_name.trim() !== ''
                ? entry.org_name
                : null,
        });
    }
    // Additive block (the payload keeps schema 1): a malformed or missing
    // store block sanitizes to null, so the dialog degrades to the
    // credential list alone.
    return {credentials, store: parseDiscoverStore(payload.store)};
}

// Display-only suffix for a discovered credential: the email when present,
// the organization name otherwise.
function credentialDisplayLabel(credential) {
    const suffix = credential.email || credential.org_name;
    return suffix ? `${credential.label} (${suffix})` : credential.label;
}

function accountFormError(accountId, key, fromDb = false) {
    if (!accountId)
        return 'Enter an account id.';
    if (!ACCOUNT_ID_RE.test(accountId))
        return 'Invalid account id: use a-z, 0-9, dot, underscore, or dash (max 64).';
    if (!fromDb && !key)
        return 'Enter an API key.';
    return null;
}

function removeConfirmBody(kind) {
    return kind === KIND_OPENCODE_DB
        ? 'Your OpenCode login itself is not affected.'
        : 'Its stored key will be deleted.';
}

function accountCommandFor(accountId, accounts) {
    return accounts.some(account => account.id === accountId) ? 'set-key' : 'add';
}

class OpenCodeGoMeterApplet extends Applet.TextApplet {
    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);
        this._removed = false;
        this._refreshInProgress = false;
        this._refreshTimerId = 0;
        this._tickTimerId = 0;
        this._activeAccountId = null;
        this._accounts = [];
        this._credentials = [];
        this._store = null;
        this._accountsLoaded = false;
        this._accountsLoading = false;
        this._accountsError = null;
        this._accountsErrorLogged = false;
        this._credentialsError = null;
        this._credentialsErrorLogged = false;
        this._accountsGeneration = 0;
        this._accountsPending = null;
        this._initialRefreshPending = false;
        this._accountMenuSignature = null;
        this._updatingActive = false;
        this._activeOptionsSignature = null;
        this._accountsDialog = null;

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);
        this.settings.bind('refresh-interval', 'refresh_interval', () => this._onRefreshIntervalChanged());
        this.settings.bind('show-credits', 'show_credits', () => this._updateDisplay());
        this.settings.bind('active-account', 'active_account', () => this._onActiveAccountChanged());

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menuManager.addMenu(this.menu);
        this._buildMenu();

        this._updateDisplay();
        this._startTimers();
        // Resolve the account through the CLI first (the panel and the refresh
        // must follow the CLI's active account, even without a registry file).
        // The flag is consumed by the first completed account resolution, so a
        // superseding load (for example the menu opening) cannot drop the
        // initial refresh.
        this._initialRefreshPending = true;
        this._loadAccounts();
    }

    on_applet_clicked(event) {
        this.menu.toggle();
    }

    on_applet_removed_from_panel(deleteConfig) {
        // Defense in depth over the applet manager's own try/catch: the field
        // report showed a hard Cinnamon crash around removal, so a teardown
        // error must never escape this handler.
        try {
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
            if (this._accountsDialog) {
                this._accountsDialog.destroy();
                this._accountsDialog = null;
            }
            if (this.menuManager && typeof this.menuManager.destroy === 'function')
                this.menuManager.destroy();
            this.menuManager = null;
        } catch (error) {
            logError('teardown failed', error);
        }
    }

    // -- rendering -----------------------------------------------------------

    _updateDisplay() {
        if (this._removed)
            return;
        try {
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
            if (this._accountsError)
                lines.push(`Accounts unavailable: ${truncate(this._accountsError, MAX_WARNING_CHARS)}`);
            else
                lines.push('No accounts configured');
        } else {
            lines.push(`OpenCode Go · ${this._activeAccountLabel()}`);
            const updated = cache ? formatAgo(cache.fetched_at, now) : null;
            lines.push(updated ? `Updated ${updated}` : 'Updated —');
            const lastError = cache && typeof cache.last_error === 'string'
                ? cache.last_error.trim()
                : '';
            if (lastError) {
                const suffix = updated ? ` · data from ${updated}` : '';
                const detail = formatFailureDetail(lastError);
                lines.push(`Last refresh failed: ${truncate(detail, MAX_WARNING_CHARS)}${suffix}`);
            }
        }
        // Discover failures are non-fatal: the auto path keeps working.
        if (this._credentialsError)
            lines.push(`Credentials unavailable: ${truncate(this._credentialsError, MAX_WARNING_CHARS)}`);
        for (const account of this._danglingAccounts()) {
            lines.push(`Account '${account.label}' points to an OpenCode credential ` +
                'that no longer exists — remove it or sign in again in OpenCode.');
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

        this._creditsSeparatorItem = new PopupMenu.PopupSeparatorMenuItem();
        this.menu.addMenuItem(this._creditsSeparatorItem);

        this._creditsItems = new Map();
        for (const row of CREDITS_ROWS) {
            const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
            const name = new St.Label({
                text: row.label,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const value = new St.Label({
                text: '—',
                y_align: Clutter.ActorAlign.CENTER,
            });
            item.addActor(name, {expand: true});
            item.addActor(value);
            this.menu.addMenuItem(item);
            this._creditsItems.set(row.key, {item, value});
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
            const label = this._activeAccountLabel();
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
            const detail = formatFailureDetail(lastError);
            const warning = `Last refresh failed: ${truncate(detail, MAX_WARNING_CHARS)}${suffix}`;
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

        this._renderCredits(cache);

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._refreshItem.label.set_text(`Updated ${updated || '—'} · Refresh`);
    }

    _renderCredits(cache) {
        const credits = isObject(cache) && isObject(cache.credits) ? cache.credits : null;
        const extraUsage = isObject(cache) && typeof cache.extra_usage === 'boolean'
            ? cache.extra_usage
            : null;
        const autoRecharge = credits && isObject(credits.auto_recharge)
            ? credits.auto_recharge
            : null;

        const visible = this.show_credits !== false &&
            (credits !== null || extraUsage !== null);
        this._creditsSeparatorItem.actor.visible = visible;

        const creditsRow = this._creditsItems.get('credits');
        creditsRow.item.actor.visible = visible && credits !== null;
        if (credits) {
            let text = 'Unavailable';
            let color = null;
            if (typeof credits.error !== 'string') {
                text = creditsAmountText(credits.available_usd);
                const suffix = creditsSuffix(credits.state);
                if (suffix.text)
                    text = `${text} · ${suffix.text}`;
                color = suffix.color;
            }
            creditsRow.value.clutter_text.set_markup(creditValueMarkup(text, color));
        }

        const extraRow = this._creditsItems.get('extra_usage');
        extraRow.item.actor.visible = visible && extraUsage !== null;
        if (extraUsage !== null) {
            extraRow.value.clutter_text.set_markup(
                creditValueMarkup(extraUsage ? 'On' : 'Off', null));
        }

        const autoRow = this._creditsItems.get('auto_recharge');
        autoRow.item.actor.visible = visible && autoRecharge !== null;
        if (autoRecharge) {
            const auto = autoRechargeValue(autoRecharge);
            autoRow.value.clutter_text.set_markup(creditValueMarkup(auto.text, auto.color));
        }
    }

    _renderAccountMenu() {
        if (!this._accountSubMenuItem)
            return;
        const accounts = this._accounts || [];
        const dangling = this._danglingAccounts();
        const activateTarget = this._activateTargetAccount();
        const signature = `${this._accountsError || ''}\u0002` + accounts.map(account =>
            `${account.id}\u0000${this._accountDisplayLabel(account)}\u0000${account.active ? 1 : 0}`).join('\u0001') +
            `\u0003${activateTarget ? activateTarget.id : ''}` +
            `\u0004${dangling.map(account => account.id).join('\u0000')}`;
        if (signature === this._accountMenuSignature)
            return;
        if (this._accountSubMenuItem.menu.isOpen)
            return; // never destroy items while the submenu is open
        this._accountMenuSignature = signature;

        const submenu = this._accountSubMenuItem.menu;
        submenu.removeAll();
        if (accounts.length === 0) {
            const text = this._accountsError ? 'Accounts unavailable' : 'No accounts configured';
            submenu.addMenuItem(new PopupMenu.PopupMenuItem(text, {reactive: false}));
            return;
        }
        for (const account of accounts) {
            const item = new PopupMenu.PopupMenuItem(this._accountDisplayLabel(account));
            item.setOrnament(PopupMenu.OrnamentType.DOT, account.active);
            item.connect('activate', () => this._switchAccount(account.id));
            submenu.addMenuItem(item);
        }

        // Use in OpenCode: only meaningful for a pinned login; the target is
        // the account the applet currently shows (the selected one).
        submenu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const activateItem = new PopupMenu.PopupMenuItem('Use in OpenCode');
        activateItem.setSensitive(activateTarget !== null);
        if (activateTarget) {
            activateItem.connect('activate', () => {
                this._confirmActivateInOpencode(activateTarget);
            });
        }
        submenu.addMenuItem(activateItem);

        // Pinned logins whose credential disappeared: surface, never block.
        if (dangling.length > 0) {
            submenu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            for (const account of dangling) {
                const text = `Account '${account.label}': OpenCode credential missing`;
                const item = new PopupMenu.PopupMenuItem(text, {reactive: false});
                item.label.clutter_text.set_markup(
                    `<span foreground="${COLORS.amber}">${escapeMarkup(text)}</span>`);
                submenu.addMenuItem(item);
            }
        }
    }

    // The applet's selected (active) account, when it is a pinned login.
    _activateTargetAccount() {
        if (!this._activeAccountId)
            return null;
        const account = (this._accounts || []).find(
            entry => entry.id === this._activeAccountId);
        return this._isPinnedLogin(account) ? account : null;
    }

    // A pinned OpenCode login: the only kind "Use in OpenCode" applies to
    // (auto logins follow OpenCode by definition; API keys are not logins).
    _isPinnedLogin(account) {
        return !!account && account.kind === KIND_OPENCODE_DB &&
            !!account.credential_id;
    }

    // Display-only suffix marking a pinned login whose credential is the
    // active one in OpenCode.
    _accountDisplayLabel(account) {
        if (account.kind !== KIND_OPENCODE_DB || !account.credential_id)
            return account.label;
        const credential = (this._credentials || []).find(
            entry => entry.id === account.credential_id);
        return credential && credential.active
            ? `${account.label} (active in OpenCode)`
            : account.label;
    }

    // Pinned logins whose credential disappeared from the database listing.
    // Empty while discover failed: an unreadable listing cannot tell "gone"
    // from "unreadable", and the failure itself is already surfaced.
    _danglingAccounts() {
        if (this._credentialsError)
            return [];
        const known = new Set((this._credentials || []).map(entry => entry.id));
        return (this._accounts || []).filter(account =>
            account.kind === KIND_OPENCODE_DB && account.credential_id &&
            !known.has(account.credential_id));
    }

    // Credential picker entries: the auto binding when no auto login exists,
    // plus every discovered credential that is not registered yet.
    _credentialChoices() {
        const choices = [];
        if (!this._hasAutoLogin())
            choices.push({credentialId: null, label: AUTO_CREDENTIAL_LABEL});
        const registered = new Set();
        for (const account of this._accounts || []) {
            if (account.kind === KIND_OPENCODE_DB && account.credential_id)
                registered.add(account.credential_id);
        }
        for (const credential of this._credentials || []) {
            if (registered.has(credential.id))
                continue;
            choices.push({
                credentialId: credential.id,
                label: credentialDisplayLabel(credential),
            });
        }
        return choices;
    }

    _hasAutoLogin() {
        return (this._accounts || []).some(
            account => account.kind === KIND_OPENCODE_DB &&
                !account.credential_id);
    }

    // True when the CLI's store report says a login exists — a database row
    // (listed or not) or the legacy auth.json — even when the discover
    // listing is empty.
    _storeHasLogin() {
        return !!(this._store && this._store.has_login === true);
    }

    // A binding can only succeed when a login exists: the auto binding
    // resolves the active credential (or the legacy auth.json login), so it
    // is only offered while the store actually holds one (an auto account
    // without any login dead-ends on '--from-db').
    _hasBindableLogin(choices) {
        if (choices.some(choice => choice.credentialId !== null))
            return true;
        return !this._hasAutoLogin() &&
            ((this._credentials || []).length > 0 || this._storeHasLogin());
    }

    // First free account-id suggestion for the add dialog: 'work', then
    // 'work-2'…'work-99'. Empty when every candidate is taken.
    _suggestedAccountId() {
        const used = new Set((this._accounts || []).map(account => account.id));
        if (!used.has('work'))
            return 'work';
        for (let index = 2; index <= 99; index++) {
            const candidate = `work-${index}`;
            if (!used.has(candidate))
                return candidate;
        }
        return '';
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

    _activeAccountLabel() {
        const account = (this._accounts || []).find(
            entry => entry.id === this._activeAccountId);
        return account ? account.label : this._activeAccountId;
    }

    _startAccountLoad(generation, onComplete) {
        const binary = this._ocgoPath();
        if (!binary) {
            this._finishAccountLoad(
                generation, onComplete,
                {parsed: null, errorMessage: "The meter's helper is not installed — "
                    + 're-run the installer, then restart Cinnamon.', error: null},
                {parsed: null, errorMessage: "The meter's helper is not installed — "
                    + 're-run the installer, then restart Cinnamon.'});
            return;
        }
        this._accountsLoading = true;
        const accounts = {parsed: null, errorMessage: null, error: null};
        const credentials = {parsed: null, errorMessage: null};
        let remaining = 2;
        const finish = () => {
            if (--remaining > 0)
                return;
            this._accountsLoading = false;
            this._finishAccountLoad(generation, onComplete, accounts, credentials);
        };
        // Accounts and discovered credentials load together; a discover
        // failure is non-fatal (empty credential list, auto path intact).
        this._spawnAccountJson(
            binary, ['account', 'list', '--json'], parseAccountList,
            (parsed, errorMessage, error = null) => {
                accounts.parsed = parsed;
                accounts.errorMessage = errorMessage;
                accounts.error = error;
                finish();
            });
        this._spawnAccountJson(
            binary, ['account', 'discover', '--json'], parseDiscoverJson,
            (parsed, errorMessage) => {
                credentials.parsed = parsed;
                credentials.errorMessage = errorMessage;
                finish();
            });
    }

    _spawnAccountJson(binary, args, parser, callback) {
        const command = `${args[0]} ${args[1]}`;
        try {
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                if (this._removed) {
                    callback(null, null);
                    return;
                }
                if (exitCode !== 0) {
                    callback(null, `${command} failed (exit ${exitCode})`);
                    return;
                }
                const parsed = parser(stdout);
                callback(parsed, parsed ? null : `unexpected ${command} output`);
            }, {argv: [binary, ...args]});
        } catch (error) {
            callback(null, 'could not start the meter helper', error);
        }
    }

    _finishAccountLoad(generation, onComplete, accountsResult, credentialsResult) {
        if (this._removed) {
            this._accountsPending = null;
            return;
        }
        if (generation === this._accountsGeneration) {
            // Newest request: apply the result (or the fallback) and run its
            // callback on both paths, so a queued action is never dropped.
            const accounts = accountsResult ? accountsResult.parsed : null;
            const credentials = credentialsResult ? credentialsResult.parsed : null;
            // Discover failures are non-fatal: the empty credential list
            // keeps the auto path working and the error surfaces in the
            // tooltip and the journal.
            this._credentials = credentials ? credentials.credentials : [];
            // The store report rides with the credential list; on a discover
            // failure (or an old CLI payload) it is null and the dialog falls
            // back to the credential list alone.
            this._store = credentials ? credentials.store : null;
            this._credentialsError = credentialsResult
                ? credentialsResult.errorMessage
                : null;
            if (this._credentialsError) {
                if (!this._credentialsErrorLogged) {
                    this._credentialsErrorLogged = true;
                    logError(this._credentialsError);
                }
            } else {
                this._credentialsErrorLogged = false;
            }
            if (accounts) {
                this._accounts = accounts.accounts;
                this._accountsLoaded = true;
                this._accountsError = null;
                this._accountsErrorLogged = false;
                this._activeAccountId = accounts.active;
            } else {
                if (!this._accountsLoaded) {
                    this._accounts = [];
                    this._activeAccountId = null;
                }
                this._accountsLoaded = true;
                this._accountsError = accountsResult ? accountsResult.errorMessage : null;
                if (!this._accountsErrorLogged) {
                    this._accountsErrorLogged = true;
                    logError(
                        `${this._accountsError}; keeping the current account list`,
                        accountsResult ? accountsResult.error : null);
                }
            }
            this._renderAccountMenu();
            this._updateDisplay();
            this._syncAccountsSettings();
            if (this._initialRefreshPending) {
                this._initialRefreshPending = false;
                this._triggerRefresh();
            }
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
                    logError(`could not switch to account '${accountId}' (exit ${exitCode})`);
                    return;
                }
                // The CLI already switched the active account: reflect it
                // optimistically, refresh, then reconcile from the CLI.
                this._activeAccountId = accountId;
                this._updateDisplay();
                this._triggerRefresh();
                this._loadAccounts();
            }, {argv: [binary, 'account', 'use', accountId]});
        } catch (error) {
            logError(`could not start the account switch to '${accountId}'`, error);
        }
    }

    // -- account settings (preferences) --------------------------------------

    _syncAccountsSettings() {
        const options = {};
        if (this._accounts.length === 0) {
            options['No accounts'] = '';
        } else {
            // Combobox keys must be unique: duplicate labels collapse into one
            // option, hiding accounts. Labels stay bare when unique; colliding
            // ones get a deterministic '(id)' suffix. The option value is
            // always the account id. The display-only '(active in OpenCode)'
            // suffix participates in label collision handling like any other
            // part of the label.
            const counts = new Map();
            for (const account of this._accounts) {
                const label = this._accountDisplayLabel(account);
                counts.set(label, (counts.get(label) || 0) + 1);
            }
            const used = new Set();
            for (const account of this._accounts) {
                const label = this._accountDisplayLabel(account);
                let key = counts.get(label) === 1
                    ? label
                    : `${label} (${account.id})`;
                while (used.has(key))
                    key += ` (${account.id})`;
                used.add(key);
                options[key] = account.id;
            }
        }
        const signature = JSON.stringify(options);
        if (signature !== this._activeOptionsSignature) {
            this._activeOptionsSignature = signature;
            this.settings.setOptions('active-account', options);
        }
        // Reflect the real active account without triggering a switch.
        this._updatingActive = true;
        try {
            this.active_account = this._activeAccountId || '';
        } finally {
            this._updatingActive = false;
        }
    }

    _onActiveAccountChanged() {
        if (this._updatingActive)
            return;
        const id = typeof this.active_account === 'string' ? this.active_account : '';
        if (!id || id === this._activeAccountId)
            return;
        this._runAccountCommand(['account', 'use', id], null, (ok, stdout, stderr) => {
            if (this._removed)
                return;
            if (ok) {
                this._loadAccounts();
            } else {
                logError(`could not switch to account '${id}' from the settings`);
                this._syncAccountsSettings(); // restore the real active account
            }
        });
    }

    _selectedComboAccount() {
        const id = typeof this.active_account === 'string' ? this.active_account : '';
        return (this._accounts || []).find(account => account.id === id) || null;
    }

    _openAccountsDialog() {
        const dialog = new ModalDialog.ModalDialog();
        // Uniform breathing room between the dialog's rows on both themes
        // (5.4's modal-dialog-content-box sets no spacing).
        setBoxSpacing(dialog.contentLayout, 6);
        this._accountsDialog = dialog;
        // Per-dialog cleanups hang off this explicit lifecycle instead of the
        // 'destroy' signal alone: Cinnamon 5.4's close() never destroys the
        // dialog and never emits 'destroy'. This handler stays as the backstop
        // for paths that destroy the group directly (the applet teardown).
        dialog._ocgoCleanups = [];
        dialog._ocgoDisposed = false;
        dialog.connect('destroy', () => {
            dialog._ocgoDisposed = true;
            if (this._accountsDialog === dialog)
                this._accountsDialog = null;
            this._runDialogCleanups(dialog);
        });
        return dialog;
    }

    _runDialogCleanups(dialog) {
        const cleanups = dialog._ocgoCleanups || [];
        dialog._ocgoCleanups = [];
        for (const cleanup of cleanups) {
            try {
                cleanup();
            } catch (error) {
                logError('account dialog cleanup failed', error);
            }
        }
    }

    // Single close path for every account dialog. The cleanups run before the
    // close because Cinnamon 5.4 never emits 'destroy' on close.
    _closeAccountsDialog(dialog) {
        if (!dialog)
            return;
        if (this._accountsDialog === dialog)
            this._accountsDialog = null;
        this._runDialogCleanups(dialog);
        try {
            dialog.close();
        } catch (error) {
            logError('could not close the account dialog', error);
        }
        // Cinnamon 5.4 (Linux Mint 21): close() only fades and hides the dialog —
        // it never destroys it nor emits 'destroy', so without this the hidden
        // actor (and its lightbox) would leak on every open/close cycle, and the
        // 6.4 auto-destroy ('_destroyOnClose' default true) must not be repeated.
        if (!dialog._ocgoDisposed && dialog._destroyOnClose !== true) {
            try {
                dialog.destroy();
            } catch (error) {
                logError('could not destroy the account dialog', error);
            }
        }
    }

    _setDialogButtonEnabled(button, enabled) {
        if (!button)
            return;
        button.reactive = enabled;
        if (enabled)
            button.remove_style_pseudo_class('insensitive');
        else
            button.add_style_pseudo_class('insensitive');
    }

    // RadioButtonGroup (byte-identical on 5.4 and 6.4) keeps its options in a
    // private list and has no per-option API: reach the option's actor to
    // disable it, degrading to a normal option when the shape changes.
    // reactive=false alone does not block keyboard activation: St.Button still
    // emits 'clicked' on Space/Return on both versions, while focus navigation
    // gates on can_focus, so the disabled option must also leave the focus
    // chain. When the option being disabled currently holds key focus, move
    // focus to an enabled option of the same group so the keyboard cannot
    // strand on an insensitive actor.
    _setRadioOptionEnabled(group, id, enabled) {
        try {
            const entry = (group._buttons || []).find(item => item && item.id === id);
            const actor = entry && entry.button ? entry.button.actor : null;
            if (!actor)
                return;
            actor.reactive = enabled;
            actor.can_focus = enabled;
            if (enabled)
                actor.remove_style_pseudo_class('insensitive');
            else
                actor.add_style_pseudo_class('insensitive');
            if (!enabled && actor.has_key_focus()) {
                const other = (group._buttons || []).find(item =>
                    item && item.button && item.button.actor !== actor &&
                    item.button.actor.reactive);
                if (other)
                    other.button.actor.grab_key_focus();
            }
        } catch (error) {
            logError('could not update the type option state', error);
        }
    }

    _labeledRow(text, child) {
        const row = new St.BoxLayout({vertical: true, x_expand: true});
        row.add_child(new St.Label({text: text}));
        child.x_expand = true;
        row.add_child(child);
        return row;
    }

    _statusLabel() {
        const label = new St.Label({text: '', style_class: 'run-dialog-description'});
        label.clutter_text.line_wrap = true;
        return label;
    }

    // Status line shared by the account dialogs: neutral/pending text plain,
    // failure text in the theme's error color (styled on 5.4 and 6.4).
    _setStatus(label, text, failed) {
        label.set_text(text);
        if (failed)
            label.add_style_class_name('error');
        else
            label.remove_style_class_name('error');
    }

    // Writes the login helper script to the per-user runtime directory
    // (XDG_RUNTIME_DIR, 0700). The world-writable temp dir would let a symlink
    // planted at the fixed filename redirect file_set_contents, so the script
    // lives where only the user can write. The script runs through 'sh', so
    // the executable bit is best-effort only. POSIX sh: it prepends the common
    // OpenCode install dirs to PATH, runs the resolved binary (or a bare
    // 'opencode' when none resolved) and reports the real exit status instead
    // of claiming success.
    _writeLoginScript(resolvedBinary) {
        const dir = GLib.get_user_runtime_dir();
        try {
            // Best-effort: if this fails, file_set_contents below fails too
            // and the caller falls back to the clipboard command.
            GLib.mkdir_with_parents(dir, 0o700);
        } catch (error) {
            logError('could not prepare the login script directory', error);
        }
        const script = GLib.build_filenamev([dir, 'opencode-login.sh']);
        const command = resolvedBinary
            ? `'${resolvedBinary.replace(/'/g, "'\\''")}'`
            : 'opencode';
        const contents = '#!/bin/sh\n'
            + 'PATH="$HOME/.opencode/bin:$HOME/.local/bin:$HOME/bin:$PATH"\n'
            + 'export PATH\n'
            + `${command} auth login\n`
            + 'status=$?\n'
            + 'if [ "$status" -eq 0 ]; then\n'
            + '    printf "\\nLogin finished. You can close this window.\\n"\n'
            + 'elif [ "$status" -eq 127 ]; then\n'
            + '    printf "\\nOpenCode was not found. Install OpenCode for this '
            + 'user, or run \\"opencode auth login\\" in a terminal where it '
            + 'works, then press Refresh in the applet.\\n"\n'
            + 'else\n'
            + '    printf "\\nThe OpenCode login did not finish (exit code '
            + '%s).\\n" "$status"\n'
            + 'fi\n'
            + 'printf "Press Enter to close this window.\\n"\n'
            + 'read -r _\n';
        if (!GLib.file_set_contents(script, contents))
            throw new Error('could not write the login script');
        try {
            GLib.chmod(script, 0o755);
        } catch (error) {
            logError('could not mark the login script executable', error);
        }
        return script;
    }

    // Tries the terminal candidates in order and returns the binary that
    // started, or null when none did. Util.spawn returns a pid when the
    // binary resolves and undefined when it does not; a started terminal can
    // still die silently (D-Bus activation), so the return value is never
    // treated as proof the window appeared.
    _launchLoginTerminal(script) {
        for (const candidate of loginTerminalCandidates(script)) {
            if (!GLib.find_program_in_path(candidate.binary))
                continue;
            try {
                if (Util.spawn([candidate.binary, ...candidate.args]))
                    return candidate.binary;
            } catch (error) {
                logError(`could not start ${candidate.binary}`, error);
            }
        }
        return null;
    }

    // Best-effort clipboard fallback: the terminal can die silently, so the
    // manual command is what guarantees the user can finish the login.
    _copyLoginCommand() {
        try {
            St.Clipboard.get_default().set_text(
                St.ClipboardType.CLIPBOARD, 'opencode auth login');
        } catch (error) {
            logError('could not copy the login command', error);
        }
    }

    on_accounts_apply() {
        if (this._accountsDialog)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog._ocgoCleanups.push(() => {
            closed = true;
        });

        const content = new MessageContent({
            title: 'Add / replace account key',
            description: 'API-key accounts from the OpenCode console. The key is '
                + 'verified with OpenCode and is never stored by the applet.',
        });
        dialog.contentLayout.add_child(content);

        // First-run affordance: with no discoverable OpenCode login (or an
        // unreadable credential store) the "OpenCode login" type can only
        // dead-end, so the login path and the API-key path are offered up
        // front. The block is always built and hidden while a login is
        // available; refreshGuidedState() owns its visibility and content.
        const helper = new St.BoxLayout({vertical: true, x_expand: true});
        setBoxSpacing(helper, 4);
        const helperLabel = new St.Label({text: ''});
        helperLabel.clutter_text.line_wrap = true;
        helperLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        helper.add_child(helperLabel);
        // Second line for the no-login state: the credential-store paths the
        // CLI checked (the database, plus auth.json when the legacy file
        // exists), so the empty state is self-diagnosable.
        const storeLabel = new St.Label({text: ''});
        storeLabel.clutter_text.line_wrap = true;
        storeLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        helper.add_child(storeLabel);

        // Both button classes: 'modal-dialog-button' styles on Cinnamon
        // 5.4 themes, 'dialog-button' on 6.4 themes.
        const helperButtons = new St.BoxLayout({
            style_class: 'modal-dialog-button-box ocgo-helper-buttons',
        });
        setBoxSpacing(helperButtons, 6);
        // Always offered: "opencode auth login" creates (or repairs) the
        // credential store, and it is also the recovery path when the store
        // itself could not be read.
        const loginButton = new St.Button({
            style_class: 'modal-dialog-button dialog-button',
            label: 'Log in with OpenCode…',
            reactive: true,
            can_focus: true,
        });
        loginButton.connect('clicked', () => {
            // The desktop-session PATH normally misses the user's OpenCode
            // install, so resolve the binary explicitly before anything runs.
            const binary = resolveOpenCodeBinary();
            if (!binary) {
                // No script and no terminal: the login would only die with
                // "command not found", so point at the manual path instead.
                this._copyLoginCommand();
                this._setStatus(status, 'OpenCode was not found on this '
                    + 'machine. Install OpenCode, or run "opencode auth login" '
                    + 'in a terminal where it works (the command is on your '
                    + 'clipboard), then press Refresh.', true);
                return;
            }
            let script = null;
            try {
                script = this._writeLoginScript(binary);
            } catch (error) {
                logError('could not prepare the login script', error);
            }
            if (!script) {
                this._copyLoginCommand();
                this._setStatus(status, 'Could not prepare the login. '
                    + '"opencode auth login" is on your clipboard — paste it '
                    + 'into a terminal, then press Refresh.', true);
                return;
            }
            const terminal = this._launchLoginTerminal(script);
            // Always copied: a spawned terminal can die silently (D-Bus
            // activation) and its exit status is not trustworthy, so the
            // manual command is the guaranteed fallback.
            this._copyLoginCommand();
            if (terminal) {
                this._setStatus(status, 'Terminal opened — complete the login '
                    + 'in your browser. If no window appeared, the command is '
                    + 'on your clipboard.', false);
            } else {
                this._setStatus(status, 'Could not open a terminal. '
                    + '"opencode auth login" is on your clipboard — paste it '
                    + 'into a terminal, then press Refresh.', true);
            }
            startLoginPoll();
        });
        helperButtons.add_child(loginButton);

        const refreshButton = new St.Button({
            style_class: 'modal-dialog-button dialog-button',
            label: 'Refresh',
            reactive: true,
            can_focus: true,
        });
        refreshButton.connect('clicked', () => {
            this._setStatus(status, 'Reloading accounts and credentials…', false);
            this._loadAccounts(() => {
                if (this._removed)
                    return;
                // The refresh updates this dialog in place: a
                // destroy-and-recreate cycle proved fragile while this was
                // developed and the root cause is not settled, so the open
                // dialog is reused instead of torn down. refreshGuidedState()
                // owns the helper block (message, store paths, visibility).
                refreshGuidedState();
                if (this._credentialsError) {
                    this._setStatus(status,
                        'Could not reload the OpenCode credential store.', true);
                } else if ((this._credentials || []).length === 0 &&
                        !this._storeHasLogin()) {
                    this._setStatus(status, 'No new credentials found yet.', false);
                } else {
                    this._setStatus(status, 'Credentials reloaded.', false);
                }
            });
        });
        helperButtons.add_child(refreshButton);

        helper.add_child(helperButtons);
        dialog.contentLayout.add_child(helper);

        const idEntry = new St.Entry({hint_text: 'e.g. work', x_expand: true});
        idEntry.set_text(this._suggestedAccountId());
        const labelEntry = new St.Entry({hint_text: 'optional', x_expand: true});
        const keyEntry = new St.Entry({hint_text: 'oc_sk_…', x_expand: true});
        keyEntry.clutter_text.set_password_char('\u25cf');

        // Both types are always listed: the "OpenCode login" type is disabled
        // (via _setRadioOptionEnabled) when no binding can succeed — no
        // discovered credential is free to bind and the auto entry cannot
        // resolve one either — so the dead end is visible up front instead of
        // failing on submit.
        const choices = this._credentialChoices();
        const allowLogin = this._hasBindableLogin(choices);
        const typeChooser = new RadioButton.RadioButtonGroup();
        typeChooser.addButton(KIND_OPENCODE_DB, 'OpenCode login');
        typeChooser.addButton(KIND_API_KEY, 'API key');
        this._setRadioOptionEnabled(typeChooser, KIND_OPENCODE_DB, allowLogin);
        typeChooser.setActive(allowLogin ? KIND_OPENCODE_DB : KIND_API_KEY);

        dialog.contentLayout.add_child(this._labeledRow('Account id', idEntry));
        const idHint = new St.Label({
            text: 'Just a name for this account here — it does not need to match '
                + 'anything in OpenCode.',
        });
        idHint.clutter_text.line_wrap = true;
        idHint.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        dialog.contentLayout.add_child(idHint);
        dialog.contentLayout.add_child(this._labeledRow('Label (optional)', labelEntry));
        dialog.contentLayout.add_child(this._labeledRow('Type', typeChooser.actor));

        // Credential combo: a themed button opening a popup menu (the
        // in-process Cinnamon combo pattern; modal dialogs can host popups).
        // Both button classes: 'dialog-button' styles inside the 6.4 dialog,
        // 'modal-dialog-button' is the 5.4 theme's dialog button. The text is
        // St.Button's own label — the theme styles it with the button; a plain
        // child St.Label inherits no color and renders invisible on 6.4.
        let selectedCredential = choices.length > 0 ? choices[0] : null;
        const combo = new St.Button({
            style_class: 'dialog-button modal-dialog-button',
            reactive: true,
            can_focus: true,
            x_expand: true,
            label: selectedCredential ? selectedCredential.label : 'No credentials found',
        });
        const credentialMenu = new PopupMenu.PopupMenu(combo, St.Side.TOP);
        const menuManager = new PopupMenu.PopupMenuManager({actor: combo});
        Main.uiGroup.add_actor(credentialMenu.actor);
        credentialMenu.actor.hide();
        menuManager.addMenu(credentialMenu);
        combo.connect('clicked', () => credentialMenu.toggle());
        // (Re)builds the combo entries from the discovered credentials; the
        // Refresh button calls it again after a terminal login.
        const populateCredentialChoices = () => {
            const fresh = this._credentialChoices();
            credentialMenu.removeAll();
            for (const choice of fresh) {
                const item = new PopupMenu.PopupMenuItem(choice.label);
                item.connect('activate', () => {
                    selectedCredential = choice;
                    combo.label = choice.label;
                });
                credentialMenu.addMenuItem(item);
            }
            if (!fresh.some(choice => selectedCredential &&
                    choice.credentialId === selectedCredential.credentialId))
                selectedCredential = fresh.length > 0 ? fresh[0] : null;
            combo.label = selectedCredential
                ? selectedCredential.label
                : 'No credentials found';
        };
        // "Looked in: …" line for the no-login helper: the paths the CLI
        // checked, with the home prefix shortened.
        const storePathsMessage = () => {
            let text = `Looked in: ${shortenHomePath(this._store.db_path)}`;
            if (this._store.auth_json_exists)
                text += ` and ${shortenHomePath(this._store.auth_json_path)}`;
            return text;
        };
        // Recomputes the guided state in place after a reload (the Refresh
        // button, the silent reload on open, and the login poll): the login
        // type depends on whether a login is bindable, the combo must follow
        // the fresh credential list, and the helper block (message, checked
        // paths, visibility) reflects the fresh store. The optional override
        // forces an explicit helper line and visibility (the poll's
        // "detected" message).
        const refreshGuidedState = (helperOverride = null) => {
            const fresh = this._credentialChoices();
            const freshAllowLogin = this._hasBindableLogin(fresh);
            this._setRadioOptionEnabled(typeChooser, KIND_OPENCODE_DB, freshAllowLogin);
            // The reload can remove the last bindable login while the login
            // type is active: keeping it selected would submit from the
            // disabled type, so fall back to the API-key type.
            if (!freshAllowLogin && selectedType() === KIND_OPENCODE_DB)
                typeChooser.setActive(KIND_API_KEY);
            populateCredentialChoices();

            const noLogin = !this._credentialsError &&
                (this._credentials || []).length === 0 && !this._storeHasLogin();
            if (helperOverride !== null) {
                helper.visible = true;
                helperLabel.set_text(helperOverride);
            } else if (this._credentialsError) {
                helper.visible = true;
                helperLabel.set_text('Could not read the OpenCode credential store. '
                    + truncate(this._credentialsError, MAX_WARNING_CHARS));
            } else {
                helper.visible = noLogin;
                helperLabel.set_text('No OpenCode login found on this machine. '
                    + 'Log in below, or add an API-key account.');
            }
            // The checked paths ride under the no-login message only.
            storeLabel.visible = helperOverride === null && noLogin && !!this._store;
            storeLabel.set_text(storeLabel.visible ? storePathsMessage() : '');
            return {allowLogin: freshAllowLogin, choices: fresh};
        };

        // Detection poll: after a login attempt, watch the credential store
        // for a credential id that was not there when the button was clicked
        // (~5 minutes). It updates the dialog in place and stops on detection,
        // timeout, or dialog close (through the cleanups).
        let loginPollId = 0;
        let loginPollTicks = 0;
        let loginPollSerial = 0;
        const stopLoginPoll = () => {
            if (loginPollId) {
                Mainloop.source_remove(loginPollId);
                loginPollId = 0;
            }
        };
        dialog._ocgoCleanups.push(stopLoginPoll);
        const startLoginPoll = () => {
            if (loginPollId)
                return; // one poll at a time
            const serial = ++loginPollSerial;
            const baseline = new Set(
                (this._credentials || []).map(credential => credential.id));
            // Legacy logins never appear in the credentials list: a login
            // landing in auth.json is detected through has_login alone.
            const baselineHasLogin = this._storeHasLogin();
            loginPollTicks = 0;
            loginPollId = Mainloop.timeout_add_seconds(LOGIN_POLL_SECONDS, () => {
                if (this._removed || closed) {
                    loginPollId = 0;
                    return false;
                }
                loginPollTicks += 1;
                const lastTick = loginPollTicks >= LOGIN_POLL_TICKS;
                this._loadAccounts(() => {
                    if (this._removed || closed || serial !== loginPollSerial)
                        return; // closed, or a newer poll replaced this one
                    const detected = (this._credentials || []).some(
                        credential => !baseline.has(credential.id)) ||
                        (!baselineHasLogin && this._storeHasLogin());
                    if (detected) {
                        stopLoginPoll();
                        refreshGuidedState('OpenCode login detected.');
                        this._setStatus(status, 'OpenCode login detected — '
                            + 'the login can be added now.', false);
                        return;
                    }
                    if (lastTick) {
                        stopLoginPoll();
                        this._setStatus(status, 'Still no OpenCode login detected — '
                            + 'finish the login, then press Refresh.', false);
                    }
                });
                if (lastTick)
                    loginPollId = 0;
                return !lastTick;
            });
        };

        const credentialRow = this._labeledRow('Credential', combo);
        // Same class trick as the helper row: the combo button needs the
        // theme's dialog-button chrome as a descendant of the box class.
        credentialRow.add_style_class_name('modal-dialog-button-box');
        credentialRow.add_style_class_name('ocgo-helper-buttons');
        credentialRow.visible = false;
        dialog.contentLayout.add_child(credentialRow);
        dialog._ocgoCleanups.push(() => {
            // Guarded like the applet's own menu manager: 5.4 and 6.4 both
            // expose destroy(), but never trust the class shape here.
            if (menuManager && typeof menuManager.destroy === 'function')
                menuManager.destroy();
            credentialMenu.close(false);
            credentialMenu.destroy();
        });

        const keyRow = this._labeledRow('API key', keyEntry);
        dialog.contentLayout.add_child(keyRow);

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let closeTimerId = 0;
        dialog._ocgoCleanups.push(() => {
            if (closeTimerId) {
                Mainloop.source_remove(closeTimerId);
                closeTimerId = 0;
            }
        });

        // Keyring-less fallback state (field report 4b): set when an API-key
        // submit fails with SECRET_TOOL_UNAVAILABLE_MARKER, so the next confirm
        // click re-runs the same command with '--store file'. A type switch
        // clears it (updateTypeState); closing the dialog drops it with the
        // closure.
        let fileFallbackOffered = false;

        const selectedType = () => typeChooser.getActive();
        // Initial guided state: helper visibility and message, checked
        // paths, radio enablement and the combo all come from this one path.
        refreshGuidedState();

        const submit = () => {
            const accountId = idEntry.get_text().trim();
            const label = labelEntry.get_text().trim();
            const fromDb = selectedType() === KIND_OPENCODE_DB;
            // A pending keyring-less offer turns this submit into the file
            // backend retry: same command, '--store file' instead of 'auto'
            // (the CLI's deliberate explicit opt-in). Captured before the
            // offer flag is consumed below.
            const useFileStore = !fromDb && fileFallbackOffered;
            const key = fromDb ? '' : keyEntry.get_text();
            const error = accountFormError(accountId, key, fromDb);
            if (error) {
                this._setStatus(status, error, true);
                return;
            }
            let args;
            let pendingText;
            if (fromDb) {
                // The CLI registers an OpenCode login; no key, no stdin.
                // Without --credential the account follows the active
                // OpenCode credential (the auto entry).
                // Backstop only: the login type is disabled when no
                // credential is bindable, so this submit cannot normally run.
                // The auto entry (credentialId null) needs a login in the
                // store to resolve — a listed credential or the legacy
                // auth.json login — so it counts as missing when the store
                // holds neither.
                if (!selectedCredential ||
                        (selectedCredential.credentialId === null &&
                            (this._credentials || []).length === 0 &&
                            !this._storeHasLogin())) {
                    this._setStatus(status, 'No OpenCode login found — use '
                        + '"Log in with OpenCode…" or the API key type.', true);
                    return;
                }
                args = ['account', 'add', accountId, '--from-db'];
                if (label)
                    args.push('--label', label);
                if (selectedCredential.credentialId)
                    args.push('--credential', selectedCredential.credentialId);
                pendingText = `Adding the OpenCode login as '${accountId}'…`;
            } else {
                const command = accountCommandFor(accountId, this._accounts);
                args = ['account', command, accountId, '--store',
                    useFileStore ? 'file' : 'auto'];
                if (command === 'add' && label)
                    args.push('--label', label);
                pendingText = useFileStore
                    ? 'Storing the key in a local file…'
                    : command === 'add'
                        ? `Adding account '${accountId}'…`
                        : `Replacing the key for '${accountId}'…`;
            }
            // The offer is consumed by this run: the retry must take one
            // click, and any later failure goes back to the normal branch.
            fileFallbackOffered = false;
            this._setDialogButtonEnabled(confirmInfo.button, false);
            this._setStatus(status, pendingText, false);
            this._runAccountCommand(args, fromDb ? null : key, (ok, stdout, stderr) => {
                if (this._removed)
                    return;
                if (ok)
                    this._loadAccounts();
                if (closed)
                    return;
                // The CLI's keyring-or-error contract is deliberate; the
                // applet only offers the file backend when the failure names
                // the keyring. Two markers: the binary missing, and a keyring
                // that resolves but cannot store (no keyring service, timeout).
                // stderr first, stdout as the fallback — the same detail
                // _failureMessage picks.
                const detail = stderr || stdout || '';
                const keyringUnavailable = detail.includes(SECRET_TOOL_UNAVAILABLE_MARKER);
                const keyringStoreFailed = detail.includes(SECRET_TOOL_STORE_FAILED_MARKER);
                const keyringMissing = !ok && !fromDb && !useFileStore &&
                    (keyringUnavailable || keyringStoreFailed);
                if (!keyringMissing) {
                    // The key never stays in the entry beyond the command.
                    // Exception (field report 4b): a missing-keyring failure
                    // keeps it, because the command did not complete and the
                    // retry must not ask the user to paste it again.
                    keyEntry.set_text('');
                }
                // A completed file-store retry (success or failure) ends the
                // offer: the confirm button goes back to the API-key type's
                // label, exactly as updateTypeState assigns it.
                if (useFileStore)
                    confirmInfo.button.label = 'Add / replace key';
                if (ok) {
                    const summary = stripToolToken(
                        [stdout.trim(), stderr.trim()].filter(Boolean).join(' '));
                    this._setStatus(status, summary || `Account '${accountId}' updated.`, false);
                    closeTimerId = Mainloop.timeout_add(1200, () => {
                        closeTimerId = 0;
                        this._closeAccountsDialog(dialog);
                        return false;
                    });
                } else if (keyringMissing) {
                    // Two-step offer (field report 4b, extended in report 5):
                    // keep the typed key, explain without the CLI's
                    // terminal-level wording, and let the next confirm click
                    // retry with '--store file'. Two causes, two messages — a
                    // runtime keyring failure must not claim the tool is
                    // missing. No close timer: the user decides.
                    fileFallbackOffered = true;
                    confirmInfo.button.label = 'Store in a local file';
                    this._setStatus(status, keyringUnavailable
                        ? 'The system keyring (libsecret-tools) is not '
                            + 'installed. Press "Store in a local file" to keep '
                            + 'the key in a private file that only your user can '
                            + 'read — or install libsecret-tools and try again.'
                        : 'The system keyring is unavailable in this session '
                            + '(no keyring service answered). Press "Store in a '
                            + 'local file" to keep the key in a private file '
                            + 'that only your user can read.', true);
                    this._setDialogButtonEnabled(confirmInfo.button, true);
                } else {
                    this._setStatus(status, this._failureMessage(
                        fromDb ? 'could not add the OpenCode login account'
                            : 'could not update the account',
                        stderr, stdout), true);
                    this._setDialogButtonEnabled(confirmInfo.button, true);
                }
            });
        };

        const confirmInfo = {
            label: 'Add / replace key',
            action: submit,
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => this._closeAccountsDialog(dialog),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);

        const updateTypeState = () => {
            const fromDb = selectedType() === KIND_OPENCODE_DB;
            // A type switch cancels a pending keyring-less offer: the
            // type-driven label assignment below drops the
            // 'Store in a local file' relabel too, and the offer's stale
            // explanation must not survive pointing at a now-hidden key field.
            if (fileFallbackOffered) {
                fileFallbackOffered = false;
                status.set_text('');
            }
            keyRow.visible = !fromDb;
            credentialRow.visible = fromDb;
            if (fromDb)
                keyEntry.set_text('');
            if (!fromDb)
                credentialMenu.close();
            content.title = fromDb ? 'Add account' : 'Add / replace account key';
            content.description = fromDb
                ? 'Registers an OpenCode login. Pick the auto binding (follows ' +
                    'the active OpenCode credential) or a discovered credential.'
                : 'API-key accounts from the OpenCode console. The key is '
                    + 'verified with OpenCode and is never stored by the applet.';
            confirmInfo.button.label = fromDb ? 'Add account' : 'Add / replace key';
        };
        typeChooser.connect('radio-changed', () => updateTypeState());
        updateTypeState();
        dialog.setInitialKeyFocus(idEntry);
        if (dialog.open() === false) {
            // pushModal failed (another modal owns the screen): the dialog never
            // opened, so close() would be a no-op on 6.4 — destroy directly; the
            // guarded 'destroy' handler clears the reference and runs the cleanups.
            dialog.destroy();
        }
        // Silent freshness reload: a login made outside the dialog (for
        // example in a terminal) must not leave a stale "no login found"
        // behind. No status change from this reload.
        this._loadAccounts(() => {
            if (closed)
                return;
            refreshGuidedState();
        });
    }

    on_accounts_remove() {
        if (this._accountsDialog)
            return;
        const account = this._selectedComboAccount();
        if (!account)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog._ocgoCleanups.push(() => {
            closed = true;
        });

        dialog.contentLayout.add_child(new MessageContent({
            title: `Remove account '${account.label}'?`,
            description: removeConfirmBody(account.kind),
        }));

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        const confirmInfo = {
            label: 'Remove',
            action: () => {
                this._setDialogButtonEnabled(confirmInfo.button, false);
                this._setStatus(status, 'Removing…', false);
                this._runAccountCommand(['account', 'remove', account.id], null, (ok, stdout, stderr) => {
                    if (this._removed)
                        return;
                    if (ok) {
                        this._loadAccounts();
                        if (!closed)
                            this._closeAccountsDialog(dialog);
                        return;
                    }
                    if (closed)
                        return;
                    this._setStatus(status, this._failureMessage(
                        'could not remove the account', stderr, stdout), true);
                    this._setDialogButtonEnabled(confirmInfo.button, true);
                });
            },
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => this._closeAccountsDialog(dialog),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);
        if (dialog.open() === false) {
            // pushModal failed (another modal owns the screen): the dialog never
            // opened, so close() would be a no-op on 6.4 — destroy directly; the
            // guarded 'destroy' handler clears the reference and runs the cleanups.
            dialog.destroy();
        }
    }

    // Settings-dialog entry point for "Use in OpenCode…". Mirrors the
    // Remove button's handling: one accounts dialog at a time; a pinned login
    // goes to the shared confirmation flow (same as the popup submenu item),
    // anything else gets an explainer instead of a silent no-op.
    on_accounts_activate() {
        if (this._accountsDialog)
            return;
        const account = this._selectedComboAccount();
        if (!this._isPinnedLogin(account)) {
            this._openActivateExplainer(account);
            return;
        }
        this._confirmActivateInOpencode(account);
    }

    // Explains "Use in OpenCode…" when it does not apply: only a pinned
    // OpenCode login can become the credential OpenCode itself uses. Purpose
    // first (two sentences at most), then the concrete next step.
    _openActivateExplainer(account) {
        const dialog = this._openAccountsDialog();
        const lead = account
            ? `The selected account '${account.label}' is not a pinned OpenCode login. `
            : 'No account is selected above. ';
        const purpose = account
            ? 'Use in OpenCode makes OpenCode itself use one of your pinned '
                + 'logins for new OpenCode sessions; only pinned logins can be used.'
            : 'Use in OpenCode makes OpenCode itself use one of your pinned '
                + 'logins for new OpenCode sessions.';
        const nextStep = account
            ? 'Add one with "Add / replace key…" (type "OpenCode login", pick '
                + 'a specific credential).'
            : 'Select a pinned OpenCode login above first — or add one with '
                + '"Add / replace key…" (type "OpenCode login").';
        dialog.contentLayout.add_child(new MessageContent({
            title: 'Use in OpenCode',
            description: `${lead}${purpose} ${nextStep}`,
        }));
        dialog.setButtons([
            {
                label: 'OK',
                action: () => this._closeAccountsDialog(dialog),
                key: Clutter.KEY_Escape,
                default: true,
            },
        ]);
        if (dialog.open() === false) {
            // pushModal failed (another modal owns the screen): the dialog never
            // opened, so close() would be a no-op on 6.4 — destroy directly; the
            // guarded 'destroy' handler clears the reference and runs the cleanups.
            dialog.destroy();
        }
    }

    _confirmActivateInOpencode(account) {
        if (this._accountsDialog)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog._ocgoCleanups.push(() => {
            closed = true;
        });

        dialog.contentLayout.add_child(new MessageContent({
            title: `Use '${account.label}' in OpenCode?`,
            description: 'OpenCode will use this login for new sessions. '
                + 'The applet keeps showing the account selected in the menu.',
        }));

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let closeTimerId = 0;
        dialog._ocgoCleanups.push(() => {
            if (closeTimerId) {
                Mainloop.source_remove(closeTimerId);
                closeTimerId = 0;
            }
        });

        const confirmInfo = {
            label: 'Use in OpenCode',
            action: () => {
                this._setDialogButtonEnabled(confirmInfo.button, false);
                this._setStatus(status, 'Pointing OpenCode at this login…', false);
                this._runAccountCommand(
                    ['account', 'activate-in-opencode', account.id], null,
                    (ok, stdout, stderr) => {
                        if (this._removed)
                            return;
                        if (ok)
                            this._loadAccounts();
                        if (closed)
                            return;
                        if (ok) {
                            const summary = stripToolToken(
                                [stdout.trim(), stderr.trim()].filter(Boolean).join(' '));
                            this._setStatus(status, summary ||
                                `Account '${account.id}' is now OpenCode's login.`, false);
                            closeTimerId = Mainloop.timeout_add(1200, () => {
                                closeTimerId = 0;
                                this._closeAccountsDialog(dialog);
                                return false;
                            });
                            return;
                        }
                        this._setStatus(status, this._failureMessage(
                            'could not set the OpenCode login',
                            stderr, stdout), true);
                        this._setDialogButtonEnabled(confirmInfo.button, true);
                    });
            },
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => this._closeAccountsDialog(dialog),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);
        if (dialog.open() === false) {
            // pushModal failed (another modal owns the screen): the dialog never
            // opened, so close() would be a no-op on 6.4 — destroy directly; the
            // guarded 'destroy' handler clears the reference and runs the cleanups.
            dialog.destroy();
        }
    }

    _failureMessage(fallback, stderr, stdout) {
        return formatFailureDetail(stderr || stdout) || fallback;
    }

    _runAccountCommand(args, stdinText, callback) {
        const binary = this._ocgoPath();
        if (!binary) {
            callback(false, '', "The meter's helper is not installed — "
                + 're-run the installer, then restart Cinnamon.');
            return;
        }
        try {
            // argv array only; when stdinText is set it travels through the
            // stdin pipe (opts.input), never through argv or the journal.
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                callback(exitCode === 0, stdout || '', stderr || '');
            }, {
                argv: [binary, ...args],
                input: stdinText === null ? null : `${stdinText}\n`,
            });
        } catch (error) {
            callback(false, '', `could not start the meter helper: ${error.message ?? error}`);
        }
    }

    // -- cache ---------------------------------------------------------------

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

    // The helper is looked up at its standard install location and then on
    // PATH, mirroring the GNOME extension. There is no user-facing override.
    _ocgoPath() {
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
        if (this._accountsLoaded && !this._activeAccountId)
            return; // known-empty list: there is no account to refresh
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
                if (exitCode !== 0)
                    logError(`refresh exited with status ${exitCode}`);
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
