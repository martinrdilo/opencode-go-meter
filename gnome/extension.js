// OpenCode Go Meter — GNOME Shell top-bar indicator.
// Reads the ocgo cache written by the core CLI; it never touches credentials.

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

const CACHE_DIR = 'ocgo';
const CACHE_FILE = 'status.json';
const ACCOUNTS_DIR = 'accounts';
const TICK_SECONDS = 30;
const DEFAULT_REFRESH_SECONDS = 300;
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

const CREDITS_ROWS = [
    {key: 'credits', label: 'Credits'},
    {key: 'extra_usage', label: 'Extra usage'},
    {key: 'auto_recharge', label: 'Auto-recharge'},
];

const PANEL_BOXES = ['left', 'center', 'right'];
const DEFAULT_PANEL_BOX = 'right';
const DEFAULT_PANEL_POSITION = 0;
const MIN_PANEL_POSITION = -1;
const MAX_PANEL_POSITION = 30;

function logError(message, error) {
    console.error(`[opencode-go-meter] ${message}${error ? `: ${error}` : ''}`);
}

function parseDate(value) {
    if (typeof value !== 'string' || value.trim() === '')
        return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function colorClass(percent) {
    if (percent >= RED_AT)
        return 'ocgo-red';
    if (percent >= AMBER_AT)
        return 'ocgo-amber';
    return 'ocgo-green';
}

function percentText(percent) {
    return Number.isFinite(percent) ? `${Math.round(percent)}%` : '—';
}

function percentStyle(percent) {
    return Number.isFinite(percent) ? `ocgo-pct ${colorClass(percent)}` : 'ocgo-pct';
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

// One plain-language rewrite for a cached refresh failure: the Cinnamon
// applet's helper mirrored locally (no cross-file import) — strip the tool
// token and any ocgo-bearing config path first, then map the known
// terminal-level messages to actionable copy. Unknown details pass through
// sanitized.
function formatFailureDetail(text) {
    let detail = typeof text === 'string' ? text.trim() : '';
    if (detail.includes('ocgo')) {
        detail = detail.replace(/ocgo:\s*/g, ' ');
        detail = detail.replace(/\(ocgo_[^)]*\)/g, '');
        // `... at <ocgo-path>` reads fine without the fragment; any other
        // ocgo-bearing path becomes a neutral reference.
        detail = detail.replace(/\s+at\s+(?=[^\s:'"]*ocgo)(?=[^\s:'"]*\/)[^\s:'"]*/g, '');
        detail = detail.replace(/(?=[^\s:'"]*ocgo)(?=[^\s:'"]*\/)[^\s:'"]*/g, 'its config file');
        detail = detail.replace(/\s{2,}/g, ' ').trim();
    }
    if (detail.includes('No OpenCode credential found')) {
        detail = 'No OpenCode login found on this machine — sign in again '
            + 'in OpenCode.';
    } else if (detail.includes('no OpenCode credential matches')) {
        detail = 'That credential is no longer available — reload the list '
            + 'and pick another one.';
    } else if (detail.includes('no secret found for account')) {
        detail = "The account's stored key is missing — add the key again "
            + 'in settings.';
    }
    return detail;
}

function windowsOf(cache) {
    const windows = cache && typeof cache === 'object' ? cache.windows : null;
    if (!windows || typeof windows !== 'object' || Array.isArray(windows))
        return {};
    return windows;
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
            hint: typeof entry.hint === 'string' ? entry.hint : null,
        });
    }
    const requested = typeof payload.active === 'string' ? payload.active : null;
    const active = requested !== null && seen.has(requested) ? requested : null;
    for (const account of accounts)
        account.active = account.id === active;
    return {accounts, active};
}

function windowOf(windows, key) {
    const window = windows[key];
    return window && typeof window === 'object' && !Array.isArray(window) ? window : {};
}

function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function creditsOf(cache) {
    return isObject(cache) && isObject(cache.credits) ? cache.credits : null;
}

function extraUsageOf(cache) {
    const value = isObject(cache) ? cache.extra_usage : null;
    return typeof value === 'boolean' ? value : null;
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
        return {text: 'Running low', styleClass: 'ocgo-amber'};
    if (state === 'empty')
        return {text: 'No credits left', styleClass: 'ocgo-red'};
    return {text: '', styleClass: ''};
}

