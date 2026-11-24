import pytest

from jarvis.skills import browser_control


def test_browser_rejects_non_http_url():
    with pytest.raises(ValueError, match="Only complete http"):
        browser_control.open_url("file:///C:/Windows/win.ini")


def test_browser_rejects_empty_url():
    with pytest.raises(ValueError, match="Only complete http"):
        browser_control.open_url("")

from jarvis.skills.browser_control import press_key


def test_browser_rejects_unapproved_keyboard_shortcut():
    with pytest.raises(ValueError, match="safe key allowlist"):
        press_key("Alt+F4")


def test_browser_rejects_unknown_keyboard_key():
    with pytest.raises(ValueError, match="safe key allowlist"):
        press_key("LaunchAnything")
