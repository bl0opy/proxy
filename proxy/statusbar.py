import os
import subprocess
from pathlib import Path
from typing import Callable

import AppKit
import objc

from . import mac
from .hotkey import listen_access, request_listen_access

LOG = Path.home() / "Library/Logs/Proxy/proxy.log"
RESTART_STATUS = 75
PRIVACY = "x-apple.systempreferences:com.apple.preference.security?Privacy_"


def symbol(name: str):
    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "Proxy")
    image.setTemplate_(True)
    return image


def missing_permissions() -> list[str]:
    missing = []
    if not listen_access():
        missing.append("Input Monitoring")
    if not mac.accessibility_trusted():
        missing.append("Accessibility")
    return missing


class MenuTarget(AppKit.NSObject):
    def initWithBar_(self, bar):
        self = objc.super(MenuTarget, self).init()
        if self is not None:
            self.bar = bar
        return self

    def toggleDryRun_(self, sender):
        self.bar.toggle_dry_run()

    def openLog_(self, sender):
        subprocess.run(["open", "-a", "Console", str(LOG)])

    def grantPermissions_(self, sender):
        mac.request_accessibility()
        request_listen_access()
        pane = "ListenEvent" if not listen_access() else "Accessibility"
        AppKit.NSWorkspace.sharedWorkspace().openURL_(AppKit.NSURL.URLWithString_(PRIVACY + pane))

    def restart_(self, sender):
        os._exit(RESTART_STATUS)

    def menuWillOpen_(self, menu):
        self.bar.refresh()


class StatusBar:
    def __init__(self, key_label: str, get_dry_run: Callable[[], bool], set_dry_run: Callable[[bool], None]):
        self._get_dry_run, self._set_dry_run = get_dry_run, set_dry_run
        self._target = MenuTarget.alloc().initWithBar_(self)
        self._item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self._item.button().setImage_(symbol("waveform"))

        menu = AppKit.NSMenu.alloc().init()
        menu.setDelegate_(self._target)
        menu.setAutoenablesItems_(False)
        self._title = self._add(menu, f"Proxy — hold {key_label} to talk", None)
        self._status = self._add(menu, "", None)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._dry = self._add(menu, "Dry run (plan only)", "toggleDryRun:")
        self._grant = self._add(menu, "Grant permissions…", "grantPermissions:")
        self._add(menu, "Open log", "openLog:")
        self._add(menu, "Restart Proxy", "restart:")
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        quit_item = menu.addItemWithTitle_action_keyEquivalent_("Quit Proxy", "terminate:", "q")
        quit_item.setTarget_(AppKit.NSApp)
        self._item.setMenu_(menu)
        self.refresh()

    def _add(self, menu, title: str, action: str | None):
        item = menu.addItemWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            item.setTarget_(self._target)
        else:
            item.setEnabled_(False)
        return item

    def refresh(self):
        missing = missing_permissions()
        self._status.setTitle_(f"Needs {', '.join(missing)}" if missing else "Ready")
        self._grant.setHidden_(not missing)
        self._dry.setState_(AppKit.NSControlStateValueOn if self._get_dry_run() else AppKit.NSControlStateValueOff)

    def toggle_dry_run(self):
        self._set_dry_run(not self._get_dry_run())
        self.refresh()

    def listening(self, on: bool):
        self._item.button().setImage_(symbol("waveform.circle.fill" if on else "waveform"))
