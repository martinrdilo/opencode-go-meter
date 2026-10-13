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
const GObject = imports.gi.GObject;
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

const ACCOUNTS_SCHEMA = 2;
const DISCOVER_SCHEMA = 1;
const DEFAULT_ACCOUNT_ID = 'default';
const KIND_OPENCODE_DB = 'opencode-db';
const KIND_API_KEY = 'api-key';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const AUTO_CREDENTIAL_LABEL = 'Auto (follows the active account)';

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
const MessageContent = GObject.registerClass(
class MessageContent extends St.BoxLayout {
    _init(params = {}) {
        super._init({
            style_class: 'message-dialog-content',
            vertical: true,
            x_expand: true,
        });
        this._titleLabel = new St.Label({style_class: 'message-dialog-title'});
        this._descriptionLabel = new St.Label({style_class: 'message-dialog-description'});
        this._descriptionLabel.clutter_text.line_wrap = true;
        this._descriptionLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        this.add_child(this._titleLabel);
        this.add_child(this._descriptionLabel);
        this.title = params.title || '';
        this.description = params.description || '';
    }

    get title() {
        return this._titleLabel.text;
    }

    set title(value) {
        this._titleLabel.set_text(value || '');
    }

    get description() {
        return this._descriptionLabel.text;
    }

    set description(value) {
        this._descriptionLabel.set_text(value || '');
    }
});

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
    return {credentials};
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
        this.settings.bind('ocgo-path', 'ocgo_path', null);
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
        this.menuManager = null;
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
                lines.push(`Last refresh failed: ${truncate(lastError, MAX_WARNING_CHARS)}${suffix}`);
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

        // Make active in OpenCode: only meaningful for a pinned login; the
        // target is the account the applet currently shows (the selected one).
        submenu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const activateItem = new PopupMenu.PopupMenuItem('Make active in OpenCode');
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

    // A pinned OpenCode login: the only kind "Make active in OpenCode" applies
    // to (auto logins follow OpenCode by definition; API keys are not logins).
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
                {parsed: null, errorMessage: 'ocgo not found', error: null},
                {parsed: null, errorMessage: 'ocgo not found'});
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
        const command = `ocgo ${args[0]} ${args[1]}`;
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
            callback(null, `could not start ${command}`, error);
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
        this._accountsDialog = dialog;
        dialog.connect('destroy', () => {
            if (this._accountsDialog === dialog)
                this._accountsDialog = null;
        });
        return dialog;
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

    _labeledRow(text, child) {
        const row = new St.BoxLayout({vertical: true, x_expand: true});
        row.add_child(new St.Label({text: text}));
        child.x_expand = true;
        row.add_child(child);
        return row;
    }

    _statusLabel() {
        const label = new St.Label({text: ''});
        label.clutter_text.line_wrap = true;
        return label;
    }

    on_accounts_apply() {
        if (this._accountsDialog)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog.connect('destroy', () => {
            closed = true;
        });

        const content = new MessageContent({
            title: 'Add / replace account key',
            description: 'API-key accounts from the OpenCode console. The key is sent to '
                + 'the ocgo CLI and is never stored by the applet.',
        });
        dialog.contentLayout.add_child(content);

        // First-run affordance: with no discovered OpenCode login (or an
        // unreadable credential store) the "OpenCode login" type can only
        // dead-end, so the browser login path is offered up front.
        const noCredentials = (this._credentials || []).length === 0;
        if (noCredentials || this._credentialsError) {
            const helper = new St.BoxLayout({vertical: true, x_expand: true});
            setBoxSpacing(helper, 4);
            const helperLabel = new St.Label({
                text: this._credentialsError
                    ? 'Could not read the OpenCode credential store. '
                        + truncate(this._credentialsError, MAX_WARNING_CHARS)
                    : 'No OpenCode login found on this machine.',
            });
            helperLabel.clutter_text.line_wrap = true;
            helperLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            helper.add_child(helperLabel);

            // Both button classes: 'modal-dialog-button' styles on Cinnamon
            // 5.4 themes, 'dialog-button' on 6.4 themes.
            const helperButtons = new St.BoxLayout();
            setBoxSpacing(helperButtons, 6);
            if (!this._credentialsError) {
                const loginButton = new St.Button({
                    style_class: 'modal-dialog-button dialog-button',
                    label: 'Log in with OpenCode…',
                    reactive: true,
                    can_focus: true,
                });
                loginButton.connect('clicked', () => {
                    try {
                        const script = GLib.build_filenamev(
                            [GLib.get_tmp_dir(), 'ocgo-opencode-login.sh']);
                        GLib.file_set_contents(script, '#!/bin/sh\nopencode auth login\nprintf "\\nLogin finished — you can close this window.\\n"\nread -r _\n');
                        GLib.chmod(script, 0o755);
                        if (!Util.spawn(['x-terminal-emulator', '-e', script]))
                            throw new Error('x-terminal-emulator could not be started');
                        status.set_text('Terminal opened — complete the login in your ' +
                            'browser, then press Refresh.');
                    } catch (error) {
                        logError('could not open the login terminal', error);
                        status.set_text('Could not open a terminal — run this command: ' +
                            'opencode auth login');
                    }
                });
                helperButtons.add_child(loginButton);
            }

            const refreshButton = new St.Button({
                style_class: 'modal-dialog-button dialog-button',
                label: 'Refresh',
                reactive: true,
                can_focus: true,
            });
            refreshButton.connect('clicked', () => {
                status.set_text('Reloading accounts and credentials…');
                this._loadAccounts(() => {
                    if (this._removed)
                        return;
                    // The refresh updates this dialog in place: destroying it
                    // (or letting it be collected after a close) aborts
                    // Cinnamon with a clutter_actor_dispose assertion when the
                    // dialog holds focusable children, so it is never torn
                    // down while the applet lives.
                    populateCredentialChoices();
                    if (this._credentialsError) {
                        helper.visible = true;
                        helperLabel.set_text('Could not read the OpenCode credential store. '
                            + truncate(this._credentialsError, MAX_WARNING_CHARS));
                        status.set_text('Could not reload the OpenCode credential store.');
                    } else if ((this._credentials || []).length === 0) {
                        helper.visible = true;
                        helperLabel.set_text('No OpenCode login found on this machine.');
                        status.set_text('Still no OpenCode login found on this machine.');
                    } else {
                        helper.visible = false;
                        status.set_text('Credentials reloaded.');
                    }
                });
            });
            helperButtons.add_child(refreshButton);

            helper.add_child(helperButtons);
            dialog.contentLayout.add_child(helper);
        }

        const idEntry = new St.Entry({hint_text: 'e.g. work', x_expand: true});
        const labelEntry = new St.Entry({hint_text: 'optional', x_expand: true});
        const keyEntry = new St.Entry({hint_text: 'oc_sk_…', x_expand: true});
        keyEntry.clutter_text.set_password_char('\u25cf');

        // The "OpenCode login" type stays available while no auto (unpinned)
        // login is registered yet, or while at least one discovered credential
        // is not registered as a pinned login. Otherwise only API keys remain.
        const choices = this._credentialChoices();
        const allowLogin = !this._hasAutoLogin() ||
            choices.some(choice => choice.credentialId !== null);
        const typeChooser = new RadioButton.RadioButtonGroup();
        if (allowLogin)
            typeChooser.addButton(KIND_OPENCODE_DB, 'OpenCode login');
        typeChooser.addButton(KIND_API_KEY, 'API key');
        // With no discovered credential to bind, default to the API key so
        // the first submit can succeed instead of dead-ending on --from-db.
        typeChooser.setActive(allowLogin && !noCredentials ? KIND_OPENCODE_DB : KIND_API_KEY);

        dialog.contentLayout.add_child(this._labeledRow('Account id', idEntry));
        dialog.contentLayout.add_child(this._labeledRow('Label (optional)', labelEntry));
        dialog.contentLayout.add_child(this._labeledRow('Type', typeChooser.actor));

        // Credential combo: a themed button opening a popup menu (the
        // in-process Cinnamon combo pattern; modal dialogs can host popups).
        let selectedCredential = choices.length > 0 ? choices[0] : null;
        const combo = new St.Button({
            style_class: 'dialog-button',
            reactive: true,
            can_focus: true,
            x_expand: true,
        });
        const comboLabel = new St.Label({
            text: selectedCredential ? selectedCredential.label : 'No credentials found',
        });
        combo.add_child(comboLabel);
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
                    comboLabel.set_text(choice.label);
                });
                credentialMenu.addMenuItem(item);
            }
            if (!fresh.some(choice => selectedCredential &&
                    choice.credentialId === selectedCredential.credentialId))
                selectedCredential = fresh.length > 0 ? fresh[0] : null;
            comboLabel.set_text(selectedCredential
                ? selectedCredential.label
                : 'No credentials found');
        };
        populateCredentialChoices();
        const credentialRow = this._labeledRow('Credential', combo);
        credentialRow.visible = false;
        dialog.contentLayout.add_child(credentialRow);
        dialog.connect('destroy', () => {
            credentialMenu.close(false);
            credentialMenu.destroy();
        });

        const keyRow = this._labeledRow('API key', keyEntry);
        dialog.contentLayout.add_child(keyRow);

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let closeTimerId = 0;
        dialog.connect('destroy', () => {
            if (closeTimerId) {
                Mainloop.source_remove(closeTimerId);
                closeTimerId = 0;
            }
        });

        const selectedType = () => typeChooser.getActive();

        const submit = () => {
            const accountId = idEntry.get_text().trim();
            const label = labelEntry.get_text().trim();
            const fromDb = selectedType() === KIND_OPENCODE_DB;
            const key = fromDb ? '' : keyEntry.get_text();
            const error = accountFormError(accountId, key, fromDb);
            if (error) {
                status.set_text(error);
                return;
            }
            let args;
            let pendingText;
            if (fromDb) {
                // The CLI registers an OpenCode login; no key, no stdin.
                // Without --credential the account follows the active
                // OpenCode credential (the auto entry).
                if (!selectedCredential) {
                    status.set_text('No OpenCode credentials are available to add.');
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
                args = ['account', command, accountId, '--store', 'auto'];
                if (command === 'add' && label)
                    args.push('--label', label);
                pendingText = command === 'add'
                    ? `Adding account '${accountId}'…`
                    : `Replacing the key for '${accountId}'…`;
            }
            this._setDialogButtonEnabled(confirmInfo.button, false);
            status.set_text(pendingText);
            this._runAccountCommand(args, fromDb ? null : key, (ok, stdout, stderr) => {
                if (this._removed)
                    return;
                if (ok)
                    this._loadAccounts();
                if (closed)
                    return;
                // The key never stays in the entry beyond the command.
                keyEntry.set_text('');
                if (ok) {
                    const summary = [stdout.trim(), stderr.trim()].filter(Boolean).join(' ');
                    status.set_text(summary || `Account '${accountId}' updated.`);
                    closeTimerId = Mainloop.timeout_add(1200, () => {
                        closeTimerId = 0;
                        if (this._accountsDialog === dialog)
                            dialog.close();
                        return false;
                    });
                } else {
                    status.set_text(this._failureMessage(
                        fromDb ? 'could not add the OpenCode login account'
                            : 'could not update the account',
                        stderr, stdout));
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
                action: () => dialog.close(),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);

        const updateTypeState = () => {
            const fromDb = selectedType() === KIND_OPENCODE_DB;
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
                : 'API-key accounts from the OpenCode console. The key is sent to '
                    + 'the ocgo CLI and is never stored by the applet.';
            confirmInfo.button.label = fromDb ? 'Add account' : 'Add / replace key';
        };
        typeChooser.connect('radio-changed', () => updateTypeState());
        updateTypeState();
        dialog.setInitialKeyFocus(idEntry);
        dialog.open();
    }

    on_accounts_remove() {
        if (this._accountsDialog)
            return;
        const account = this._selectedComboAccount();
        if (!account)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog.connect('destroy', () => {
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
                status.set_text('Removing…');
                this._runAccountCommand(['account', 'remove', account.id], null, (ok, stdout, stderr) => {
                    if (this._removed)
                        return;
                    if (ok) {
                        this._loadAccounts();
                        if (!closed)
                            dialog.close();
                        return;
                    }
                    if (closed)
                        return;
                    status.set_text(this._failureMessage(
                        'could not remove the account', stderr, stdout));
                    this._setDialogButtonEnabled(confirmInfo.button, true);
                });
            },
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => dialog.close(),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);
        dialog.open();
    }

    // Settings-dialog entry point for "Make active in OpenCode…". Mirrors the
    // Remove button's handling: one accounts dialog at a time, silent no-op
    // when the selected account is not a pinned login, then the shared
    // confirmation flow (same as the popup submenu item).
    on_accounts_activate() {
        if (this._accountsDialog)
            return;
        const account = this._selectedComboAccount();
        if (!this._isPinnedLogin(account))
            return;
        this._confirmActivateInOpencode(account);
    }

    _confirmActivateInOpencode(account) {
        if (this._accountsDialog)
            return;
        const dialog = this._openAccountsDialog();
        let closed = false;
        dialog.connect('destroy', () => {
            closed = true;
        });

        dialog.contentLayout.add_child(new MessageContent({
            title: `Make '${account.label}' active in OpenCode?`,
            description: 'OpenCode will use this account for new sessions.',
        }));

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let closeTimerId = 0;
        dialog.connect('destroy', () => {
            if (closeTimerId) {
                Mainloop.source_remove(closeTimerId);
                closeTimerId = 0;
            }
        });

        const confirmInfo = {
            label: 'Make active',
            action: () => {
                this._setDialogButtonEnabled(confirmInfo.button, false);
                status.set_text('Switching the active OpenCode credential…');
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
                            const summary = [stdout.trim(), stderr.trim()]
                                .filter(Boolean).join(' ');
                            status.set_text(summary ||
                                `Account '${account.id}' is now active in OpenCode.`);
                            closeTimerId = Mainloop.timeout_add(1200, () => {
                                closeTimerId = 0;
                                if (this._accountsDialog === dialog)
                                    dialog.close();
                                return false;
                            });
                            return;
                        }
                        status.set_text(this._failureMessage(
                            'could not make the account active in OpenCode',
                            stderr, stdout));
                        this._setDialogButtonEnabled(confirmInfo.button, true);
                    });
            },
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => dialog.close(),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);
        dialog.open();
    }

    _failureMessage(fallback, stderr, stdout) {
        let detail = (stderr || stdout || '').trim();
        // The raw NO_CREDENTIAL stderr assumes a terminal user; point at the
        // dialog's own affordances instead.
        if (detail.includes('No OpenCode credential found')) {
            detail = 'No OpenCode login found on this machine — use '
                + '"Log in with OpenCode…" or switch the type to API key.';
        }
        return detail || fallback;
    }

    _runAccountCommand(args, stdinText, callback) {
        const binary = this._ocgoPath();
        if (!binary) {
            callback(false, '', 'ocgo not found; set the path in the applet settings');
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
            callback(false, '', `could not start ocgo: ${error.message ?? error}`);
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
