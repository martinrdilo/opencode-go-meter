// Preferences for OpenCode Go Meter: refresh interval, panel, and credentials.

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

const AUTH_SCHEMA = 1;

// Deliberate copy: keep in sync with cinnamon/applet.js and gnome/extension.js.
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

function resolveOcgoPath() {
    const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
    if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
        return local;
    return GLib.find_program_in_path('ocgo');
}

function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// Parses `ocgo auth show --json` (schema 1). The CLI prints the document with
// a null credential and exits 1 when nothing resolves, so callers show the
// empty state from a successful parse instead of treating it as an error.
function parseAuthShowJson(text) {
    if (typeof text !== 'string' || text.trim() === '')
        return null;
    let payload = null;
    try {
        payload = JSON.parse(text);
    } catch (error) {
        return null;
    }
    if (!isObject(payload) || payload.schema !== AUTH_SCHEMA)
        return null;
    return {
        credential: isObject(payload.credential) ? payload.credential : null,
        store: isObject(payload.store) ? payload.store : null,
    };
}

const NO_LOGIN_TEXT = 'No OpenCode login found — configure a fallback API key below.';

// One-line summary of the resolved credential; the CLI strings render
// verbatim. A null credential is the explicit no-login state.
function credentialSummary(parsed) {
    const credential = parsed.credential;
    if (!credential)
        return NO_LOGIN_TEXT;
    const source = typeof credential.source === 'string' && credential.source.trim() !== ''
        ? credential.source.trim()
        : '—';
    const hint = typeof credential.token_hint === 'string' && credential.token_hint.trim() !== ''
        ? credential.token_hint.trim()
        : null;
    return hint ? `Source: ${source} · key ${hint}` : `Source: ${source}`;
}