function autoRechargeValue(auto) {
    if (auto.failed)
        return {text: 'Failed', styleClass: 'ocgo-red'};
    if (auto.pending)
        return {text: 'Recharging…', styleClass: ''};
    if (auto.enabled) {
        const amount = dollarsText(auto.amount_usd);
        const threshold = dollarsText(auto.threshold_usd);
        if (amount === null || threshold === null)
            return {text: 'On', styleClass: ''};
        return {text: `Adds ${amount} below ${threshold}`, styleClass: ''};
    }
    return {text: 'Off', styleClass: ''};
}

function creditValueStyle(styleClass) {
    return styleClass ? `ocgo-credit-value ${styleClass}` : 'ocgo-credit-value';
}

export default class OpenCodeGoMeterExtension extends Extension {
    enable() {
        try {
            this._settings = this.getSettings();
            this._refreshInProgress = false;
            this._monitor = null;
            this._monitorId = 0;
            this._monitorAccountId = null;
            this._refreshTimerId = 0;
            this._tickTimerId = 0;
            this._panelBoxId = 0;
            this._panelPositionId = 0;
            this._showCreditsId = 0;
            this._menuOpenId = 0;
            this._accounts = [];
            this._activeAccountId = null;
            this._accountsLoaded = false;
            this._accountsLoading = false;
            this._accountsErrorLogged = false;
            this._accountsGeneration = 0;
            this._accountsPending = null;
            this._accountMenuSignature = null;
            this._accountSubMenuItem = null;

            this._indicator = new PanelMenu.Button(0.0, this.metadata.name, false);
            this._buildPanel();
            this._buildMenu();
            Main.panel.addToStatusArea(
                this.uuid, this._indicator, this._panelPosition(), this._panelBoxSetting());
            this._panelBoxId = this._settings.connect(
                'changed::panel-box', () => this._reposition());
            this._panelPositionId = this._settings.connect(
                'changed::panel-position', () => this._reposition());
            this._showCreditsId = this._settings.connect(
                'changed::show-credits', () => this._updateDisplay());

            this._updateDisplay();
            this._startTimers();
            this._startMonitor();
            this._loadAccounts();
            this._triggerRefresh();
        } catch (error) {
            logError('could not enable the extension', error);
        }
    }

    disable() {
        if (this._panelBoxId) {
            this._settings?.disconnect(this._panelBoxId);
            this._panelBoxId = 0;
        }
        if (this._panelPositionId) {
            this._settings?.disconnect(this._panelPositionId);
            this._panelPositionId = 0;
        }
        if (this._showCreditsId) {
            this._settings?.disconnect(this._showCreditsId);
            this._showCreditsId = 0;
        }
        if (this._refreshTimerId) {
            GLib.source_remove(this._refreshTimerId);
            this._refreshTimerId = 0;
        }
        if (this._tickTimerId) {
            GLib.source_remove(this._tickTimerId);
            this._tickTimerId = 0;
        }
        this._stopMonitor();
        if (this._indicator) {
            try {
                if (this._menuOpenId)
                    this._indicator.menu.disconnect(this._menuOpenId);
            } catch (error) {
                logError('could not disconnect the menu', error);
            }
            this._menuOpenId = 0;
            try {
                this._indicator.destroy();
            } catch (error) {
                logError('could not destroy the indicator', error);
            }
            this._indicator = null;
        }
        this._settings = null;
        this._panelPercents = null;
        this._panelParts = null;
        this._menuRows = null;
        this._creditsItems = null;
        this._creditsSeparatorItem = null;
        this._headerItem = null;
        this._warningItem = null;
        this._updatedItem = null;
        this._refreshItem = null;
        this._accountSubMenuItem = null;
        this._accountMenuSignature = null;
        this._accounts = [];
        this._activeAccountId = null;
        this._accountsLoaded = false;
        this._accountsLoading = false;
        this._accountsErrorLogged = false;
        this._accountsGeneration = 0;
        this._accountsPending = null;
    }

