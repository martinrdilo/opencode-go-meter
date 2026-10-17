// OpenCode Go Meter — Cinnamon panel applet (Cinnamon 5.4+, legacy imports).
// Reads the ocgo cache written by the core CLI; it never touches credentials.

const Applet = imports.ui.applet;
const ModalDialog = imports.ui.modalDialog;
const PopupMenu = imports.ui.popupMenu;
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
const DEFAULT_REFRESH_SECONDS = 300;
const MIN_REFRESH_SECONDS = 30;
const TICK_SECONDS = 30;
const AMBER_AT = 50;
const RED_AT = 85;
const MAX_WARNING_CHARS = 70;

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
// credential-command failure path and the cached last_error render sites:
// strip the tool token first, then map the known terminal-level messages to
// actionable copy. Unknown details pass through token-stripped.
function formatFailureDetail(text) {
    let detail = stripToolToken(typeof text === 'string' ? text.trim() : '');
    if (detail.includes('No OpenCode credential found')) {
        detail = 'No OpenCode login found on this machine — set a fallback '
            + 'API key in the applet settings.';
    }
    return detail;
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

class OpenCodeGoMeterApplet extends Applet.TextApplet {
    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);
        this._removed = false;
        this._refreshInProgress = false;
        this._refreshTimerId = 0;
        this._tickTimerId = 0;
        this._keyDialog = null;
        this._authError = null;

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);
        this.settings.bind('refresh-interval', 'refresh_interval', () => this._onRefreshIntervalChanged());
        this.settings.bind('opencode-data-dir', 'opencode_data_dir');

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menuManager.addMenu(this.menu);
        this._buildMenu();

        this._updateDisplay();
        this._startTimers();
        this._triggerRefresh();
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
            if (this._keyDialog) {
                this._keyDialog.destroy();
                this._keyDialog = null;
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
            this._renderLabel(windows);
            this._renderMenu(cache, windows);
            this._renderTooltip(cache);
        } catch (error) {
            logError('could not render the usage cache', error);
        }
    }

    _renderLabel(windows) {
        const parts = WINDOWS.map(window => {
            const percent = windowOf(windows, window.key).percent;
            return `${window.short} ${percentMarkup(percent)}`;
        });
        this._applet_label.clutter_text.set_markup(parts.join(' · '));
    }

    _renderTooltip(cache) {
        const now = new Date();
        const lines = ['OpenCode Go'];
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
        if (this._authError)
            lines.push(`Credentials: ${truncate(this._authError, MAX_WARNING_CHARS)}`);
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

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._refreshItem = new PopupMenu.PopupMenuItem('Updated — · Refresh');
        this._refreshItem.connect('activate', () => this._triggerRefresh());
        this.menu.addMenuItem(this._refreshItem);
    }

    _renderMenu(cache, windows) {
        const now = new Date();
        const renewal = cache ? formatRenewal(cache.renewal_ends_at) : null;
        const header = renewal ? `OpenCode Go — Renews ${renewal}` : 'OpenCode Go';
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

        const updated = cache ? formatAgo(cache.fetched_at, now) : null;
        this._refreshItem.label.set_text(`Updated ${updated || '—'} · Refresh`);
    }

    // -- credentials (settings actions) --------------------------------------

    // Applies the custom OpenCode data directory (or resets to auto-detect
    // when the field is empty). The helper owns the config file; the applet
    // only forwards the value and never reads credentials itself.
    on_set_data_dir() {
        const value = typeof this.opencode_data_dir === 'string'
            ? this.opencode_data_dir.trim()
            : '';
        if (value === '') {
            this._runAuthCommand(
                ['auth', 'clear-data-dir'], null,
                'could not reset the OpenCode data directory');
            return;
        }
        this._runAuthCommand(
            ['auth', 'set-data-dir', value], null,
            'could not set the OpenCode data directory');
    }

    on_clear_data_dir() {
        this._runAuthCommand(
            ['auth', 'clear-data-dir'], null,
            'could not reset the OpenCode data directory');
    }

    // Minimal single-field prompt for the fallback API key: the key is typed
    // into a masked entry and reaches the helper over stdin only.
    on_set_api_key() {
        if (this._keyDialog)
            return;
        const dialog = new ModalDialog.ModalDialog();
        this._keyDialog = dialog;
        // Uniform breathing room between the dialog's rows on both themes
        // (5.4's modal-dialog-content-box sets no spacing).
        setBoxSpacing(dialog.contentLayout, 6);
        dialog._ocgoClosed = false;
        dialog.connect('destroy', () => {
            dialog._ocgoClosed = true;
            if (this._keyDialog === dialog)
                this._keyDialog = null;
        });

        dialog.contentLayout.add_child(new MessageContent({
            title: 'Set fallback API key',
            description: 'Used only while no local OpenCode login is available. '
                + 'The key is verified with OpenCode and stored by the ocgo '
                + 'helper in a private file — the applet settings never hold it.',
        }));

        const keyEntry = new St.Entry({hint_text: 'oc_sk_…', x_expand: true});
        keyEntry.clutter_text.set_password_char('\u25cf');
        dialog.contentLayout.add_child(keyEntry);

        const status = this._statusLabel();
        dialog.contentLayout.add_child(status);

        let submitting = false;
        const confirmInfo = {
            label: 'Store key',
            action: () => {
                if (submitting)
                    return;
                const key = keyEntry.get_text().trim();
                if (!key) {
                    this._setStatus(status, 'Enter an API key.', true);
                    return;
                }
                submitting = true;
                this._setDialogButtonEnabled(confirmInfo.button, false);
                this._setStatus(status, 'Verifying the key…', false);
                this._runAuthCommand(
                    ['auth', 'set-key', '--stdin'], key,
                    'could not store the API key',
                    (ok, detail) => {
                        submitting = false;
                        if (this._removed || dialog._ocgoClosed)
                            return;
                        if (ok) {
                            // The key never stays in the entry beyond the command.
                            keyEntry.set_text('');
                            this._closeDialog(dialog);
                            return;
                        }
                        this._setStatus(status, detail || 'Could not store the key.', true);
                        this._setDialogButtonEnabled(confirmInfo.button, true);
                    });
            },
            default: true,
        };
        dialog.setButtons([
            {
                label: 'Cancel',
                action: () => this._closeDialog(dialog),
                key: Clutter.KEY_Escape,
            },
            confirmInfo,
        ]);
        dialog.setInitialKeyFocus(keyEntry);
        if (dialog.open() === false) {
            // pushModal failed (another modal owns the screen): the dialog never
            // opened, so destroy directly; the 'destroy' handler clears the
            // reference.
            dialog.destroy();
        }
    }

    on_clear_api_key() {
        this._runAuthCommand(
            ['auth', 'clear-key'], null,
            'could not remove the stored API key');
    }

    // -- dialog helpers ------------------------------------------------------

    // Single close path for the key prompt. The cleanups are not needed here
    // (no timers or menus), but 5.4's close() nuance is: it only fades and
    // hides the dialog — never destroys it nor emits 'destroy' — so without
    // the backstop the hidden actor would leak on every open/close cycle,
    // and the 6.4 auto-destroy ('_destroyOnClose' default true) must not be
    // repeated.
    _closeDialog(dialog) {
        if (!dialog)
            return;
        if (this._keyDialog === dialog)
            this._keyDialog = null;
        try {
            dialog.close();
        } catch (error) {
            logError('could not close the key dialog', error);
        }
        if (!dialog._ocgoClosed && dialog._destroyOnClose !== true) {
            try {
                dialog.destroy();
            } catch (error) {
                logError('could not destroy the key dialog', error);
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

    _statusLabel() {
        const label = new St.Label({text: '', style_class: 'run-dialog-description'});
        label.clutter_text.line_wrap = true;
        return label;
    }

    // Status line of the key dialog: neutral/pending text plain, failure text
    // in the theme's error color (styled on 5.4 and 6.4).
    _setStatus(label, text, failed) {
        label.set_text(text);
        if (failed)
            label.add_style_class_name('error');
        else
            label.remove_style_class_name('error');
    }

    _failureMessage(fallback, stderr, stdout) {
        return formatFailureDetail(stderr || stdout) || fallback;
    }

    // Runs one `ocgo auth` command through the helper and re-reads the state
    // afterwards. The optional stdin text (the API key) travels over the
    // stdin pipe only — never argv or the journal. Failures are sanitized
    // through formatFailureDetail and surfaced in the tooltip; a dialog
    // caller also gets the detail through onDone.
    _runAuthCommand(args, stdinText, actionLabel, onDone = null) {
        const binary = this._ocgoPath();
        if (!binary) {
            this._failAuthCommand(
                actionLabel,
                "The meter's helper is not installed — re-run the installer, "
                    + 'then restart Cinnamon.',
                onDone);
            return;
        }
        try {
            // argv array only; when stdinText is set it travels through the
            // stdin pipe (opts.input), never through argv or the journal.
            Util.spawnCommandLineAsyncIO(null, (stdout, stderr, exitCode) => {
                if (this._removed)
                    return;
                if (exitCode === 0) {
                    this._authError = null;
                    if (onDone)
                        onDone(true, '');
                    this._updateDisplay();
                    this._triggerRefresh();
                    return;
                }
                this._failAuthCommand(
                    actionLabel,
                    this._failureMessage(actionLabel, stderr, stdout),
                    onDone);
            }, {
                argv: [binary, ...args],
                input: stdinText === null ? null : `${stdinText}\n`,
            });
        } catch (error) {
            this._failAuthCommand(
                actionLabel, 'could not start the meter helper', onDone, error);
        }
    }

    _failAuthCommand(actionLabel, detail, onDone, error = null) {
        this._authError = detail;
        logError(`${actionLabel}: ${detail}`, error);
        if (onDone)
            onDone(false, detail);
        this._updateDisplay();
    }

    // -- cache ---------------------------------------------------------------

    _cachePath() {
        return GLib.build_filenamev([GLib.get_user_cache_dir(), CACHE_DIR, CACHE_FILE]);
    }

    _readCache() {
        const path = this._cachePath();
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
