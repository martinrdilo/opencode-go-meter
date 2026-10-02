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
        window.add(page);
    }
}
