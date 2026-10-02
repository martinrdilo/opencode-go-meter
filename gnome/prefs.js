// Preferences for OpenCode Go Meter: ocgo path and refresh interval.

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

export default class OpenCodeGoMeterPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

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

        page.add(group);
        window.add(page);
    }
}
