// Preferences for OpenCode Go Meter: ocgo path, refresh interval, and accounts.

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

const ACCOUNTS_SCHEMA = 2;
const DISCOVER_SCHEMA = 1;
const KIND_OPENCODE_DB = 'opencode-db';
const KIND_API_KEY = 'api-key';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const AUTO_CREDENTIAL_LABEL = 'Auto (follows the active account)';

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
            // Additive field (the payload keeps schema 2): null means the
            // account is not pinned to a database credential.
            credential_id: typeof entry.credential_id === 'string' &&
                entry.credential_id !== ''
                ? entry.credential_id
                : null,
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

export default class OpenCodeGoMeterPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        this._settings = settings;
        this._window = window;
        this._accounts = [];
        this._credentials = [];
        this._activeId = null;
        this._updatingActive = false;
        this._accountsLoading = false;
        this._accountsGeneration = 0;
        this._accountsPending = null;
        this._accountActionInProgress = false;
        this._accountActionAwaitingLoad = false;
        this._removeDialogOpen = false;
        this._activateDialogOpen = false;
        this._typeKinds = [];
        this._typeModelSignature = null;
        this._credentialEntries = [];
        this._credentialModelSignature = null;

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
        for (const accountsGroup of this._buildAccountsGroups())
            page.add(accountsGroup);
        window.add(page);

        this._updateTypeModel();
        this._loadAccounts();
    }

    // -- accounts UI ---------------------------------------------------------

    _buildAccountsGroups() {
        const group = new Adw.PreferencesGroup({
            title: 'Accounts',
            description: 'The account shown in the panel and popup.',
        });

        this._activeRow = new Adw.ComboRow({title: 'Active account'});
        this._activeRow.connect('notify::selected', () => this._onActiveChanged());
        group.add(this._activeRow);

        this._removeRow = new Adw.ButtonRow({title: 'Remove account'});
        this._removeRow.add_css_class('destructive-action');
        this._removeRow.sensitive = false;
        this._removeRow.connect('activated', () => this._confirmRemove());
        group.add(this._removeRow);

        this._activateRow = new Adw.ButtonRow({
            title: 'Make active in OpenCode',
        });
        this._activateRow.sensitive = false;
        this._activateRow.connect('activated', () => this._confirmActivate());
        group.add(this._activateRow);

        const formGroup = new Adw.PreferencesGroup({
            title: 'Add or replace an account',
            description: 'Adds a new account, or replaces the API key of an existing one.',
        });

        this._idRow = new Adw.EntryRow({title: 'Account id'});
        const idDelegate = this._idRow.get_delegate();
        if (idDelegate)
            idDelegate.placeholder_text = 'work';
        formGroup.add(this._idRow);

        this._labelRow = new Adw.EntryRow({title: 'Label (optional)'});
        formGroup.add(this._labelRow);

        this._typeRow = new Adw.ComboRow({title: 'Type'});
        this._typeRow.connect('notify::selected', () => this._updateFormState());
        formGroup.add(this._typeRow);

        this._credentialRow = new Adw.ComboRow({title: 'OpenCode credential'});
        this._credentialRow.visible = false;
        formGroup.add(this._credentialRow);

        this._keyRow = new Adw.PasswordEntryRow({title: 'API key'});
        formGroup.add(this._keyRow);

        this._applyRow = new Adw.ButtonRow({title: 'Add / replace key'});
        this._applyRow.add_css_class('suggested-action');
        this._applyRow.connect('activated', () => this._applyAccountForm());
        formGroup.add(this._applyRow);

        this._feedbackRow = new Adw.ActionRow({title: 'Status'});
        this._feedbackRow.subtitle_lines = 0;
        this._feedbackRow.visible = false;
        formGroup.add(this._feedbackRow);

        return [group, formGroup];
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

    // The add-flow type model follows the loaded accounts and credentials:
    // "OpenCode login" stays available while an auto (unpinned) login is not
    // registered yet, or while at least one discovered credential is not
    // registered as a pinned login.
    _hasAutoLogin() {
        return this._accounts.some(
            account => account.kind === KIND_OPENCODE_DB &&
                !account.credential_id);
    }

    _typeOptions() {
        const hasAuto = this._hasAutoLogin();
        const unregistered = this._credentialChoices().some(
            choice => choice.credentialId !== null);
        return !hasAuto || unregistered
            ? [KIND_OPENCODE_DB, KIND_API_KEY]
            : [KIND_API_KEY];
    }

    _typeLabel(kind) {
        return kind === KIND_OPENCODE_DB ? 'OpenCode login' : 'API key';
    }

    _selectedType() {
        const index = this._typeRow.selected;
        if (!Number.isInteger(index) || index < 0 || index >= this._typeKinds.length)
            return null;
        return this._typeKinds[index];
    }

    // Credential picker entries: the auto binding when no auto login exists,
    // plus every discovered credential that is not registered yet.
    _credentialChoices() {
        const choices = [];
        if (!this._hasAutoLogin())
            choices.push({credentialId: null, label: AUTO_CREDENTIAL_LABEL});
        const registered = new Set();
        for (const account of this._accounts) {
            if (account.kind === KIND_OPENCODE_DB && account.credential_id)
                registered.add(account.credential_id);
        }
        for (const credential of this._credentials) {
            if (registered.has(credential.id))
                continue;
            choices.push({
                credentialId: credential.id,
                label: credentialDisplayLabel(credential),
            });
        }
        return choices;
    }

    _selectedCredential() {
        const index = this._credentialRow.selected;
        if (!Number.isInteger(index) || index < 0 ||
                index >= this._credentialEntries.length)
            return null;
        return this._credentialEntries[index];
    }

    _updateCredentialModel() {
        const previous = this._selectedCredential();
        const choices = this._credentialChoices();
        const signature = choices.map(
            choice => `${choice.credentialId ?? ''}\u0000${choice.label}`
        ).join('\u0001');
        if (signature !== this._credentialModelSignature) {
            this._credentialModelSignature = signature;
            this._credentialEntries = choices;
            this._credentialRow.model = Gtk.StringList.new(
                choices.map(choice => choice.label));
        }
        // Keep the user's pick across rebuilds; a vanished credential falls
        // back to the first entry (auto when it is offered).
        let index = 0;
        if (previous !== null && previous.credentialId !== null) {
            const found = this._credentialEntries.findIndex(
                choice => choice.credentialId === previous.credentialId);
            if (found >= 0)
                index = found;
        }
        this._credentialRow.selected =
            this._credentialEntries.length > 0 ? index : -1;
    }

    _updateTypeModel() {
        const kinds = this._typeOptions();
        const previous = this._selectedType();
        const signature = kinds.join('\u0000');
        if (signature !== this._typeModelSignature) {
            this._typeModelSignature = signature;
            this._typeKinds = kinds;
            this._typeRow.model = Gtk.StringList.new(
                kinds.map(kind => this._typeLabel(kind)));
        }
        // The user's choice survives a rebuild; when the OpenCode login option
        // disappears (an auto login appeared and every credential is
        // registered), fall back to the remaining type.
        const index = previous === null ? -1 : kinds.indexOf(previous);
        this._typeRow.selected = index >= 0 ? index : 0;
        this._updateFormState();
        this._updateCredentialModel();
    }

    _updateFormState() {
        const fromDb = this._selectedType() === KIND_OPENCODE_DB;
        this._keyRow.visible = !fromDb;
        if (fromDb)
            this._keyRow.text = '';
        this._credentialRow.visible = fromDb;
        this._applyRow.title = fromDb ? 'Add account' : 'Add / replace key';
    }

    // Display-only suffix marking a pinned login whose credential is the
    // active one in OpenCode. Purely informational: selection stays by index.
    _accountDisplayLabel(account) {
        if (account.kind !== KIND_OPENCODE_DB || !account.credential_id)
            return account.label;
        const credential = this._credentials.find(
            entry => entry.id === account.credential_id);
        return credential && credential.active
            ? `${account.label} (active in OpenCode)`
            : account.label;
    }

    // Pinned logins whose credential disappeared from the database listing.
    _danglingLogins() {
        const known = new Set(this._credentials.map(entry => entry.id));
        return this._accounts.filter(account =>
            account.kind === KIND_OPENCODE_DB && account.credential_id &&
            !known.has(account.credential_id));
    }

    _renderAccounts() {
        this._updatingActive = true;
        try {
            if (this._accounts.length === 0) {
                this._activeRow.model = Gtk.StringList.new(['No accounts']);
                this._activeRow.selected = 0; // placeholder; no account selected
            } else {
                const labels = this._accounts.map(
                    account => this._accountDisplayLabel(account));
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
        this._activateRow.sensitive = !busy && !!selected &&
            selected.kind === KIND_OPENCODE_DB && !!selected.credential_id;
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
        this._updateTypeModel();
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
                generation, null, null, 'ocgo not found; set the path above', null);
            return;
        }
        this._accountsLoading = true;
        const results = {
            accounts: null,
            accountsError: null,
            credentials: null,
            discoverError: null,
        };
        let remaining = 2;
        const finish = () => {
            if (--remaining > 0)
                return;
            this._accountsLoading = false;
            this._finishAccountLoad(
                generation, results.accounts, results.credentials,
                results.accountsError, results.discoverError);
        };
        // Accounts and discovered credentials load together; a discover
        // failure is non-fatal (empty credential list, auto path intact).
        this._readJsonCommand(
            binary, ['account', 'list', '--json'], parseAccountsJson, parsed => {
                results.accounts = parsed;
                results.accountsError = parsed ? null : 'could not read accounts';
                finish();
            });
        this._readJsonCommand(
            binary, ['account', 'discover', '--json'], parseDiscoverJson, parsed => {
                results.credentials = parsed;
                results.discoverError = parsed
                    ? null
                    : 'could not list the OpenCode credentials';
                finish();
            });
    }

    _readJsonCommand(binary, args, parser, callback) {
        let subprocess = null;
        try {
            subprocess = Gio.Subprocess.new(
                [binary, ...args],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (error) {
            callback(null);
            return;
        }
        subprocess.communicate_utf8_async(null, null, (process, result) => {
            let stdout = '';
            try {
                const [, out] = process.communicate_utf8_finish(result);
                stdout = out ?? '';
            } catch (error) {
                callback(null);
                return;
            }
            callback(process.get_successful() ? parser(stdout) : null);
        });
    }

    _finishAccountLoad(generation, accountsParsed, credentialsParsed,
        accountsError, discoverError = null) {
        if (generation === this._accountsGeneration) {
            // Discover defaults to an empty list; a failed discover only
            // disables the specific-credential choices (the auto entry, when
            // offered, keeps working) and surfaces through the status row.
            this._credentials = credentialsParsed
                ? credentialsParsed.credentials
                : [];
            if (accountsParsed) {
                this._applyAccounts(accountsParsed);
            } else {
                this._applyAccounts(null);
            }
            const messages = [];
            if (!accountsParsed && accountsError)
                messages.push(accountsError);
            if (discoverError)
                messages.push(discoverError);
            // Dangling feedback only when discover returned a real list; a
            // failed discover is already reported and cannot tell "gone" from
            // "unreadable".
            if (!discoverError && credentialsParsed) {
                for (const account of this._danglingLogins()) {
                    messages.push(
                        `Account '${account.label}' points to an OpenCode ` +
                        'credential that no longer exists — remove it or sign ' +
                        'in again in OpenCode.');
                }
            }
            if (messages.length > 0)
                this._setFeedback(messages.join('\n'));
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
        const fromDb = this._selectedType() === KIND_OPENCODE_DB;
        const key = fromDb ? '' : this._keyRow.text;
        const error = accountFormError(accountId, key, fromDb);
        if (error) {
            this._setFeedback(error);
            return;
        }
        const credential = fromDb ? this._selectedCredential() : null;
        if (fromDb && !credential) {
            this._setFeedback('No OpenCode credentials are available to add.');
            return;
        }
        if (!this._beginAccountAction())
            return;
        let args;
        if (fromDb) {
            // The CLI registers an OpenCode login; no key, no stdin. Without
            // --credential the account follows the active OpenCode credential.
            args = ['account', 'add', accountId, '--from-db'];
            if (label)
                args.push('--label', label);
            if (credential.credentialId)
                args.push('--credential', credential.credentialId);
        } else {
            const command = accountCommandFor(accountId, this._accounts);
            args = ['account', command, accountId, '--store', 'auto'];
            if (command === 'add' && label)
                args.push('--label', label);
        }
        this._runAccountCommand(args, fromDb ? null : key, (ok, stdout, stderr) => {
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
                    fromDb ? 'could not add the OpenCode login account'
                        : 'could not update the account',
                    stderr, stdout));
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

    _confirmActivate() {
        const account = this._selectedAccount();
        if (!account)
            return;
        if (this._accountActionInProgress || this._activateDialogOpen)
            return;
        this._activateDialogOpen = true;
        this._activateRow.sensitive = false;
        this._presentActivateDialog(account);
    }

    _presentActivateDialog(account) {
        const dialog = new Adw.MessageDialog({
            transient_for: this._window,
            heading: `Make '${account.label}' active in OpenCode?`,
            body: 'OpenCode will use this account for new sessions.',
        });
        dialog.add_response('cancel', 'Cancel');
        dialog.add_response('activate', 'Make active');
        dialog.set_response_appearance('activate', Adw.ResponseAppearance.SUGGESTED);
        dialog.set_default_response('cancel');
        dialog.set_close_response('cancel');
        dialog.connect('response', (_dialog, response) => {
            this._onActivateDialogResponse(account, response);
        });
        dialog.present();
    }

    _onActivateDialogResponse(account, response) {
        this._activateDialogOpen = false;
        this._updateActionSensitivity();
        if (response === 'activate')
            this._activateInOpencode(account);
    }

    _activateInOpencode(account) {
        if (!this._beginAccountAction())
            return;
        this._runAccountCommand(
            ['account', 'activate-in-opencode', account.id], null,
            (ok, stdout, stderr) => {
                if (ok) {
                    this._setFeedback(
                        stdout.trim() || `Account '${account.id}' is now active in OpenCode.`);
                    this._accountActionAwaitingLoad = true;
                    this._loadAccounts();
                } else {
                    this._setFeedback(this._failureMessage(
                        'could not make the account active in OpenCode',
                        stderr, stdout));
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
