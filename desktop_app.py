"""Portable Windows entry point. Imports heavy UI libraries only in child modes."""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

VERSION = "0.1.0-preview"


def self_check(destination: str) -> int:
    """Exercise bundled imports/assets without reading or capturing the desktop."""
    from core import config
    from persona import render
    from persona.loader import load
    from settings_ui.model import SettingsModel
    from settings_ui import ui_render
    from winapi import win32

    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    cfg = config.load()
    persona = load(cfg.persona)
    rendered = []
    for cid in persona.characters:
        for scene in ("unlock_scold", "side_peek", "overtime_care"):
            text = persona.lines_for("zh", cid)[scene][0]
            image = render.render_flash(persona, scene, text, "zh", "#4F3F3B", cid, 1080, 96)
            if not image.getbbox():
                raise ValueError(f"Empty image: {cid}/{scene}")
            rendered.append(f"{cid}/{scene}")
    preview_path = output.with_suffix(".png")
    render.preview_sheet(cfg, persona, 1080, 96).save(preview_path)
    # Import tkinter and native bindings, but create no native windows.
    import settings_ui.app
    import main
    model = SettingsModel()
    assert not model.persona_error
    assert ui_render.W > 0 and win32.IS_WINDOWS
    result = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "config_errors": cfg.errors, "characters": list(persona.characters),
              "rendered": rendered, "preview": preview_path.name,
              "desktop_captured": False, "native_windows_created": False,
              "passed": not cfg.errors}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--self-check"]:
        if len(args) != 2:
            raise ValueError("--self-check requires a JSON destination")
        return self_check(args[1])
    if args[:1] == ["--settings"]:
        from settings_ui.app import main as settings_main
        return settings_main(args[1:]) or 0
    if args[:1] == ["--quit"]:
        from winapi import ipc
        from winapi.win32 import WM_CLOSE, user32
        hwnd = ipc.sentinel_hwnd()
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return 0
    # The sentinel uses the same entry point for its two independent child modes.
    if args[:1] == ["-m"]:
        if args[1:2] == ["settings_ui.app"]:
            from settings_ui.app import main as child_main
        elif args[1:2] == ["persona.render"]:
            from persona.render import main as child_main
        else:
            raise ValueError("Unsupported child mode")
        return child_main(args[2:]) or 0
    from main import main as sentinel_main
    return sentinel_main(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A windowless executable must still leave a useful diagnostic.
        root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        logs = root / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "launcher-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        if "--self-check" in sys.argv:
            raise
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "启动失败，请查看 logs/launcher-error.log。", "大水理论最严厉的母亲", 0x10)
        sys.exit(1)
