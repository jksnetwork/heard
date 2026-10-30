// SPDX-License-Identifier: GPL-3.0-or-later
// Heard helper: runs inside GNOME Shell and offers the Heard app what a
// regular Wayland client can't do itself:
//   * typing text into whichever window has focus (a virtual keyboard)
//   * pasting without having keyboard focus (clipboard + paste keystroke)
//   * a small always-on-top "listening" pill that never takes focus
//   * raising Heard's own windows when they're opened from a hotkey

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.jksnetwork.Heard.Shell';
const OBJECT_PATH = '/io/github/jksnetwork/Heard/Shell';
const API_VERSION = 1;

const IFACE = `
<node>
  <interface name="io.github.jksnetwork.Heard.Shell">
    <method name="SetState">
      <arg type="s" name="state" direction="in"/>
      <arg type="s" name="text" direction="in"/>
    </method>
    <method name="SetLevel">
      <arg type="d" name="level" direction="in"/>
    </method>
    <signal name="IndicatorClicked">
      <arg type="s" name="action"/>
    </signal>
    <method name="TypeText">
      <arg type="s" name="text" direction="in"/>
      <arg type="s" name="mode" direction="in"/>
      <arg type="b" name="enter" direction="in"/>
      <arg type="s" name="method" direction="out"/>
    </method>
    <method name="SetClipboardText">
      <arg type="s" name="text" direction="in"/>
    </method>
    <method name="FocusedApp">
      <arg type="s" name="wmClass" direction="out"/>
      <arg type="s" name="title" direction="out"/>
    </method>
    <method name="ManageWindow">
      <arg type="s" name="title" direction="in"/>
    </method>
    <property name="Version" type="u" access="read"/>
  </interface>
</node>`;

const BARS = 5;
const CHUNK = 24; // characters typed per main-loop turn
// window classes where Ctrl+V doesn't paste but Ctrl+Shift+V does
const TERMINALS = ['terminal', 'kgx', 'console', 'ptyxis', 'kitty', 'alacritty', 'foot', 'wezterm',
    'tilix', 'konsole', 'xterm', 'terminator', 'ghostty', 'blackbox', 'urxvt'];
const HELD_MODIFIERS = Clutter.ModifierType.SHIFT_MASK | Clutter.ModifierType.CONTROL_MASK |
    Clutter.ModifierType.MOD1_MASK | Clutter.ModifierType.SUPER_MASK | Clutter.ModifierType.MOD4_MASK;

function sleep(ms) {
    return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
        resolve();
        return GLib.SOURCE_REMOVE;
    }));
}

function isTerminal(win) {
    const cls = (win?.get_wm_class() ?? '').toLowerCase();
    return TERMINALS.some(t => cls.includes(t));
}

/** The pill shown at the top of the screen while listening or transcribing. */
class Indicator {
    constructor(onClick) {
        this._onClick = onClick;
        this._box = new St.BoxLayout({style_class: 'heard-pill', reactive: true, visible: false});
        this._dot = new St.Widget({style_class: 'heard-dot', y_align: Clutter.ActorAlign.CENTER});
        this._label = new St.Label({style_class: 'heard-label', y_align: Clutter.ActorAlign.CENTER});
        this._meter = new St.BoxLayout({style_class: 'heard-meter', y_align: Clutter.ActorAlign.CENTER});
        this._bars = [];
        for (let i = 0; i < BARS; i++) {
            const bar = new St.Widget({style_class: 'heard-bar', y_align: Clutter.ActorAlign.CENTER});
            this._meter.add_child(bar);
            this._bars.push(bar);
        }
        this._stop = new St.Button({style_class: 'heard-button', can_focus: false,
            child: new St.Icon({icon_name: 'media-playback-stop-symbolic', icon_size: 14})});
        this._stop.connect('clicked', () => this._onClick('stop'));
        // stop, type and press Enter (sends a chat prompt)
        this._send = new St.Button({style_class: 'heard-button', can_focus: false,
            child: new St.Icon({icon_name: 'mail-send-symbolic', icon_size: 14})});
        this._send.connect('clicked', () => this._onClick('send'));
        this._cancel = new St.Button({style_class: 'heard-button', can_focus: false,
            child: new St.Icon({icon_name: 'window-close-symbolic', icon_size: 14})});
        this._cancel.connect('clicked', () => this._onClick('cancel'));
        for (const child of [this._dot, this._label, this._meter, this._stop, this._send, this._cancel])
            this._box.add_child(child);
        Main.layoutManager.addTopChrome(this._box);
        this._state = 'hidden';
        this._started = 0;
        this._tick = 0;
        this._pulse = 0;
        this._box.connect('notify::width', () => this._place());
    }

