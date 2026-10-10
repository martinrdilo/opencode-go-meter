// OpenCode Go Meter — Cinnamon panel applet (Cinnamon 6.4, legacy imports).
// Reads the ocgo cache written by the core CLI; it never touches credentials.

const Applet = imports.ui.applet;
const Dialog = imports.ui.dialog;
const ModalDialog = imports.ui.modalDialog;
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
const DEFAULT_REFRESH_SECONDS = 300;
const MIN_REFRESH_SECONDS = 30;
const TICK_SECONDS = 30;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;

const ACCOUNTS_SCHEMA = 2;
const DEFAULT_ACCOUNT_ID = 'default';
const KIND_OPENCODE_DB = 'opencode-db';
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
            active: false,
        });
    }
    const requested = typeof payload.active === 'string' ? payload.active : null;
    const active = requested !== null && seen.has(requested) ? requested : null;
    for (const account of accounts)
        account.active = account.id === active;
    return {accounts, active};
}

function accountFormError(accountId, key) {
    if (!accountId)
        return 'Enter an account id.';
    if (!ACCOUNT_ID_RE.test(accountId))
        return 'Invalid account id: use a-z, 0-9, dot, underscore, or dash (max 64).';
    if (!key)
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
        this._accountsLoaded = false;
        this._accountsLoading = false;
        this._accountsError = null;
        this._accountsErrorLogged = false;
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

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._refreshItem.label.set_text(`Updated ${updated || '—'} · Refresh`);
    }

    _renderAccountMenu() {
        if (!this._accountSubMenuItem)
            return;
        const accounts = this._accounts || [];
        const signature = `${this._accountsError || ''}\u0002` + accounts.map(account =>
            `${account.id}\u0000${account.label}\u0000${account.active ? 1 : 0}`).join('\u0001');
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

    _activeAccountLabel() {
        const account = (this._accounts || []).find(
            entry => entry.id === this._activeAccountId);
        return account ? account.label : this._activeAccountId;
    }

    _startAccountLoad(generation, onComplete) {
        const binary = this._ocgoPath();
        if (!binary) {
            this._finishAccountLoad(generation, onComplete, null, 'ocgo not found');
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
                if (exitCode !== 0)
                    errorMessage = `ocgo account list failed (exit ${exitCode})`;
                const parsed = errorMessage ? null : parseAccountList(stdout);
                if (!errorMessage && !parsed)
                    errorMessage = 'unexpected ocgo account list output';
                this._finishAccountLoad(generation, onComplete, parsed, errorMessage);
            }, {argv: [binary, 'account', 'list', '--json']});
        } catch (error) {
            this._accountsLoading = false;
            this._finishAccountLoad(
                generation, onComplete, null, 'could not start ocgo account list', error);
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
                this._accountsError = null;
                this._accountsErrorLogged = false;
                this._activeAccountId = parsed.active;
            } else {
                if (!this._accountsLoaded) {
                    this._accounts = [];
                    this._activeAccountId = null;
                }
                this._accountsLoaded = true;
                this._accountsError = errorMessage;
                if (!this._accountsErrorLogged) {
                    this._accountsErrorLogged = true;
                    logError(`${errorMessage}; keeping the current account list`, error);
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
            // always the account id.
            const counts = new Map();
            for (const account of this._accounts)
                counts.set(account.label, (counts.get(account.label) || 0) + 1);
            const used = new Set();
            for (const account of this._accounts) {
                let key = counts.get(account.label) === 1
                    ? account.label
                    : `${account.label} (${account.id})`;
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

    _entryRow(text, entry) {
        const row = new St.BoxLayout({vertical: true, x_expand: true});
        row.add_child(new St.Label({text: text}));
        entry.x_expand = true;
        row.add_child(entry);
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

        dialog.contentLayout.add_child(new Dialog.MessageDialogContent({
            title: 'Add / replace account key',
            description: 'API-key accounts from the OpenCode console. The key is sent to '
                + 'the ocgo CLI and is never stored by the applet.',
        }));

        const idEntry = new St.Entry({hint_text: 'e.g. work', x_expand: true});
        const labelEntry = new St.Entry({hint_text: 'optional', x_expand: true});
        const keyEntry = new St.Entry({hint_text: 'oc_sk_…', x_expand: true});
        keyEntry.clutter_text.set_password_char('\u25cf');
        dialog.contentLayout.add_child(this._entryRow('Account id', idEntry));
        dialog.contentLayout.add_child(this._entryRow('Label (optional)', labelEntry));
        dialog.contentLayout.add_child(this._entryRow('API key', keyEntry));

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let closeTimerId = 0;
        dialog.connect('destroy', () => {
            if (closeTimerId) {
                Mainloop.source_remove(closeTimerId);
                closeTimerId = 0;
            }
        });

        const submit = () => {
            const accountId = idEntry.get_text().trim();
            const label = labelEntry.get_text().trim();
            const key = keyEntry.get_text();
            const error = accountFormError(accountId, key);
            if (error) {
                status.set_text(error);
                return;
            }
            const command = accountCommandFor(accountId, this._accounts);
            const args = ['account', command, accountId, '--store', 'auto'];
            if (command === 'add' && label)
                args.push('--label', label);
            this._setDialogButtonEnabled(confirmInfo.button, false);
            status.set_text(command === 'add'
                ? `Adding account '${accountId}'…`
                : `Replacing the key for '${accountId}'…`);
            this._runAccountCommand(args, key, (ok, stdout, stderr) => {
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
                        'could not update the account', stderr, stdout));
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

        dialog.contentLayout.add_child(new Dialog.MessageDialogContent({
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

    _failureMessage(fallback, stderr, stdout) {
        return (stderr || stdout || '').trim() || fallback;
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
