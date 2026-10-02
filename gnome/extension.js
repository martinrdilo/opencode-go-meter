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
const TICK_SECONDS = 30;
const DEFAULT_REFRESH_SECONDS = 300;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;

const WINDOWS = [
    {key: 'rolling', label: 'Rolling usage', short: '5h'},
    {key: 'weekly', label: 'Weekly usage', short: '7d'},
    {key: 'monthly', label: 'Monthly usage', short: '30d'},
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

function resolveExecutable(path) {
    if (!path)
        return null;
    if (!path.includes('/'))
        return GLib.find_program_in_path(path);
    return GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE) ? path : null;
}

export default class OpenCodeGoMeterExtension extends Extension {
    enable() {
        try {
            this._settings = this.getSettings();
            this._refreshInProgress = false;
            this._monitor = null;
            this._monitorId = 0;
            this._refreshTimerId = 0;
            this._tickTimerId = 0;
            this._panelBoxId = 0;
            this._panelPositionId = 0;

            this._indicator = new PanelMenu.Button(0.0, this.metadata.name, false);
            this._buildPanel();
            this._buildMenu();
            Main.panel.addToStatusArea(
                this.uuid, this._indicator, this._panelPosition(), this._panelBox());
            this._panelBoxId = this._settings.connect(
                'changed::panel-box', () => this._reposition());
            this._panelPositionId = this._settings.connect(
                'changed::panel-position', () => this._reposition());

            this._updateDisplay();
            this._startTimers();
            this._startMonitor();
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
        if (this._refreshTimerId) {
            GLib.source_remove(this._refreshTimerId);
            this._refreshTimerId = 0;
        }
        if (this._tickTimerId) {
            GLib.source_remove(this._tickTimerId);
            this._tickTimerId = 0;
        }
        if (this._monitor) {
            try {
                if (this._monitorId)
                    this._monitor.disconnect(this._monitorId);
                this._monitor.cancel();
            } catch (error) {
                logError('could not stop the cache monitor', error);
            }
            this._monitor = null;
            this._monitorId = 0;
        }
        if (this._indicator) {
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
        this._headerItem = null;
        this._warningItem = null;
        this._updatedItem = null;
        this._refreshItem = null;
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

    _panelBox() {
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
                this.uuid, this._indicator, this._panelPosition(), this._panelBox());
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
    }

    _renderMenu(cache, windows, now) {
        const renewal = cache ? formatRenewal(cache.renewal_ends_at) : null;
        this._headerItem.label.text = renewal
            ? `OpenCode Go — Renews ${renewal}`
            : 'OpenCode Go';

        const lastError = cache && typeof cache.last_error === 'string'
            ? cache.last_error.trim()
            : '';
        if (lastError) {
            const ago = formatAgo(cache.fetched_at, now);
            const suffix = ago ? ` · data from ${ago}` : '';
            this._warningItem.label.text =
                `Last refresh failed: ${truncate(lastError, MAX_WARNING_CHARS)}${suffix}`;
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

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._updatedItem.label.text = updated ? `Updated ${updated}` : 'Updated —';
    }

    // -- cache ---------------------------------------------------------------

    _cachePath() {
        return GLib.build_filenamev([GLib.get_user_cache_dir(), CACHE_DIR, CACHE_FILE]);
    }

    _readCache() {
        try {
            const file = Gio.File.new_for_path(this._cachePath());
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
        try {
            const file = Gio.File.new_for_path(this._cachePath());
            this._monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, null);
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
        }
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

    _ocgoPath() {
        try {
            const fromSetting = resolveExecutable(this._settings.get_string('ocgo-path').trim());
            if (fromSetting)
                return fromSetting;
        } catch (error) {
            logError('could not read ocgo-path', error);
        }
        const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
        if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
            return local;
        return GLib.find_program_in_path('ocgo');
    }

    _triggerRefresh() {
        if (this._refreshInProgress)
            return;
        try {
            const binary = this._ocgoPath();
            if (!binary) {
                logError('ocgo not found; set ocgo-path in the extension settings');
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