    destroy() {
        this._stopTimers();
        Main.layoutManager.removeChrome(this._box);
        this._box.destroy();
    }

    _stopTimers() {
        if (this._tick)
            GLib.source_remove(this._tick);
        if (this._pulse)
            GLib.source_remove(this._pulse);
        this._tick = this._pulse = 0;
        this._dot.remove_all_transitions();
        this._dot.opacity = 255;
    }

    _place() {
        // the monitor you're working on: where the focused window is, else the primary one
        const win = global.display.focus_window;
        const index = win ? win.get_monitor() : Main.layoutManager.primaryIndex;
        const m = Main.layoutManager.monitors[index] ?? Main.layoutManager.primaryMonitor;
        const top = index === Main.layoutManager.primaryIndex ? Main.panel.height : 0;
        this._box.set_position(Math.round(m.x + (m.width - this._box.width) / 2), m.y + top + 10);
    }

    setState(state, text) {
        const was = this._state;
        this._state = state;
        if (state === 'hidden') {
            this._stopTimers();
            this._box.ease({opacity: 0, duration: 150, onComplete: () => {
                if (this._state === 'hidden')
                    this._box.hide();
            }});
            return;
        }
        this._dot.style_class = `heard-dot heard-${state}`;
        const recording = state === 'recording';
        this._meter.visible = this._stop.visible = this._send.visible = recording;
        this._cancel.visible = state !== 'busy';
        if (recording && was !== 'recording') {
            this._started = GLib.get_monotonic_time();
            this.setLevel(0);
        }
        this._text = text;
        this._updateLabel();
        this._stopTimers();
        if (recording) {
            this._tick = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
                this._updateLabel();
                return GLib.SOURCE_CONTINUE;
            });
        }
        this._pulseDot();
        if (!this._box.visible) {
            this._box.opacity = 0;
            this._box.show();
        }
        this._place();
        this._box.ease({opacity: 255, duration: 120});
    }

    _pulseDot() {
        const fade = () => {
            this._dot.ease({opacity: this._dot.opacity > 128 ? 70 : 255, duration: 600,
                mode: Clutter.AnimationMode.EASE_IN_OUT_SINE});
            return GLib.SOURCE_CONTINUE;
        };
        fade();
        this._pulse = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 650, fade);
    }

    _updateLabel() {
        if (this._state === 'recording' && !this._text) {
            const secs = Math.floor((GLib.get_monotonic_time() - this._started) / 1e6);
            this._label.text = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
        } else {
            this._label.text = this._text ?? '';
        }
    }

    setLevel(level) {
        const lit = Math.ceil(Math.max(0, Math.min(1, level)) * BARS);
        this._bars.forEach((bar, i) => {
            // a little shape: middle bars reach higher
            const peak = [6, 10, 14, 10, 6][i];
            bar.height = i < lit ? peak : 3;
            bar.opacity = i < lit ? 255 : 90;
        });
    }
}

class Keyboard {
    constructor() {
        const seat = Clutter.get_default_backend().get_default_seat();
        this._device = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
    }

    _key(keyval, pressed) {
        this._device.notify_keyval(GLib.get_monotonic_time(), keyval,
            pressed ? Clutter.KeyState.PRESSED : Clutter.KeyState.RELEASED);
    }

    tap(keyval) {
        this._key(keyval, true);
        this._key(keyval, false);
    }

