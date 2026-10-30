# SPDX-License-Identifier: GPL-3.0-or-later
"""History window: recent transcripts, searchable, one click to copy."""

import time

from gi.repository import Adw, Gdk, GObject, Gtk

from .transcripts import matches


class HistoryWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Heard History", default_width=720, default_height=720)
        self.app = app

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="Recent Dictations")
        header.set_title_widget(self.title)
        self.search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Search (Ctrl+F)")
        header.pack_start(self.search_btn)
        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Settings")
        settings_btn.connect("clicked", lambda *_: app.open_settings())
        header.pack_end(settings_btn)
        clear_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Clear history")
        clear_btn.connect("clicked", lambda *_: self.confirm_clear())
        header.pack_end(clear_btn)
        view.add_top_bar(header)

        self.search = Gtk.SearchEntry(placeholder_text="Search transcripts", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())
        bar = Gtk.SearchBar(child=Adw.Clamp(child=self.search, maximum_size=640))
        bar.connect_entry(self.search)
        bar.set_key_capture_widget(self)
        self.search_btn.bind_property("active", bar, "search-mode-enabled",
                                      GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        view.add_top_bar(bar)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                valign=Gtk.Align.START)
        self.list.set_filter_func(lambda row: matches(row.entry, self.search.get_text()))
        self.list.connect("row-activated", lambda _l, row: self.copy(row.entry))
        clamp = Adw.Clamp(child=self.list, maximum_size=640, margin_top=18, margin_bottom=18,
                          margin_start=12, margin_end=12)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=clamp)
        self.empty = Adw.StatusPage(icon_name="io.github.jksnetwork.Heard-symbolic", title="Nothing dictated yet",
                                    description="Press the dictation shortcut, speak, and press it again. "
                                                "Your transcripts show up here.")
        self.stack = Gtk.Stack()
        self.stack.add_named(scroller, "list")
        self.stack.add_named(self.empty, "empty")
        self.toasts = Adw.ToastOverlay(child=self.stack)
        view.set_content(self.toasts)
        self.set_content(view)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.reload()

    def on_key(self, _ctl, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval == Gdk.KEY_f:
            self.search_btn.set_active(True)
        elif keyval == Gdk.KEY_Escape and not self.search_btn.get_active() or (ctrl and keyval == Gdk.KEY_w):
            self.close()
        else:
            return False
        return True

    def reload(self):
        self.list.remove_all()
        entries = self.app.transcripts.load()
        self.stack.set_visible_child_name("list" if entries else "empty")
        limit = self.app.config.history_limit
        self.title.set_subtitle(f"{len(entries)} kept (up to {limit})  ·  Click one to copy it" if limit
                                else "History is turned off in Settings")
        for entry in entries:
            self.list.append(self.row(entry))

    def row(self, entry):
        row = Gtk.ListBoxRow(activatable=True)
        row.entry = entry
        box = Gtk.Box(spacing=12, margin_top=10, margin_bottom=10, margin_start=14, margin_end=8)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        texts.append(Gtk.Label(label=entry["text"], wrap=True, xalign=0, natural_wrap_mode=Gtk.NaturalWrapMode.WORD,
                               lines=6, ellipsize=3))
        texts.append(Gtk.Label(label=details(entry), xalign=0, css_classes=["caption", "dim-label"]))
        box.append(texts)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy", valign=Gtk.Align.CENTER,
                          css_classes=["flat"])
        copy.connect("clicked", lambda *_: self.copy(entry))
        box.append(copy)
        remove = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Remove", valign=Gtk.Align.CENTER,
                            css_classes=["flat"])
        remove.connect("clicked", lambda *_: self.remove(row))
        box.append(remove)
        row.set_child(box)
        return row

    def copy(self, entry):
        # this window has focus, so GTK can set the clipboard itself
        self.get_clipboard().set(entry["text"])
        self.toasts.add_toast(Adw.Toast(title="Copied", timeout=2))

    def remove(self, row):
        self.app.transcripts.remove(row.entry)
        self.list.remove(row)
        if self.list.get_first_child() is None:
            self.stack.set_visible_child_name("empty")

    def confirm_clear(self):
        dialog = Adw.AlertDialog(heading="Clear history?", body="Every saved transcript will be deleted.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(dlg, res):
            if dlg.choose_finish(res) == "clear":
                self.app.transcripts.clear()
                self.reload()
        dialog.choose(self, None, done)


def details(entry):
    parts = [time.strftime("%b %d, %H:%M", time.localtime(entry.get("time", 0)))]
    if entry.get("seconds"):
        parts.append(f"{entry['seconds']:.1f} s of speech")
    if entry.get("elapsed"):
        parts.append(f"transcribed in {entry['elapsed']:.1f} s")
    if entry.get("method"):
        parts.append(entry["method"])
    return "  ·  ".join(parts)