    // -- panel ---------------------------------------------------------------

    _buildPanel() {
        this._panelBox = new St.BoxLayout({
            style_class: 'ocgo-panel-box',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._indicator.add_child(this._panelBox);

        this._panelPercents = new Map();
        this._panelParts = [];
        WINDOWS.forEach((window, index) => {
            if (index > 0) {
                const separator = new St.Label({
                    text: '·',
                    style_class: 'ocgo-separator',
                    y_align: Clutter.ActorAlign.CENTER,
                });
                this._panelBox.add_child(separator);
                this._panelParts.push(separator);
            }
            const name = new St.Label({
                text: window.short,
                style_class: 'ocgo-window-name',
                y_align: Clutter.ActorAlign.CENTER,
            });
            const percent = new St.Label({
                text: '—',
                style_class: 'ocgo-pct',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._panelBox.add_child(name);
            this._panelBox.add_child(percent);
            this._panelParts.push(name, percent);
            this._panelPercents.set(window.key, percent);
        });

        this._noDataLabel = new St.Label({
            text: 'Go —',
            style_class: 'ocgo-window-name',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._panelBox.add_child(this._noDataLabel);
    }

    _renderPanel(hasCache, windows) {
        for (const part of this._panelParts)
            part.visible = hasCache;
        this._noDataLabel.visible = !hasCache;
        if (!hasCache)
            return;

        for (const window of WINDOWS) {
            const percent = windowOf(windows, window.key).percent;
            const label = this._panelPercents.get(window.key);
            label.text = percentText(percent);
            label.style_class = percentStyle(percent);
        }
    }

    // -- panel position ------------------------------------------------------

    _panelBoxSetting() {
        try {
            const value = this._settings.get_string('panel-box').trim().toLowerCase();
            if (PANEL_BOXES.includes(value))
                return value;
            logError(`unknown panel-box '${value}'; using '${DEFAULT_PANEL_BOX}'`);
        } catch (error) {
            logError('could not read panel-box', error);
        }
        return DEFAULT_PANEL_BOX;
    }

    _panelPosition() {
        try {
            const value = this._settings.get_int('panel-position');
            if (Number.isInteger(value) &&
                value >= MIN_PANEL_POSITION && value <= MAX_PANEL_POSITION)
                return value;
            logError(`panel-position ${value} is out of range; using ${DEFAULT_PANEL_POSITION}`);
        } catch (error) {
            logError('could not read panel-position', error);
        }
        return DEFAULT_PANEL_POSITION;
    }

    _reposition() {
        try {
            if (!this._indicator)
                return;
            // The shell throws on an existing statusArea entry and re-parents
            // the indicator itself, so drop the registration first.
            delete Main.panel.statusArea[this.uuid];
            Main.panel.addToStatusArea(
                this.uuid, this._indicator, this._panelPosition(), this._panelBoxSetting());
        } catch (error) {
            logError('could not move the indicator', error);
        }
    }

    // -- popup menu ----------------------------------------------------------

    _buildMenu() {
        const menu = this._indicator.menu;

        this._headerItem = new PopupMenu.PopupMenuItem('OpenCode Go', {
            reactive: false,
            can_focus: false,
        });
        this._headerItem.add_style_class_name('ocgo-header');
        menu.addMenuItem(this._headerItem);

        this._warningItem = new PopupMenu.PopupMenuItem('', {
            reactive: false,
            can_focus: false,
        });
        this._warningItem.add_style_class_name('ocgo-warning');
        this._warningItem.visible = false;
        menu.addMenuItem(this._warningItem);

        this._menuRows = new Map();
        for (const window of WINDOWS) {
            const item = new PopupMenu.PopupBaseMenuItem({
                reactive: false,
                can_focus: false,
            });
            const label = new St.Label({
                text: window.label,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const percent = new St.Label({
                text: '—',
                style_class: 'ocgo-pct',
                y_align: Clutter.ActorAlign.CENTER,
            });
            const countdown = new St.Label({
                text: 'Resets in —',
                style_class: 'ocgo-countdown',
                y_align: Clutter.ActorAlign.CENTER,
            });
            item.add_child(label);
            item.add_child(percent);
            item.add_child(countdown);
            menu.addMenuItem(item);
            this._menuRows.set(window.key, {percent, countdown});
        }

        this._creditsSeparatorItem = new PopupMenu.PopupSeparatorMenuItem();
        menu.addMenuItem(this._creditsSeparatorItem);

        this._creditsItems = new Map();
        for (const row of CREDITS_ROWS) {
            const item = new PopupMenu.PopupBaseMenuItem({
                reactive: false,
                can_focus: false,
            });
            const label = new St.Label({
                text: row.label,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const value = new St.Label({
                text: '—',
                style_class: 'ocgo-credit-value',
                y_align: Clutter.ActorAlign.CENTER,
            });
            item.add_child(label);
            item.add_child(value);
            menu.addMenuItem(item);
            this._creditsItems.set(row.key, {item, value});
        }

        this._accountSubMenuItem = new PopupMenu.PopupSubMenuMenuItem('Account');
        menu.addMenuItem(this._accountSubMenuItem);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._updatedItem = new PopupMenu.PopupMenuItem('Updated —', {
            reactive: false,
            can_focus: false,
        });
        this._updatedItem.add_style_class_name('ocgo-footer');
        menu.addMenuItem(this._updatedItem);

        this._refreshItem = new PopupMenu.PopupMenuItem('Refresh');
        this._refreshItem.connect('activate', () => this._triggerRefresh());
        menu.addMenuItem(this._refreshItem);

        this._menuOpenId = menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen)
                this._loadAccounts();
        });
    }

    _renderMenu(cache, windows, now) {
        const renewal = cache ? formatRenewal(cache.renewal_ends_at) : null;
        if (!this._activeAccountId) {
            this._headerItem.label.text = 'OpenCode Go';
        } else if (this._activeAccountId === DEFAULT_ACCOUNT_ID) {
            this._headerItem.label.text = renewal
                ? `OpenCode Go — Renews ${renewal}`
                : 'OpenCode Go';
        } else {
            const label = this._activeAccountLabel();
            this._headerItem.label.text = renewal
                ? `OpenCode Go · ${label} — Renews ${renewal}`
                : `OpenCode Go · ${label}`;
        }

        const lastError = cache && typeof cache.last_error === 'string'
            ? cache.last_error.trim()
            : '';
        if (lastError) {
            const ago = formatAgo(cache.fetched_at, now);
            const suffix = ago ? ` · data from ${ago}` : '';
            const detail = formatFailureDetail(lastError);
            this._warningItem.label.text =
                `Last refresh failed: ${truncate(detail, MAX_WARNING_CHARS)}${suffix}`;
            this._warningItem.visible = true;
        } else {
            this._warningItem.visible = false;
        }

        for (const window of WINDOWS) {
            const row = this._menuRows.get(window.key);
            const data = windowOf(windows, window.key);
            const percent = data.percent;
            row.percent.text = percentText(percent);
            row.percent.style_class = percentStyle(percent);
            // The month meter has no resetsAt; the console counts down to renewal.
            const target = window.key === 'monthly' ? cache?.renewal_ends_at : data.resets_at;
            row.countdown.text = `Resets in ${formatCountdown(target, now)}`;
        }

        this._renderCredits(cache);

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._updatedItem.label.text = updated ? `Updated ${updated}` : 'Updated —';
    }

    _showCreditsSetting() {
        try {
            return this._settings.get_boolean('show-credits');
        } catch (error) {
            logError('could not read show-credits; hiding the credits section', error);
            return false;
        }
    }

    _renderCredits(cache) {
        const credits = creditsOf(cache);
        const extraUsage = extraUsageOf(cache);
        const autoRecharge = credits && isObject(credits.auto_recharge)
            ? credits.auto_recharge
            : null;

        const visible = this._showCreditsSetting() &&
            (credits !== null || extraUsage !== null);
        this._creditsSeparatorItem.visible = visible;

        const creditsRow = this._creditsItems.get('credits');
        creditsRow.item.visible = visible && credits !== null;
        if (credits) {
            let text = 'Unavailable';
            let styleClass = '';
            if (typeof credits.error !== 'string') {
                text = creditsAmountText(credits.available_usd);
                const suffix = creditsSuffix(credits.state);
                if (suffix.text)
                    text = `${text} · ${suffix.text}`;
                styleClass = suffix.styleClass;
            }
            creditsRow.value.text = text;
            creditsRow.value.style_class = creditValueStyle(styleClass);
        }

        const extraRow = this._creditsItems.get('extra_usage');
        extraRow.item.visible = visible && extraUsage !== null;
        if (extraUsage !== null) {
            extraRow.value.text = extraUsage ? 'On' : 'Off';
            extraRow.value.style_class = creditValueStyle('');
        }

        const autoRow = this._creditsItems.get('auto_recharge');
        autoRow.item.visible = visible && autoRecharge !== null;
        if (autoRecharge) {
            const auto = autoRechargeValue(autoRecharge);
            autoRow.value.text = auto.text;
            autoRow.value.style_class = creditValueStyle(auto.styleClass);
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
            return null; // no cache yet or unreadable JSON: show the empty state
        }
    }

    _updateDisplay() {
        try {
            const now = new Date();
            const cache = this._readCache();
            const windows = windowsOf(cache);
            this._renderPanel(cache !== null, windows);
            this._renderMenu(cache, windows, now);
        } catch (error) {
            logError('could not render the usage cache', error);
        }
    }

    _startMonitor() {
        const path = this._cachePath();
        if (!path) {
            this._monitor = null;
            this._monitorId = 0;
            this._monitorAccountId = this._activeAccountId;
            return;
        }
        try {
            const file = Gio.File.new_for_path(path);
            this._monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitorAccountId = this._activeAccountId;
            this._monitorId = this._monitor.connect('changed', () => {
                try {
                    this._updateDisplay();
                } catch (error) {
                    logError('cache monitor update failed', error);
                }
            });
        } catch (error) {
            logError('cache monitor unavailable; using the timer only', error);
            this._monitor = null;
            this._monitorId = 0;
            this._monitorAccountId = null;
        }
    }

    _stopMonitor() {
        if (!this._monitor)
            return;
        try {
            if (this._monitorId)
                this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
        } catch (error) {
            logError('could not stop the cache monitor', error);
        }
        this._monitor = null;
        this._monitorId = 0;
        this._monitorAccountId = null;
    }

    _retargetMonitor() {
        if (this._monitor && this._monitorAccountId === this._activeAccountId)
            return;
        this._stopMonitor();
        this._startMonitor();
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
            const subprocess = Gio.Subprocess.new(
                [binary, 'account', 'list', '--json'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            subprocess.communicate_utf8_async(null, null, (process, result) => {
                this._accountsLoading = false;
                if (!this._indicator) {
                    this._accountsPending = null;
                    return;
                }
                let stdout = '';
                let errorMessage = null;
                let error = null;
                try {
                    const [, out] = process.communicate_utf8_finish(result);
                    stdout = out || '';
                } catch (caught) {
                    errorMessage = 'could not list accounts; keeping the current account list';
                    error = caught;
                }
                if (!errorMessage && !process.get_successful())
                    errorMessage = 'ocgo account list failed; keeping the current account list';
                const parsed = errorMessage ? null : parseAccountList(stdout);
                if (!errorMessage && !parsed)
                    errorMessage = 'unexpected account list output; keeping the current account list';
                this._finishAccountLoad(generation, onComplete, parsed, errorMessage, error);
            });
        } catch (error) {
            this._accountsLoading = false;
            this._finishAccountLoad(
                generation, onComplete, null,
                'could not start the account list; keeping the current account list', error);
        }
    }

    _finishAccountLoad(generation, onComplete, parsed, errorMessage, error = null) {
        if (!this._indicator) {
            this._accountsPending = null;
            return;
        }
        if (generation === this._accountsGeneration) {
            // Newest request: apply the result (or the fallback) and run its
            // callback on both paths, so a queued action is never dropped.
            if (parsed) {
                this._accounts = parsed.accounts;
                this._activeAccountId = parsed.active;
                this._accountsLoaded = true;
                this._accountsErrorLogged = false;
            } else {
                if (!this._accountsLoaded) {
                    this._accounts = [];
                    this._activeAccountId = null;
                }
                this._accountsLoaded = true;
                if (!this._accountsErrorLogged) {
                    this._accountsErrorLogged = true;
                    logError(errorMessage, error);
                }
            }
            this._renderAccountMenu();
            this._updateDisplay();
            this._retargetMonitor();
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

    _renderAccountMenu() {
        if (!this._accountSubMenuItem)
            return;
        const accounts = this._accounts || [];
        const signature = `${this._activeAccountId}|${accounts.map(
            account => `${account.id}\u0000${account.label}`).join('\u0001')}`;
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
                can_focus: false,
            }));
        } else {
            for (const account of accounts) {
                const item = new PopupMenu.PopupMenuItem(account.label);
                item.setOrnament(account.id === this._activeAccountId
                    ? PopupMenu.Ornament.DOT
                    : PopupMenu.Ornament.NONE);
                item.connect('activate', () => this._switchAccount(account.id));
                submenu.addMenuItem(item);
            }
        }
        submenu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const manageItem = new PopupMenu.PopupMenuItem('Manage accounts…');
        manageItem.connect('activate', () => this.openPreferences());
        submenu.addMenuItem(manageItem);
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
            const subprocess = Gio.Subprocess.new(
                [binary, 'account', 'use', accountId],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
            subprocess.wait_async(null, (process, result) => {
                if (!this._indicator)
                    return;
                try {
                    process.wait_finish(result);
                } catch (error) {
                    logError(`could not switch to account '${accountId}'`, error);
                    return;
                }
                if (!process.get_successful()) {
                    logError(`could not switch to account '${accountId}'`);
                    return;
                }
                // The CLI active account is already switched: reflect it now,
                // retarget the monitor, refresh, then reconcile the UI with a
                // fresh (newest-wins) account list.
                this._activeAccountId = accountId;
                this._retargetMonitor();
                this._triggerRefresh();
                this._loadAccounts();
            });
        } catch (error) {
            logError(`could not start the account switch to '${accountId}'`, error);
        }
    }

    _activeAccountLabel() {
        const account = (this._accounts || []).find(
            entry => entry.id === this._activeAccountId);
        return account ? account.label : this._activeAccountId;
    }

    // -- refresh -------------------------------------------------------------

    _refreshSeconds() {
        try {
            const value = this._settings.get_int('refresh-interval');
            return value >= 60 ? value : DEFAULT_REFRESH_SECONDS;
        } catch (error) {
            logError('could not read refresh-interval; using the default', error);
            return DEFAULT_REFRESH_SECONDS;
        }
    }

    _startTimers() {
        const interval = this._refreshSeconds();
        this._refreshTimerId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, interval, () => {
                try {
                    this._triggerRefresh();
                } catch (error) {
                    logError('scheduled refresh failed', error);
                }
                return GLib.SOURCE_CONTINUE;
            });
        this._tickTimerId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, TICK_SECONDS, () => {
                try {
                    this._updateDisplay();
                } catch (error) {
                    logError('countdown tick failed', error);
                }
                return GLib.SOURCE_CONTINUE;
            });
    }

    // The helper is looked up at its standard install location and then on
    // PATH, mirroring the Cinnamon applet. There is no user-facing override.
    _ocgoPath() {
        const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
        if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
            return local;
        return GLib.find_program_in_path('ocgo');
    }

    _triggerRefresh() {
        if (this._refreshInProgress)
            return;
        if (this._accountsLoaded && !this._activeAccountId)
            return; // known-empty list: there is no account to refresh
        try {
            const binary = this._ocgoPath();
            if (!binary) {
                logError('ocgo not found; skipping the refresh');
                return;
            }
            this._refreshInProgress = true;
            const subprocess = Gio.Subprocess.new(
                [binary, 'refresh'],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
            subprocess.wait_async(null, (process, result) => {
                this._refreshInProgress = false;
                try {
                    process.wait_finish(result);
                } catch (error) {
                    logError('refresh process failed', error);
                }
                this._updateDisplay();
            });
        } catch (error) {
            this._refreshInProgress = false;
            logError('could not start the refresh', error);
        }
    }
}