    combo(modifiers, keyval) {
        modifiers.forEach(m => this._key(m, true));
        this.tap(keyval);
        [...modifiers].reverse().forEach(m => this._key(m, false));
    }

    async type(text) {
        const chars = [...text];
        for (let i = 0; i < chars.length; i += CHUNK) {
            for (const ch of chars.slice(i, i + CHUNK)) {
                const keyval = ch === '\n' ? Clutter.KEY_Return : Clutter.unicode_to_keysym(ch.codePointAt(0));
                this.tap(keyval);
            }
            await sleep(4);
        }
    }

    /** Wait until the user lets go of the shortcut's modifiers, or they'd change what we type. */
    async released(timeoutMs = 1500) {
        const until = GLib.get_monotonic_time() + timeoutMs * 1000;
        while (GLib.get_monotonic_time() < until) {
            const [, , mods] = global.get_pointer();
            if ((mods & HELD_MODIFIERS) === 0)
                return;
            await sleep(25);
        }
    }
}

export default class HeardExtension extends Extension {
    enable() {
        this._indicator = new Indicator(action =>
            this._dbus?.emit_signal('IndicatorClicked', new GLib.Variant('(s)', [action])));
        this._keyboard = new Keyboard();
        this._focusRules = new Map(); // title -> signal handler for window-created
        this._createdId = global.display.connect('window-created', (_d, win) => this._onWindowCreated(win));
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, BUS_NAME,
            Gio.BusNameOwnerFlags.NONE, null, null);
    }

    disable() {
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
        if (this._createdId) {
            global.display.disconnect(this._createdId);
            this._createdId = 0;
        }
        this._indicator?.destroy();
        this._indicator = null;
        this._keyboard = null;
        this._focusRules = null;
    }

    get Version() {
        return API_VERSION;
    }

    SetState(state, text) {
        this._indicator.setState(state, text);
    }

    SetLevel(level) {
        this._indicator.setLevel(level);
    }

    SetClipboardText(text) {
        St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
    }

    FocusedApp() {
        const win = global.display.focus_window;
        return [win?.get_wm_class() ?? '', win?.get_title() ?? ''];
    }

    TypeTextAsync([text, mode, enter], invocation) {
        this._typeText(text, mode, enter)
            .then(method => invocation.return_value(new GLib.Variant('(s)', [method])))
            .catch(e => {
                logError(e, 'heard');
                invocation.return_error_literal(Gio.DBusError, Gio.DBusError.FAILED, String(e?.message ?? e));
            });
    }

    async _typeText(text, mode, enter) {
        await this._keyboard.released();
        let method;
        if (mode === 'paste') {
            St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
            await sleep(30); // let the clipboard owner change reach the app first
            const ctrl = Clutter.KEY_Control_L, shift = Clutter.KEY_Shift_L;
            const win = global.display.focus_window;
            this._keyboard.combo(isTerminal(win) ? [ctrl, shift] : [ctrl], Clutter.KEY_v);
            method = 'pasted';
        } else {
            await this._keyboard.type(text);
            method = 'typed';
        }
        if (enter) {
            await sleep(30);
            this._keyboard.tap(Clutter.KEY_Return);
        }
        return method;
    }

    // windows opened from a hotkey carry no activation token, so mutter would
    // only show "… is ready"; raise them ourselves
    ManageWindow(title) {
        const existing = global.get_window_actors().find(a => a.meta_window.get_title() === title);
        if (existing)
            Main.activateWindow(existing.meta_window);
        else
            this._focusRules.set(title, true);
    }

    _onWindowCreated(win) {
        const check = () => {
            if (!this._focusRules?.has(win.get_title()))
                return false;
            this._focusRules.delete(win.get_title());
            const id = win.connect('shown', () => {
                win.disconnect(id);
                Main.activateWindow(win);
            });
            return true;
        };
        if (check())
            return;
        const id = win.connect('notify::title', () => {
            if (check())
                win.disconnect(id);
        });
        win.connect('unmanaged', () => {
            try {
                win.disconnect(id);
            } catch {}
        });
    }
}
