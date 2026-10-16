// OpenCode Go Meter — standalone "Add / replace account key" window (GTK 3).
//
// The Cinnamon applet hosts this form inside a modal in-shell dialog, which
// pins the whole Cinnamon session while it is open. This file is the same
// form as a real, non-blocking desktop window: the applet spawns it as its
// own `cjs` process (see cinnamon/applet.js) and keeps running.
//
// It is a faithful port of the applet dialog flow; the pure helpers and the
// user-visible texts are deliberate copies of cinnamon/applet.js, marked
// `Kept in sync with cinnamon/applet.js — deliberate copy.` below. Port map:
//
//   truncate / expandHome / shortenHomePath / resolveExecutable —
//       display and path helpers.
//   stripToolToken / formatFailureDetail — CLI output cleanup.
//   parseAccountList / parseDiscoverStore / parseDiscoverJson —
//       `ocgo account list|discover --json` payload parsers.
//   accountFormError / accountCommandFor — form validation and the
//       set-key-vs-add choice.
//   resolveOpenCodeBinary / loginTerminalCandidates — login launch paths.
//   AccountsWindow._credentialChoices / _hasAutoLogin / _storeHasLogin /
//       _hasBindableLogin / _suggestedAccountId — the form's guided state.
//   AccountsWindow._writeLoginScript / _launchLoginTerminal /
//       _copyLoginCommand / _startLoginPoll — the login flow.
//   AccountsWindow._onSubmit / _onRefresh / _updateTypeState /
//       _refreshGuidedState — the submit and reload flows.
//
// Differences that GTK forces, not choices: St widgets become GTK widgets
// (St.Entry -> Gtk.Entry, radio group -> Gtk.RadioButton group, the St combo
// -> Gtk.ComboBoxText) and the widget-local closures of the applet's
// on_accounts_apply() become methods on AccountsWindow.
//
// Secrets: the API key never reaches argv, the environment, or a log. It is
// written to the ocgo child's stdin pipe only, exactly like the applet's
// _runAccountCommand. Nothing here reads a credential.

imports.gi.versions.Gtk = '3.0';
// Gdk is needed for the display (clipboard fallback). Machines that ship both
// the GTK 3 and the GTK 4 typelibs must pin it too: an unpinned import picks
// Gdk 4.0 and GTK 3 then refuses to initialize.
imports.gi.versions.Gdk = '3.0';

const Gdk = imports.gi.Gdk;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Gtk = imports.gi.Gtk;
const System = imports.system;

const MAX_WARNING_CHARS = 70;
const LOGIN_POLL_SECONDS = 4;
const LOGIN_POLL_TICKS = 75; // ~5 minutes

const ACCOUNTS_SCHEMA = 2;
const DISCOVER_SCHEMA = 1;
const KIND_OPENCODE_DB = 'opencode-db';
const ACCOUNT_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const AUTO_CREDENTIAL_LABEL = 'Auto (follows the active account)';
// The CLI owns the full keyring error (core/ocgo/accounts.py); the window
// only matches these stable substrings to offer the explicit file backend
// instead of surfacing the CLI's terminal-level instruction. The first one
// means secret-tool is not installed, the second one that it runs but could
// not store the secret (no keyring service on the bus, or a timeout).
const SECRET_TOOL_UNAVAILABLE_MARKER = 'secret-tool is not available';
const SECRET_TOOL_STORE_FAILED_MARKER =
    'secret-tool could not store the secret';

// Script arguments: cjs (Cinnamon's runtime) exposes them as
// System.programArgs, plain gjs as System.argv; one of the two is always
// there.
const ARGV = System.argv || System.programArgs || [];

