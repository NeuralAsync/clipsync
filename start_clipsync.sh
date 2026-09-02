#!/bin/bash
# Manually (re)starts clipsync via launchd — use this after quitting from the
# tray menu, or if it didn't start automatically. Unlike double-clicking a
# .app bundle, this goes straight through launchd and doesn't hit the
# ControlCenter XPC bug that stops the tray icon from showing.
launchctl kickstart -k "gui/$(id -u)/com.clipsync.app"
echo "clipsync (re)started."