export default class OpenCodeGoMeterPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        this._authStatusLoading = false;
        this._credentialActionInProgress = false;

        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: 'OpenCode Go Meter',
            description: 'How often the extension refreshes usage data.',
        });

        const intervalRow = new Adw.SpinRow({
            title: 'Refresh interval (seconds)',
            adjustment: new Gtk.Adjustment({
                lower: 60,
                upper: 86400,
                step_increment: 30,
                page_increment: 300,
            }),
        });
        settings.bind('refresh-interval', intervalRow, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(intervalRow);

        const panelGroup = new Adw.PreferencesGroup({
            title: 'Panel',
            description: 'Where the indicator sits in the top bar.',
        });

        const zoneRow = new Adw.ComboRow({
            title: 'Zone',
            model: Gtk.StringList.new(['Left', 'Center', 'Right']),
        });
        const zones = ['left', 'center', 'right'];
        const currentZone = zones.indexOf(settings.get_string('panel-box'));
        zoneRow.selected = currentZone >= 0 ? currentZone : zones.indexOf('right');
        zoneRow.connect('notify::selected', () => {
            settings.set_string('panel-box', zones[zoneRow.selected] ?? 'right');
        });
        panelGroup.add(zoneRow);

        const positionRow = new Adw.SpinRow({
            title: 'Order in the zone (−1 = last)',
            adjustment: new Gtk.Adjustment({
                lower: -1,
                upper: 30,
                step_increment: 1,
                page_increment: 5,
            }),
        });
        settings.bind('panel-position', positionRow, 'value', Gio.SettingsBindFlags.DEFAULT);
        panelGroup.add(positionRow);

        page.add(group);
        page.add(panelGroup);
        page.add(this._buildCredentialsGroup());
        window.add(page);

        this._refreshAuthStatus();
    }

    // -- credentials UI ------------------------------------------------------

    _buildCredentialsGroup() {
        const group = new Adw.PreferencesGroup({
            title: 'Credentials',
            description: 'The OpenCode login the meter reads, or a fallback API key.',
        });

        this._authStatusRow = new Adw.ActionRow({title: 'Credential status'});
        this._refreshStatusButton = new Gtk.Button({
            label: 'Refresh status',
            valign: Gtk.Align.CENTER,
        });
        this._refreshStatusButton.add_css_class('flat');
        this._refreshStatusButton.connect('clicked', () => this._refreshAuthStatus());
        this._authStatusRow.add_suffix(this._refreshStatusButton);
        group.add(this._authStatusRow);

        this._dataDirRow = new Adw.EntryRow({title: 'OpenCode data directory'});
        this._dataDirApplyButton = this._suffixButton('Apply', () => this._applyDataDir());
        this._dataDirRow.add_suffix(this._dataDirApplyButton);
        this._dataDirResetButton = this._suffixButton('Reset', () => this._resetDataDir());
        this._dataDirRow.add_suffix(this._dataDirResetButton);
        group.add(this._dataDirRow);

        this._keyRow = new Adw.PasswordEntryRow({title: 'Fallback API key'});
        this._keySaveButton = this._suffixButton('Save', () => this._saveApiKey());
        this._keyRow.add_suffix(this._keySaveButton);
        this._keyClearButton = this._suffixButton('Clear', () => this._clearApiKey());
        this._keyRow.add_suffix(this._keyClearButton);
        group.add(this._keyRow);

        this._feedbackRow = new Adw.ActionRow({title: 'Status'});
        this._feedbackRow.subtitle_lines = 0;
        this._feedbackRow.visible = false;
        group.add(this._feedbackRow);

        return group;
    }

    _suffixButton(label, onClicked) {
        const button = new Gtk.Button({label: label, valign: Gtk.Align.CENTER});
        button.add_css_class('flat');
        button.connect('clicked', onClicked);
        return button;
    }

    _refreshAuthStatus() {
        if (this._authStatusLoading)
            return;
        const binary = resolveOcgoPath();
        if (!binary) {
            this._authStatusRow.subtitle = "The meter's helper is not installed — "
                + 're-run the installer, then restart the preferences.';
            return;
        }
        this._authStatusLoading = true;
        let subprocess = null;
        try {
            subprocess = Gio.Subprocess.new(
                [binary, 'auth', 'show', '--json'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        } catch (error) {
            this._authStatusLoading = false;
            this._authStatusRow.subtitle =
                `could not start the meter helper: ${error.message ?? error}`;
            return;
        }
        subprocess.communicate_utf8_async(null, null, (process, result) => {
            this._authStatusLoading = false;
            let stdout = '';
            let stderr = '';
            try {
                const [, out, err] = process.communicate_utf8_finish(result);
                stdout = out ?? '';
                stderr = err ?? '';
            } catch (error) {
                this._authStatusRow.subtitle =
                    `the meter helper failed: ${error.message ?? error}`;
                return;
            }
            const parsed = parseAuthShowJson(stdout);
            if (!parsed) {
                const detail = stripToolToken(stderr.trim());
                this._authStatusRow.subtitle = detail ||
                    'No credential status available — try Refresh status.';
                return;
            }
            this._applyAuthStatus(parsed);
        });
    }

    _applyAuthStatus(parsed) {
        this._authStatusRow.subtitle = credentialSummary(parsed);
        const store = parsed.store;
        if (!store)
            return;
        const effective = typeof store.data_dir === 'string' ? store.data_dir : '';
        const configured = typeof store.configured_data_dir === 'string'
            ? store.configured_data_dir
            : null;
        const dataDirDelegate = this._dataDirRow.get_delegate();
        if (dataDirDelegate)
            dataDirDelegate.placeholder_text = effective;
        // Never clobber a path the user is typing right now.
        if (!this._dataDirRow.has_focus())
            this._dataDirRow.text = configured ?? '';
        const hint = typeof store.api_key_hint === 'string' && store.api_key_hint !== ''
            ? store.api_key_hint
            : null;
        const keyDelegate = this._keyRow.get_delegate();
        if (keyDelegate) {
            if (store.api_key_configured === true) {
                keyDelegate.placeholder_text = hint
                    ? `Stored key: ${hint}`
                    : 'Fallback API key stored';
            } else {
                keyDelegate.placeholder_text = 'No fallback API key stored';
            }
        }
    }

    // -- credential actions --------------------------------------------------

    _applyDataDir() {
        const path = this._dataDirRow.text.trim();
        if (!path) {
            this._setFeedback(
                'Enter an OpenCode data directory, or use Reset to restore the default.');
            return;
        }
        this._runCredentialAction(['auth', 'set-data-dir', path], null);
    }

    _resetDataDir() {
        this._runCredentialAction(['auth', 'clear-data-dir'], null);
    }

    _saveApiKey() {
        const key = this._keyRow.text;
        if (!key.trim()) {
            this._setFeedback('Enter an API key.');
            return;
        }
        // The secret travels over the stdin pipe only, never argv.
        this._runCredentialAction(['auth', 'set-key', '--stdin'], key);
    }

    _clearApiKey() {
        this._runCredentialAction(['auth', 'clear-key'], null);
    }

    _runCredentialAction(args, stdinText) {
        if (this._credentialActionInProgress)
            return;
        this._credentialActionInProgress = true;
        this._updateCredentialSensitivity();
        this._runCommand(args, stdinText, (ok, stdout, stderr) => {
            if (!ok) {
                this._setFeedback(this._failureMessage(
                    'could not update the credentials', stderr, stdout));
                this._endCredentialAction();
                return;
            }
            if (stdinText !== null)
                this._keyRow.text = '';
            const summary = stripToolToken(
                [stdout.trim(), stderr.trim()].filter(Boolean).join(' '));
            this._setFeedback(summary || 'Credentials updated.');
            this._refreshAuthStatus();
            // Best effort: refresh the panel cache so the meter picks the new
            // credential up right away.
            this._runBestEffortRefresh(() => this._endCredentialAction());
        });
    }

    _runBestEffortRefresh(onDone) {
        const binary = resolveOcgoPath();
        if (!binary) {
            onDone();
            return;
        }
        let subprocess = null;
        try {
            subprocess = Gio.Subprocess.new(
                [binary, 'refresh'],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (error) {
            onDone();
            return;
        }
        subprocess.wait_async(null, (process, result) => {
            try {
                process.wait_finish(result);
            } catch (error) {
                // The panel surfaces the failure from the cache on its own.
            }
            onDone();
        });
    }

    _endCredentialAction() {
        this._credentialActionInProgress = false;
        this._updateCredentialSensitivity();
    }

    _updateCredentialSensitivity() {
        const busy = this._credentialActionInProgress;
        this._refreshStatusButton.sensitive = !busy;
        this._dataDirApplyButton.sensitive = !busy;
        this._dataDirResetButton.sensitive = !busy;
        this._keySaveButton.sensitive = !busy;
        this._keyClearButton.sensitive = !busy;
    }

    _setFeedback(message) {
        const text = typeof message === 'string' ? message.trim() : '';
        this._feedbackRow.subtitle = text;
        this._feedbackRow.visible = text !== '';
    }

    _failureMessage(fallback, stderr, stdout) {
        // The CLI prefixes its messages with its binary name; strip every
        // occurrence so no raw tool error reaches the preferences UI.
        const detail = stripToolToken((stderr || stdout || '').trim());
        return detail || fallback;
    }

    _runCommand(args, stdinText, callback) {
        const binary = resolveOcgoPath();
        if (!binary) {
            callback(false, '', "The meter's helper is not installed — "
                + 're-run the installer, then restart GNOME Shell.');
            return;
        }
        let subprocess = null;
        try {
            subprocess = Gio.Subprocess.new(
                [binary, ...args],
                Gio.SubprocessFlags.STDIN_PIPE |
                    Gio.SubprocessFlags.STDOUT_PIPE |
                    Gio.SubprocessFlags.STDERR_PIPE);
        } catch (error) {
            callback(false, '', `could not start the meter helper: ${error.message ?? error}`);
            return;
        }
        if (stdinText !== null) {
            try {
                // The secret goes through the stdin pipe only, never argv.
                // communicate_utf8_async() below closes stdin after the write.
                const stdin = subprocess.get_stdin_pipe();
                stdin.write_all(new TextEncoder().encode(`${stdinText}\n`), null);
            } catch (error) {
                callback(false, '', `could not send the key to the meter helper: ${error.message ?? error}`);
                return;
            }
        }
        subprocess.communicate_utf8_async(null, null, (process, result) => {
            let stdout = '';
            let stderr = '';
            try {
                const [, out, err] = process.communicate_utf8_finish(result);
                stdout = out ?? '';
                stderr = err ?? '';
            } catch (error) {
                callback(false, '', `the meter helper failed: ${error.message ?? error}`);
                return;
            }
            callback(process.get_successful(), stdout, stderr);
        });
    }
}
