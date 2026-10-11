// Preferences for OpenCode Go Meter: ocgo path, refresh interval, and accounts.

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

const ACCOUNTS_SCHEMA = 2;
const KIND_OPENCODE_DB = 'opencode-db';
const KIND_API_KEY = 'api-key';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

function resolveOcgoPath(settings) {
    try {
        const configured = settings.get_string('ocgo-path').trim();
        if (configured) {
            const resolved = configured.includes('/')
                ? (GLib.file_test(configured, GLib.FileTest.IS_EXECUTABLE)
                    ? configured
                    : null)
                : GLib.find_program_in_path(configured);
            if (resolved)
                return resolved;
        }
    } catch (error) {
        console.error(`[opencode-go-meter] could not read ocgo-path: ${error}`);
    }
    const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
    if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
        return local;
    return GLib.find_program_in_path('ocgo');
}

function parseAccountsJson(text) {
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

export default class OpenCodeGoMeterPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        this._settings = settings;
        this._window = window;
        this._accounts = [];
        this._activeId = null;
        this._updatingActive = false;
        this._accountsLoading = false;
        this._accountsGeneration = 0;
        this._accountsPending = null;
        this._accountActionInProgress = false;
        this._accountActionAwaitingLoad = false;
        this._removeDialogOpen = false;

        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: 'OpenCode Go Meter',
            description: 'How the extension finds the ocgo CLI and how often it refreshes usage.',
        });

        const pathRow = new Adw.EntryRow({
            title: 'ocgo path (empty = auto-detect)',
        });
        settings.bind('ocgo-path', pathRow, 'text', Gio.SettingsBindFlags.DEFAULT);
        group.add(pathRow);

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

        const popupGroup = new Adw.PreferencesGroup({
            title: 'Popup',
            description: 'What the popup shows.',
        });

        const showCreditsRow = new Adw.SwitchRow({
            title: 'Show credits',
            subtitle: 'Credits balance, extra usage, and auto-recharge.',
        });
        settings.bind('show-credits', showCreditsRow, 'active', Gio.SettingsBindFlags.DEFAULT);
        popupGroup.add(showCreditsRow);

        page.add(group);
        page.add(panelGroup);
        page.add(popupGroup);
        page.add(this._buildAccountsGroup());
        window.add(page);

        this._loadAccounts();
    }

    // -- accounts UI ---------------------------------------------------------

    _buildAccountsGroup() {
        const group = new Adw.PreferencesGroup({
            title: 'Accounts',
            description: 'Manage OpenCode Go API-key accounts. The default account uses the OpenCode login.',
        });

        this._activeRow = new Adw.ComboRow({title: 'Active account'});
        this._activeRow.connect('notify::selected', () => this._onActiveChanged());
        group.add(this._activeRow);

        this._idRow = new Adw.EntryRow({title: 'Account id'});
        const idDelegate = this._idRow.get_delegate();
        if (idDelegate)
            idDelegate.placeholder_text = 'work';
        group.add(this._idRow);

        this._labelRow = new Adw.EntryRow({title: 'Label (optional)'});
        group.add(this._labelRow);

        this._keyRow = new Adw.PasswordEntryRow({title: 'API key'});
        group.add(this._keyRow);

        this._applyRow = new Adw.ButtonRow({title: 'Add / replace key'});
        this._applyRow.add_css_class('suggested-action');
        this._applyRow.connect('activated', () => this._applyAccountForm());
        group.add(this._applyRow);

        this._removeRow = new Adw.ButtonRow({title: 'Remove account'});
        this._removeRow.add_css_class('destructive-action');
        this._removeRow.sensitive = false;
        this._removeRow.connect('activated', () => this._confirmRemove());
        group.add(this._removeRow);

        this._feedbackRow = new Adw.ActionRow({title: 'Status'});
        this._feedbackRow.subtitle_lines = 0;
        this._feedbackRow.visible = false;
        group.add(this._feedbackRow);

        return group;
    }

    _setFeedback(message) {
        const text = typeof message === 'string' ? message.trim() : '';
        this._feedbackRow.subtitle = text;
        this._feedbackRow.visible = text !== '';
    }

    _selectedAccount() {
        const index = this._activeRow.selected;
        if (!Number.isInteger(index) || index < 0 || index >= this._accounts.length)
            return null;
        return this._accounts[index];
    }

    _renderAccounts() {
        this._updatingActive = true;
        try {
            if (this._accounts.length === 0) {
                this._activeRow.model = Gtk.StringList.new(['No accounts']);
                this._activeRow.selected = 0; // placeholder; no account selected
            } else {
                const labels = this._accounts.map(account => account.label);
                this._activeRow.model = Gtk.StringList.new(labels);
                const index = this._accounts.findIndex(
                    account => account.id === this._activeId);
                this._activeRow.selected = index >= 0 ? index : 0;
            }
        } finally {
            this._updatingActive = false;
        }
        this._updateActionSensitivity();
    }

    _updateActionSensitivity() {
        const busy = this._accountActionInProgress;
        this._applyRow.sensitive = !busy;
        const selected = this._selectedAccount();
        this._removeRow.sensitive = !busy && !!selected;
    }

    _beginAccountAction() {
        if (this._accountActionInProgress)
            return false;
        this._accountActionInProgress = true;
        this._accountActionAwaitingLoad = false;
        this._updateActionSensitivity();
        return true;
    }

    _endAccountAction() {
        this._accountActionInProgress = false;
        this._accountActionAwaitingLoad = false;
        this._updateActionSensitivity();
    }

    _applyAccounts(parsed) {
        if (parsed) {
            this._accounts = parsed.accounts;
            this._activeId = parsed.active;
        } else {
            this._accounts = [];
            this._activeId = null;
        }
        this._renderAccounts();
    }

    _loadAccounts() {
        const generation = ++this._accountsGeneration;
        if (this._accountsLoading) {
            this._accountsPending = {generation};
            return;
        }
        this._startAccountLoad(generation);
    }

    _startAccountLoad(generation) {
        const binary = resolveOcgoPath(this._settings);
        if (!binary) {
            this._finishAccountLoad(
                generation, null, 'ocgo not found; set the path above');
            return;
        }
        this._accountsLoading = true;
        try {
            const subprocess = Gio.Subprocess.new(
                [binary, 'account', 'list', '--json'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            subprocess.communicate_utf8_async(null, null, (process, result) => {
                this._accountsLoading = false;
                let stdout = '';
                try {
                    const [, out] = process.communicate_utf8_finish(result);
                    stdout = out ?? '';
                } catch (error) {
                    this._finishAccountLoad(generation, null, 'could not read accounts');
                    return;
                }
                const parsed = process.get_successful()
                    ? parseAccountsJson(stdout)
                    : null;
                if (!parsed) {
                    this._finishAccountLoad(generation, null, 'could not read accounts');
                    return;
                }
                this._finishAccountLoad(generation, parsed, null);
            });
        } catch (error) {
            this._accountsLoading = false;
            this._finishAccountLoad(
                generation, null, `could not read accounts: ${error.message ?? error}`);
        }
    }

    _finishAccountLoad(generation, parsed, errorMessage) {
        if (generation === this._accountsGeneration) {
            if (parsed) {
                this._applyAccounts(parsed);
            } else {
                this._applyAccounts(null);
                this._setFeedback(errorMessage);
            }
            if (this._accountActionAwaitingLoad)
                this._endAccountAction();
        }
        // Stale results are discarded, never applied; a coalesced newer
        // request (one in-flight + one pending max) starts after this one.
        const pending = this._accountsPending;
        this._accountsPending = null;
        if (pending)
            this._startAccountLoad(pending.generation);
    }

    _onActiveChanged() {
        if (this._updatingActive)
            return;
        const account = this._selectedAccount();
        if (!account || account.id === this._activeId) {
            this._updateActionSensitivity();
            return;
        }
        this._updateActionSensitivity();
        this._runAccountCommand(
            ['account', 'use', account.id], null, (ok, stdout, stderr) => {
                if (ok) {
                    this._setFeedback(`Active account: ${account.label}`);
                    this._loadAccounts();
                } else {
                    this._setFeedback(this._failureMessage(
                        'could not switch account', stderr, stdout));
                    this._renderAccounts(); // restore the real active account
                }
            });
    }

    _applyAccountForm() {
        const accountId = this._idRow.text.trim();
        const label = this._labelRow.text.trim();
        const key = this._keyRow.text;
        const error = accountFormError(accountId, key);
        if (error) {
            this._setFeedback(error);
            return;
        }
        if (!this._beginAccountAction())
            return;
        const command = accountCommandFor(accountId, this._accounts);
        const args = ['account', command, accountId, '--store', 'auto'];
        if (command === 'add' && label)
            args.push('--label', label);
        this._runAccountCommand(args, key, (ok, stdout, stderr) => {
            this._keyRow.text = '';
            if (ok) {
                const summary = [stdout.trim(), stderr.trim()]
                    .filter(Boolean)
                    .join(' ');
                this._setFeedback(summary || `Account '${accountId}' updated.`);
                this._accountActionAwaitingLoad = true;
                this._loadAccounts();
            } else {
                this._setFeedback(this._failureMessage(
                    'could not update the account', stderr, stdout));
                this._endAccountAction();
            }
        });
    }

    _confirmRemove() {
        const account = this._selectedAccount();
        if (!account)
            return;
        if (this._accountActionInProgress || this._removeDialogOpen)
            return;
        this._removeDialogOpen = true;
        this._removeRow.sensitive = false;
        this._presentRemoveDialog(account);
    }

    _presentRemoveDialog(account) {
        const dialog = new Adw.MessageDialog({
            transient_for: this._window,
            heading: `Remove account '${account.label}'?`,
            body: removeConfirmBody(account.kind),
        });
        dialog.add_response('cancel', 'Cancel');
        dialog.add_response('remove', 'Remove');
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE);
        dialog.set_default_response('cancel');
        dialog.set_close_response('cancel');
        dialog.connect('response', (_dialog, response) => {
            this._onRemoveDialogResponse(account, response);
        });
        dialog.present();
    }

    _onRemoveDialogResponse(account, response) {
        this._removeDialogOpen = false;
        this._updateActionSensitivity();
        if (response === 'remove')
            this._removeAccount(account);
    }

    _removeAccount(account) {
        if (!this._beginAccountAction())
            return;
        this._runAccountCommand(
            ['account', 'remove', account.id], null, (ok, stdout, stderr) => {
                if (ok) {
                    this._setFeedback(
                        stdout.trim() || `Removed account '${account.id}'.`);
                    this._accountActionAwaitingLoad = true;
                    this._loadAccounts();
                } else {
                    this._setFeedback(this._failureMessage(
                        'could not remove the account', stderr, stdout));
                    this._endAccountAction();
                }
            });
    }

    _failureMessage(fallback, stderr, stdout) {
        return (stderr || stdout || '').trim() || fallback;
    }

    _runAccountCommand(args, stdinText, callback) {
        const binary = resolveOcgoPath(this._settings);
        if (!binary) {
            callback(false, '', 'ocgo not found; set the path above');
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
            callback(false, '', `could not start ocgo: ${error.message ?? error}`);
            return;
        }
        if (stdinText !== null) {
            try {
                // The secret goes through the stdin pipe only, never argv.
                // communicate_utf8_async() below closes stdin after the write.
                const stdin = subprocess.get_stdin_pipe();
                stdin.write_all(new TextEncoder().encode(`${stdinText}\n`), null);
            } catch (error) {
                callback(false, '', `could not send the key to ocgo: ${error.message ?? error}`);
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
                callback(false, '', `ocgo failed: ${error.message ?? error}`);
                return;
            }
            callback(process.get_successful(), stdout, stderr);
        });
    }
}
