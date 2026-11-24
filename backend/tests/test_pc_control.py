from pathlib import Path

import pytest

from jarvis.skills import pc_control


def test_app_alias_allowlist_rejects_arbitrary_command():
    with pytest.raises(ValueError, match="not in the approved launch list"):
        pc_control.launch_app("powershell")


def test_safe_user_path_rejects_outside_home():
    with pytest.raises(ValueError, match="Path must stay inside"):
        pc_control._safe_user_path(r"C:\Windows\System32")


def test_safe_user_path_accepts_project_root():
    project = Path(__file__).resolve().parents[2]
    assert pc_control._safe_user_path(str(project)) == project.resolve()


def test_screen_click_rejects_out_of_bounds(monkeypatch):
    class FakePyAutoGUI:
        FAILSAFE = True
        @staticmethod
        def size():
            return (1920, 1080)
    import sys
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI)
    with pytest.raises(ValueError, match="Coordinates must be within"):
        pc_control.click_desktop(1920, 1080)


def test_text_entry_length_is_bounded():
    with pytest.raises(ValueError, match="between 1 and 2000"):
        pc_control.type_desktop_text("x" * 2001)