function logError(message, error) {
    console.error(`[opencode-go-meter] ${message}${error ? `: ${error}` : ''}`);
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
function truncate(text, max) {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
function expandHome(path) {
    if (path === '~')
        return GLib.get_home_dir();
    if (path.startsWith('~/'))
        return GLib.build_filenamev([GLib.get_home_dir(), path.slice(2)]);
    return path;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
// Display form of a credential-store path: a home prefix shortens to '~' so
// the dialog line stays readable.
function shortenHomePath(path) {
    const home = GLib.get_home_dir();
    if (home && path.startsWith(`${home}/`))
        return `~${path.slice(home.length)}`;
    return path;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
function resolveExecutable(path) {
    if (!path)
        return null;
    if (!path.includes('/'))
        return GLib.find_program_in_path(path);
    return GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE) ? path : null;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
// One plain-language rewrite for CLI or cache failure details: strip the tool
// token first, then map the known terminal-level messages to actionable copy.
// Unknown details pass through token-stripped.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
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

// Kept in sync with cinnamon/applet.js — deliberate copy.
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
    // store block sanitizes to null, so the window degrades to the
    // credential list alone.
    return {credentials, store: parseDiscoverStore(payload.store)};
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
// Display-only suffix for a discovered credential: the email when present,
// the organization name otherwise.
function credentialDisplayLabel(credential) {
    const suffix = credential.email || credential.org_name;
    return suffix ? `${credential.label} (${suffix})` : credential.label;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
function accountFormError(accountId, key, fromDb = false) {
    if (!accountId)
        return 'Enter an account id.';
    if (!ACCOUNT_ID_RE.test(accountId))
        return 'Invalid account id: use a-z, 0-9, dot, underscore, or dash (max 64).';
    if (!fromDb && !key)
        return 'Enter an API key.';
    return null;
}

// Kept in sync with cinnamon/applet.js — deliberate copy.
function accountCommandFor(accountId, accounts) {
    return accounts.some(account => account.id === accountId) ? 'set-key' : 'add';
}

// Same lookup as the applet's _ocgoPath(): the standard install location
// first, then PATH.
function defaultOcgoPath() {
    const local = GLib.build_filenamev(
        [GLib.get_home_dir(), '.local', 'bin', 'ocgo']);
    if (GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE))
        return local;
    return GLib.find_program_in_path('ocgo');
}

// The applet passes the helper it resolved itself; without the flag the
// window resolves it the same way.
function ocgoPathFromArgv(argv) {
    const index = argv.indexOf('--ocgo');
    if (index >= 0 && argv.length > index + 1 && argv[index + 1] !== '')
        return argv[index + 1];
    return defaultOcgoPath();
}

function wrappedLabel(text = '') {
    const label = new Gtk.Label({label: text, xalign: 0});
    label.set_line_wrap(true);
    return label;
}

// Vertical label-over-child row, the applet's _labeledRow().
function labeledRow(text, child) {
    const row = new Gtk.Box({
        orientation: Gtk.Orientation.VERTICAL,
        spacing: 2,
    });
    row.pack_start(new Gtk.Label({label: text, xalign: 0}), false, false, 0);
    child.set_hexpand(true);
    row.pack_start(child, false, false, 0);
    return row;
}

class AccountsWindow {
    constructor(ocgoPath) {
        this._ocgoPath = ocgoPath;
        this._window = null;
        this._closed = false;

        // Account and credential state, loaded by _loadAccounts().
        this._accounts = [];
        this._accountsLoaded = false;
        this._accountsLoading = false;
        this._accountsPending = null;
        this._accountsGeneration = 0;
        this._accountsError = null;
        this._accountsErrorLogged = false;
        this._credentials = [];
        this._store = null;
        this._credentialsError = null;
        this._credentialsErrorLogged = false;

        // Form state that the applet kept in closures.
        this._selectedCredential = null;
        this._comboChoices = [];
        this._comboUpdating = false;
        this._fileFallbackOffered = false;
        this._initialPickApplied = false;

        this._loginPollId = 0;
        this._loginPollTicks = 0;
        this._loginPollSerial = 0;
        this._closeTimerId = 0;

        this._buildWindow();
    }

    // -- window --------------------------------------------------------------

    _buildWindow() {
        this._window = new Gtk.Window({
            title: 'Add / replace account key',
            default_width: 460,
            default_height: 560,
            resizable: true,
        });
        this._window.set_position(Gtk.WindowPosition.CENTER);
        this._window.connect('destroy', () => this._onWindowDestroyed());
        // The applet's Cancel button answers Escape; a GTK window has to ask
        // for the key itself.
        this._window.connect('key-press-event', (widget, event) => {
            const [, keyval] = event.get_keyval();
            if (keyval === Gdk.KEY_Escape) {
                this._close();
                return true;
            }
            return false;
        });

        const content = new Gtk.Box({
            orientation: Gtk.Orientation.VERTICAL,
            spacing: 8,
            margin: 12,
        });
        this._window.add(content);

        this._descriptionLabel = wrappedLabel();
        content.pack_start(this._descriptionLabel, false, false, 0);

        // First-run affordance: with no discoverable OpenCode login (or an
        // unreadable credential store) the "OpenCode login" type can only
        // dead-end, so the login path and the API-key path are offered up
        // front. The block is always built and hidden while a login is
        // available; _refreshGuidedState() owns its visibility and content.
        this._helperBox = new Gtk.Box({
            orientation: Gtk.Orientation.VERTICAL,
            spacing: 4,
        });
        this._helperLabel = wrappedLabel();
        this._helperBox.pack_start(this._helperLabel, false, false, 0);
        // Second line for the no-login state: the credential-store paths the
        // CLI checked (the database, plus auth.json when the legacy file
        // exists), so the empty state is self-diagnosable.
        this._storeLabel = wrappedLabel();
        this._helperBox.pack_start(this._storeLabel, false, false, 0);

        const helperButtons = new Gtk.Box({
            orientation: Gtk.Orientation.HORIZONTAL,
            spacing: 6,
        });
        helperButtons.set_halign(Gtk.Align.START);
        // Always offered: "opencode auth login" creates (or repairs) the
        // credential store, and it is also the recovery path when the store
        // itself could not be read.
        this._loginButton = new Gtk.Button({label: 'Log in with OpenCode…'});
        this._loginButton.connect('clicked', () => this._onLogin());
        helperButtons.pack_start(this._loginButton, false, false, 0);
        this._refreshButton = new Gtk.Button({label: 'Refresh'});
        this._refreshButton.connect('clicked', () => this._onRefresh());
        helperButtons.pack_start(this._refreshButton, false, false, 0);
        this._helperBox.pack_start(helperButtons, false, false, 0);
        content.pack_start(this._helperBox, false, false, 0);

        this._idEntry = new Gtk.Entry({placeholder_text: 'e.g. work'});
        this._labelEntry = new Gtk.Entry({placeholder_text: 'optional'});
        this._keyEntry = new Gtk.Entry({
            placeholder_text: 'oc_sk_…',
            visibility: false,
        });
        for (const entry of [this._idEntry, this._labelEntry, this._keyEntry])
            entry.connect('activate', () => this._onSubmit());

        content.pack_start(
            labeledRow('Account id', this._idEntry), false, false, 0);
        const idHint = wrappedLabel('Just a name for this account here — it '
            + 'does not need to match anything in OpenCode.');
        content.pack_start(idHint, false, false, 0);
        content.pack_start(
            labeledRow('Label (optional)', this._labelEntry), false, false, 0);

        // Both types are always listed: the "OpenCode login" type is disabled
        // (insensitive, like the applet's _setRadioOptionEnabled) when no
        // binding can succeed — no discovered credential is free to bind and
        // the auto entry cannot resolve one either — so the dead end is
        // visible up front instead of failing on submit. RADIO_TYPE_LOGIN is
        // the radio whose active state means the applet's
        // `selectedType() === KIND_OPENCODE_DB`.
        this._loginRadio = new Gtk.RadioButton({label: 'OpenCode login'});
        this._apiKeyRadio = new Gtk.RadioButton({
            label: 'API key',
            group: this._loginRadio,
        });
        const typeBox = new Gtk.Box({
            orientation: Gtk.Orientation.HORIZONTAL,
            spacing: 6,
        });
        typeBox.pack_start(this._loginRadio, false, false, 0);
        typeBox.pack_start(this._apiKeyRadio, false, false, 0);
        content.pack_start(labeledRow('Type', typeBox), false, false, 0);

        // Credential picker: the applet draws a themed button opening a popup
        // menu; a GTK combo box is the same control on this toolkit. Entries
        // and the auto entry come from _credentialChoices().
        this._credentialCombo = new Gtk.ComboBoxText();
        this._credentialCombo.connect(
            'changed', () => this._onCredentialChanged());
        this._credentialRow = labeledRow('Credential', this._credentialCombo);
        content.pack_start(this._credentialRow, false, false, 0);

        this._keyRow = labeledRow('API key', this._keyEntry);
        content.pack_start(this._keyRow, false, false, 0);

        this._statusLabel = wrappedLabel();
        content.pack_start(this._statusLabel, false, false, 0);

        const buttonRow = new Gtk.Box({
            orientation: Gtk.Orientation.HORIZONTAL,
            spacing: 6,
        });
        buttonRow.set_halign(Gtk.Align.END);
        this._cancelButton = new Gtk.Button({label: 'Cancel'});
        this._cancelButton.connect('clicked', () => this._close());
        buttonRow.pack_start(this._cancelButton, false, false, 0);
        this._confirmButton = new Gtk.Button({label: 'Add / replace key'});
        this._confirmButton.connect('clicked', () => this._onSubmit());
        this._confirmButton.set_can_default(true);
        this._window.set_default(this._confirmButton);
        buttonRow.pack_start(this._confirmButton, false, false, 0);
        content.pack_start(buttonRow, false, false, 0);

        // The type drives row visibility and the confirm label; only the
        // login radio carries the signal: any group change toggles it.
        this._loginRadio.connect('toggled', () => this._updateTypeState());

        // Initial guided state: helper visibility and message, checked
        // paths, radio enablement and the combo all come from this one path.
        this._refreshGuidedState();
    }

    open() {
        this._window.show_all();
        // show_all() reveals every child; the type-driven rows must be
        // re-applied afterwards, exactly like the applet's updateTypeState()
        // call after building the dialog.
        this._updateTypeState();
        this._window.set_focus(this._idEntry);
        this._window.present();
        // Silent freshness reload, like the applet's reload when the dialog
        // opens: a login made outside the window (for example in a terminal)
        // must not leave a stale "no login found" behind. No status change
        // from this reload.
        this._loadAccounts(() => {
            if (this._closed)
                return;
            const guided = this._refreshGuidedState();
            // The applet builds its dialog after the account list is known,
            // so its initial type pick and the account-id suggestion happen
            // there; this window is built before the load, so both land on the
            // first load completion instead — same rule, same moment in the
            // user's eyes.
            if (!this._initialPickApplied) {
                this._initialPickApplied = true;
                if (guided.allowLogin)
                    this._loginRadio.set_active(true);
                if (this._idEntry.get_text() === '')
                    this._idEntry.set_text(this._suggestedAccountId());
            }
        });
    }

    _close() {
        if (this._closed)
            return;
        this._window.destroy();
    }

    _onWindowDestroyed() {
        this._closed = true;
        this._stopLoginPoll();
        if (this._closeTimerId) {
            GLib.source_remove(this._closeTimerId);
            this._closeTimerId = 0;
        }
        Gtk.main_quit();
    }

    // -- account state -------------------------------------------------------

    // The guided-state helpers below are kept in sync with
    // cinnamon/applet.js — deliberate copies.

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

    // First free account-id suggestion for the add form: 'work', then
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

    // -- loading -------------------------------------------------------------

    _loadAccounts(onComplete = null) {
        const generation = ++this._accountsGeneration;
        if (this._accountsLoading) {
            this._accountsPending = {generation, onComplete};
            return;
        }
        this._startAccountLoad(generation, onComplete);
    }

    _startAccountLoad(generation, onComplete) {
        if (!this._ocgoPath) {
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
        this._spawnAccountJson(['account', 'list', '--json'], parseAccountList,
            (parsed, errorMessage, error = null) => {
                accounts.parsed = parsed;
                accounts.errorMessage = errorMessage;
                accounts.error = error;
                finish();
            });
        this._spawnAccountJson(
            ['account', 'discover', '--json'], parseDiscoverJson,
            (parsed, errorMessage) => {
                credentials.parsed = parsed;
                credentials.errorMessage = errorMessage;
                finish();
            });
    }

    _spawnAccountJson(args, parser, callback) {
        const command = `${args[0]} ${args[1]}`;
        this._runCommand(args, null, (ok, stdout, stderr, exitCode) => {
            if (this._closed) {
                callback(null, null);
                return;
            }
            if (!ok) {
                callback(null, `${command} failed (exit ${exitCode})`);
                return;
            }
            const parsed = parser(stdout);
            callback(parsed, parsed ? null : `unexpected ${command} output`);
        });
    }

    _finishAccountLoad(generation, onComplete, accountsResult, credentialsResult) {
        if (this._closed)
            return;
        if (generation === this._accountsGeneration) {
            // Newest request: apply the result (or the fallback) and run its
            // callback on both paths, so a queued action is never dropped.
            const accounts = accountsResult ? accountsResult.parsed : null;
            const credentials = credentialsResult ? credentialsResult.parsed : null;
            // Discover failures are non-fatal: the empty credential list
            // keeps the auto path working and the error surfaces in the
            // helper line and the journal.
            this._credentials = credentials ? credentials.credentials : [];
            // The store report rides with the credential list; on a discover
            // failure (or an old CLI payload) it is null and the window falls
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
            } else {
                if (!this._accountsLoaded)
                    this._accounts = [];
                this._accountsLoaded = true;
                this._accountsError = accountsResult ? accountsResult.errorMessage : null;
                if (!this._accountsErrorLogged) {
                    this._accountsErrorLogged = true;
                    logError(
                        `${this._accountsError}; keeping the current account list`,
                        accountsResult ? accountsResult.error : null);
                }
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

    // -- guided state --------------------------------------------------------

    // Rebuilds the combo entries from the discovered credentials; both the
    // Refresh button and the login poll call it after a reload.
    _populateCredentialChoices() {
        const fresh = this._credentialChoices();
        this._comboUpdating = true;
        try {
            this._credentialCombo.remove_all();
            if (fresh.length === 0) {
                // The text the applet's combo shows with no entries; the
                // combo is insensitive so the placeholder cannot be picked.
                this._credentialCombo.append_text('No credentials found');
                this._credentialCombo.set_active(-1);
            } else {
                for (const choice of fresh)
                    this._credentialCombo.append_text(choice.label);
            }
            this._credentialCombo.set_sensitive(fresh.length > 0);
        } finally {
            this._comboUpdating = false;
        }
        this._comboChoices = fresh;
        if (!fresh.some(choice => this._selectedCredential &&
                choice.credentialId === this._selectedCredential.credentialId))
            this._selectedCredential = fresh.length > 0 ? fresh[0] : null;
        if (fresh.length > 0) {
            this._credentialCombo.set_active(
                fresh.indexOf(this._selectedCredential));
        }
    }

    _onCredentialChanged() {
        if (this._comboUpdating)
            return;
        const index = this._credentialCombo.get_active();
        this._selectedCredential =
            index >= 0 && index < this._comboChoices.length
                ? this._comboChoices[index]
                : null;
    }

    // "Looked in: …" line for the no-login helper: the paths the CLI
    // checked, with the home prefix shortened.
    _storePathsMessage() {
        let text = `Looked in: ${shortenHomePath(this._store.db_path)}`;
        if (this._store.auth_json_exists)
            text += ` and ${shortenHomePath(this._store.auth_json_path)}`;
        return text;
    }

    // Recomputes the guided state in place after a reload (the Refresh
    // button, the silent reload on open, and the login poll): the login type
    // depends on whether a login is bindable, the combo must follow the fresh
    // credential list, and the helper block (message, checked paths,
    // visibility) reflects the fresh store. The optional override forces an
    // explicit helper line and visibility (the poll's "detected" message).
    _refreshGuidedState(helperOverride = null) {
        const fresh = this._credentialChoices();
        const freshAllowLogin = this._hasBindableLogin(fresh);
        this._loginRadio.set_sensitive(freshAllowLogin);
        // The reload can remove the last bindable login while the login type
        // is active: keeping it selected would submit from the disabled type,
        // so fall back to the API-key type.
        if (!freshAllowLogin && this._loginRadio.get_active())
            this._apiKeyRadio.set_active(true);
        this._populateCredentialChoices();

        const noLogin = !this._credentialsError &&
            this._credentials.length === 0 && !this._storeHasLogin();
        if (helperOverride !== null) {
            this._helperBox.show();
            this._helperLabel.set_text(helperOverride);
        } else if (this._credentialsError) {
            this._helperBox.show();
            this._helperLabel.set_text(
                'Could not read the OpenCode credential store. '
                + truncate(this._credentialsError, MAX_WARNING_CHARS));
        } else {
            if (noLogin)
                this._helperBox.show();
            else
                this._helperBox.hide();
            this._helperLabel.set_text(
                'No OpenCode login found on this machine. '
                + 'Log in below, or add an API-key account.');
        }
        // The checked paths ride under the no-login message only.
        const showStore = helperOverride === null && noLogin && !!this._store;
        if (showStore) {
            this._storeLabel.set_text(this._storePathsMessage());
            this._storeLabel.show();
        } else {
            this._storeLabel.set_text('');
            this._storeLabel.hide();
        }
        return {allowLogin: freshAllowLogin, choices: fresh};
    }

    // The applet's updateTypeState(): the active type drives the visible
    // rows, the title, the description and the confirm label.
    _updateTypeState() {
        const fromDb = this._loginRadio.get_active();
        // A type switch cancels a pending keyring-less offer: the
        // type-driven label assignment below drops the
        // 'Store in a local file' relabel too, and the offer's stale
        // explanation must not survive pointing at a now-hidden key field.
        if (this._fileFallbackOffered) {
            this._fileFallbackOffered = false;
            this._statusLabel.set_text('');
        }
        if (fromDb) {
            this._keyRow.hide();
            this._credentialRow.show();
            this._keyEntry.set_text('');
        } else {
            this._keyRow.show();
            this._credentialRow.hide();
        }
        this._window.set_title(fromDb
            ? 'Add account'
            : 'Add / replace account key');
        this._descriptionLabel.set_text(fromDb
            ? 'Registers an OpenCode login. Pick the auto binding (follows ' +
                'the active OpenCode credential) or a discovered credential.'
            : 'API-key accounts from the OpenCode console. The key is '
                + 'verified with OpenCode and is never stored by the applet.');
        this._confirmButton.set_label(fromDb
            ? 'Add account'
            : 'Add / replace key');
    }

    // Neutral/pending text plain, failure text in the theme's error color,
    // like the applet's _setStatus().
    _setStatus(text, failed) {
        this._statusLabel.set_text(text);
        const context = this._statusLabel.get_style_context();
        if (failed)
            context.add_class('error');
        else
            context.remove_class('error');
    }

    // -- login ---------------------------------------------------------------

    _onLogin() {
        // The desktop-session PATH normally misses the user's OpenCode
        // install, so resolve the binary explicitly before anything runs.
        const binary = resolveOpenCodeBinary();
        if (!binary) {
            // No script and no terminal: the login would only die with
            // "command not found", so point at the manual path instead.
            this._copyLoginCommand();
            this._setStatus('OpenCode was not found on this machine. Install '
                + 'OpenCode, or run "opencode auth login" in a terminal where '
                + 'it works (the command is on your clipboard), then press '
                + 'Refresh.', true);
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
            this._setStatus('Could not prepare the login. '
                + '"opencode auth login" is on your clipboard — paste it into '
                + 'a terminal, then press Refresh.', true);
            return;
        }
        const terminal = this._launchLoginTerminal(script);
        // Always copied: a spawned terminal can die silently (D-Bus
        // activation) and its exit status is not trustworthy, so the manual
        // command is the guaranteed fallback.
        this._copyLoginCommand();
        if (terminal) {
            this._setStatus('Terminal opened — complete the login in your '
                + 'browser. If no window appeared, the command is on your '
                + 'clipboard.', false);
        } else {
            this._setStatus('Could not open a terminal. "opencode auth login" '
                + 'is on your clipboard — paste it into a terminal, then press '
                + 'Refresh.', true);
        }
        this._startLoginPoll();
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
    // started, or null when none did. A started terminal can still die
    // silently (D-Bus activation), so the return value is never treated as
    // proof the window appeared.
    _launchLoginTerminal(script) {
        for (const candidate of loginTerminalCandidates(script)) {
            if (!GLib.find_program_in_path(candidate.binary))
                continue;
            try {
                const subprocess = new Gio.Subprocess({
                    argv: [candidate.binary, ...candidate.args],
                    flags: Gio.SubprocessFlags.NONE,
                });
                subprocess.init(null);
                // Reaping the terminal must not block the window.
                subprocess.wait_async(null, (source, result) => {
                    try {
                        source.wait_finish(result);
                    } catch (error) {
                        logError(
                            'could not wait for the login terminal', error);
                    }
                });
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
            const display = Gdk.Display.get_default();
            const clipboard = Gtk.Clipboard.get_default(display);
            clipboard.set_text('opencode auth login', -1);
        } catch (error) {
            logError('could not copy the login command', error);
        }
    }

    // Detection poll: after a login attempt, watch the credential store for a
    // credential id that was not there when the button was clicked (~5
    // minutes). It updates the window in place and stops on detection,
    // timeout, or window close.
    _startLoginPoll() {
        if (this._loginPollId)
            return; // one poll at a time
        const serial = ++this._loginPollSerial;
        const baseline = new Set(
            this._credentials.map(credential => credential.id));
        // Legacy logins never appear in the credentials list: a login landing
        // in auth.json is detected through has_login alone.
        const baselineHasLogin = this._storeHasLogin();
        this._loginPollTicks = 0;
        this._loginPollId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, LOGIN_POLL_SECONDS, () => {
                if (this._closed) {
                    this._loginPollId = 0;
                    return GLib.SOURCE_REMOVE;
                }
                this._loginPollTicks += 1;
                const lastTick = this._loginPollTicks >= LOGIN_POLL_TICKS;
                this._loadAccounts(() => {
                    if (this._closed || serial !== this._loginPollSerial)
                        return; // closed, or a newer poll replaced this one
                    const detected = this._credentials.some(
                        credential => !baseline.has(credential.id)) ||
                        (!baselineHasLogin && this._storeHasLogin());
                    if (detected) {
                        this._stopLoginPoll();
                        this._refreshGuidedState('OpenCode login detected.');
                        this._setStatus('OpenCode login detected — '
                            + 'the login can be added now.', false);
                        return;
                    }
                    if (this._storeHasLogin()) {
                        // The store already held a login when the button was
                        // clicked (for example a re-auth that keeps the same
                        // credential): nothing new will appear, and claiming
                        // "no login" would be false. The login is bindable now.
                        this._stopLoginPoll();
                        this._refreshGuidedState('An OpenCode login is available.');
                        this._setStatus('An OpenCode login is already '
                            + 'available in the store — it can be added now.', false);
                        return;
                    }
                    if (lastTick) {
                        this._stopLoginPoll();
                        this._setStatus('Still no OpenCode login detected — '
                            + 'finish the login, then press Refresh.', false);
                    }
                });
                if (lastTick)
                    this._loginPollId = 0;
                return lastTick ? GLib.SOURCE_REMOVE : GLib.SOURCE_CONTINUE;
            });
    }

    _stopLoginPoll() {
        if (this._loginPollId) {
            GLib.source_remove(this._loginPollId);
            this._loginPollId = 0;
        }
    }

    // -- refresh -------------------------------------------------------------

    _onRefresh() {
        this._setStatus('Reloading accounts and credentials…', false);
        this._loadAccounts(() => {
            if (this._closed)
                return;
            // The refresh updates this window in place; the helper block
            // (message, store paths, visibility) follows the fresh store.
            this._refreshGuidedState();
            if (this._credentialsError) {
                this._setStatus(
                    'Could not reload the OpenCode credential store.', true);
            } else if (this._credentials.length === 0 &&
                    !this._storeHasLogin()) {
                this._setStatus('No new credentials found yet.', false);
            } else {
                this._setStatus('Credentials reloaded.', false);
            }
        });
    }

    // -- submit --------------------------------------------------------------

    _onSubmit() {
        const accountId = this._idEntry.get_text().trim();
        const label = this._labelEntry.get_text().trim();
        const fromDb = this._loginRadio.get_active();
        // A pending keyring-less offer turns this submit into the file
        // backend retry: same command, '--store file' instead of 'auto' (the
        // CLI's deliberate explicit opt-in). Captured before the offer flag
        // is consumed below.
        const useFileStore = !fromDb && this._fileFallbackOffered;
        const key = fromDb ? '' : this._keyEntry.get_text();
        const error = accountFormError(accountId, key, fromDb);
        if (error) {
            this._setStatus(error, true);
            return;
        }
        let args;
        let pendingText;
        if (fromDb) {
            // The CLI registers an OpenCode login; no key, no stdin. Without
            // --credential the account follows the active OpenCode credential
            // (the auto entry).
            // Backstop only: the login type is disabled when no credential is
            // bindable, so this submit cannot normally run. The auto entry
            // (credentialId null) needs a login in the store to resolve — a
            // listed credential or the legacy auth.json login — so it counts
            // as missing when the store holds neither.
            if (!this._selectedCredential ||
                    (this._selectedCredential.credentialId === null &&
                        this._credentials.length === 0 &&
                        !this._storeHasLogin())) {
                this._setStatus('No OpenCode login found — use '
                    + '"Log in with OpenCode…" or the API key type.', true);
                return;
            }
            args = ['account', 'add', accountId, '--from-db'];
            if (label)
                args.push('--label', label);
            if (this._selectedCredential.credentialId)
                args.push(
                    '--credential', this._selectedCredential.credentialId);
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
        // The offer is consumed by this run: the retry must take one click,
        // and any later failure goes back to the normal branch.
        this._fileFallbackOffered = false;
        this._confirmButton.set_sensitive(false);
        this._setStatus(pendingText, false);
        this._runCommand(args, fromDb ? null : key, (ok, stdout, stderr) => {
            if (this._closed)
                return;
            if (ok)
                this._loadAccounts();
            // The CLI's keyring-or-error contract is deliberate; the window
            // only offers the file backend when the failure names the
            // keyring. stderr first, stdout as the fallback — the same detail
            // _failureMessage picks.
            const failedOutput = stderr || stdout || '';
            const keyringFailure = !ok && !fromDb && !useFileStore
                ? failedOutput : null;
            const keyringMissing = keyringFailure !== null &&
                failedOutput.includes(SECRET_TOOL_UNAVAILABLE_MARKER);
            const keyringStoreFailed = keyringFailure !== null &&
                !keyringMissing &&
                failedOutput.includes(SECRET_TOOL_STORE_FAILED_MARKER);
            if (keyringMissing || keyringStoreFailed) {
                // Two-step offer: keep the typed key, explain without the
                // CLI's terminal-level wording, and let the next confirm click
                // retry with '--store file'. No close timer — the user
                // decides.
                this._fileFallbackOffered = true;
                this._confirmButton.set_label('Store in a local file');
                this._setStatus(keyringStoreFailed
                    ? 'The system keyring is unavailable in this session (no '
                        + 'keyring service answered). Press "Store in a local '
                        + 'file" to keep the key in a private file that only '
                        + 'your user can read.'
                    : 'The system keyring (libsecret-tools) is not installed. '
                        + 'Press "Store in a local file" to keep the key in a '
                        + 'private file that only your user can read — or '
                        + 'install libsecret-tools and try again.', true);
                this._confirmButton.set_sensitive(true);
                return;
            }
            // The key never stays in the entry beyond the command.
            // Exception: a missing-keyring failure keeps it, because the
            // command did not complete and the retry must not ask the user to
            // paste it again.
            this._keyEntry.set_text('');
            // A completed file-store retry (success or failure) ends the
            // offer: the confirm button goes back to the API-key type's
            // label, exactly as updateTypeState assigns it.
            if (useFileStore)
                this._confirmButton.set_label('Add / replace key');
            if (ok) {
                const summary = stripToolToken(
                    [stdout.trim(), stderr.trim()].filter(Boolean).join(' '));
                this._setStatus(
                    summary || `Account '${accountId}' updated.`, false);
                this._closeTimerId = GLib.timeout_add(
                    GLib.PRIORITY_DEFAULT, 1200, () => {
                        this._closeTimerId = 0;
                        this._close();
                        return GLib.SOURCE_REMOVE;
                    });
            } else {
                this._setStatus(this._failureMessage(
                    fromDb ? 'could not add the OpenCode login account'
                        : 'could not update the account',
                    stderr, stdout), true);
                this._confirmButton.set_sensitive(true);
            }
        });
    }

    _failureMessage(fallback, stderr, stdout) {
        return formatFailureDetail(stderr || stdout) || fallback;
    }

    // Runs ocgo without a shell. Another difference from the applet: GIO
    // rather than Util.spawnCommandLineAsyncIO, because imports.ui.* only
    // exists inside the Cinnamon shell.
    _runCommand(args, stdinText, callback) {
        const binary = this._ocgoPath;
        if (!binary) {
            callback(false, '', "The meter's helper is not installed — "
                + 're-run the installer, then restart Cinnamon.', null);
            return;
        }
        let subprocess = null;
        try {
            subprocess = new Gio.Subprocess({
                argv: [binary, ...args],
                flags: Gio.SubprocessFlags.STDOUT_PIPE |
                    Gio.SubprocessFlags.STDERR_PIPE |
                    Gio.SubprocessFlags.STDIN_PIPE,
            });
            subprocess.init(null);
        } catch (error) {
            callback(false, '',
                `could not start the meter helper: ${error.message ?? error}`,
                null);
            return;
        }
        // argv array only; when stdinText is set it travels through the stdin
        // pipe (communicate_utf8_async writes it), never through argv or the
        // journal.
        subprocess.communicate_utf8_async(
            stdinText === null ? null : `${stdinText}\n`, null,
            (source, result) => {
                let ok = false;
                let stdout = '';
                let stderr = '';
                let exitCode = null;
                try {
                    const [, out, err] = source.communicate_utf8_finish(result);
                    ok = source.get_successful();
                    stdout = out || '';
                    stderr = err || '';
                    exitCode = source.get_exit_status();
                } catch (error) {
                    const detail = error.message ?? error;
                    callback(false, '',
                        `could not run the meter helper: ${detail}`, null);
                    return;
                }
                callback(ok, stdout, stderr, exitCode);
            });
    }
}

function main() {
    Gtk.init(null);
    const window = new AccountsWindow(ocgoPathFromArgv(ARGV));
    window.open();
    Gtk.main();
    return 0;
}

System.exit(main());
