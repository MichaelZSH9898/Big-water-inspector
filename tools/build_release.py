"""Build an allowlisted source archive and an offline Windows portable bundle."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-preview"
PROJECT_NAME = "大水理论最严厉的母亲"
# GitHub 会删掉 Release 附件名里的中文等非 ASCII 字符，所以附件文件名用英文；压缩包里的文件夹和程序仍用中文名。
ASSET_SLUG = "Big-water-inspector"
SOURCE_DIRS = {"assets", "core", "docs", "overlay", "persona", "settings_ui", "signals", "sim", "tests", "tools", "winapi"}
SOURCE_FILES = {"main.py", "desktop_app.py", "config.toml", "requirements.txt", "README.md", "README.en.md",
                "PLAN.md", "DECISIONS.md", "LICENSE", "ASSET_NOTICES.md", "CONTRIBUTING.md", "CHANGELOG.md", ".gitignore",
                "启动督察员.bat", "打开设置.bat", "演示模式.bat", "重启督察员.bat"}
SKIP_PARTS = {"__pycache__", "reports", "cache", "_to_delete", "media-build"}


def source_files():
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if rel.parts[0] not in SOURCE_DIRS and str(rel) not in SOURCE_FILES:
            continue
        if any(part in SKIP_PARTS for part in rel.parts) or p.suffix in {".pyc", ".pyo", ".log"}:
            continue
        yield p


def zip_tree(folder, output):
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p,Path(folder.name)/p.relative_to(folder))


def third_party(target):
    dest=target/"third_party"
    dest.mkdir(exist_ok=True)
    # The portable bundle redistributes Python, Pillow and PyInstaller's bootloader.
    python_license=Path(sys.base_prefix)/"LICENSE.txt"
    if not python_license.exists():
        raise FileNotFoundError(python_license)
    shutil.copy2(python_license,dest/"Python-LICENSE.txt")
    for package in ("Pillow","pyinstaller"):
        dist=importlib.metadata.distribution(package)
        found=[]
        for item in dist.files or []:
            if any(key in item.name.lower() for key in ("license","copying")):
                p=Path(dist.locate_file(item))
                if p.is_file():
                    name=f"{package}-"+str(item).replace("/","_").replace("\\","_")
                    shutil.copy2(p,dest/name)
                    found.append(name)
        if not found:
            raise RuntimeError(f"Missing license for {package}")
    (dest/"VERSIONS.txt").write_text(f"Python {sys.version}\nPillow {importlib.metadata.version('Pillow')}\n"
        f"PyInstaller {importlib.metadata.version('pyinstaller')} (bootloader exception applies)\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-only",action="store_true")
    a=parser.parse_args()
    out=ROOT/"release"
    out.mkdir(exist_ok=True)
    source_zip=out/f"{ASSET_SLUG}-{VERSION}-source.zip"
    with zipfile.ZipFile(source_zip,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in source_files():
            z.write(p,Path(PROJECT_NAME)/p.relative_to(ROOT))
    products=[source_zip]
    if not a.source_only:
        if os.name!="nt":
            raise RuntimeError("Build the Windows bundle on Windows.")
        build=ROOT/"build"/"portable"
        build.mkdir(parents=True,exist_ok=True)
        env=os.environ.copy()
        env["PYINSTALLER_CONFIG_DIR"]=str(build/"pyinstaller-cache")
        # PyInstaller can replace its prior output directory; constrain that target.
        bundle_target=(out/PROJECT_NAME).resolve()
        if not bundle_target.is_relative_to(ROOT.resolve()) or bundle_target.name!=PROJECT_NAME:
            raise ValueError("Build output escaped the project directory")
        cmd=[sys.executable,"-m","PyInstaller","--noconfirm","--onedir","--windowed","--noupx",
             "--contents-directory",".","--name",PROJECT_NAME,"--distpath",str(out),
             "--workpath",str(build/"work"),"--specpath",str(build),
             "--icon",str(ROOT/"assets/tray/tea_3.ico"),
             "--add-data",f"{ROOT/'config.toml'};.",
             "--add-data",f"{ROOT/'assets/tray'};assets/tray",
             "--add-data",f"{ROOT/'persona/default_mom'};persona/default_mom",
             "--exclude-module","numpy","--exclude-module","matplotlib",
             "--exclude-module","psutil",str(ROOT/"desktop_app.py")]
        subprocess.run(cmd,cwd=ROOT,env=env,check=True)
        bundle=out/PROJECT_NAME
        for name in ("LICENSE","ASSET_NOTICES.md"):
            shutil.copy2(ROOT/name,bundle/name)
        # Rebuild from shipped defaults, never copy a user's rendered cache.
        from core import config
        from persona import render
        from persona.loader import load
        persona=load("default_mom")
        for lang in ("zh","en"):
            cfg=config.load(overrides={"general":{"language":lang}})
            render.ensure(cfg,[(1080,96),(1440,144),(1800,192)],persona,
                          cache_dir=str(bundle/"persona/cache"),log=None)
        for name,args in (("1-先看演示.cmd","--try"),("2-打开设置.cmd","--settings"),("3-退出程序.cmd","--quit")):
            (bundle/name).write_text('@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\nstart "" "%~dp0大水理论最严厉的母亲.exe" '+args+'\n',encoding="utf-8")
        shutil.copy2(ROOT/"docs/PORTABLE_README.txt",bundle/"先读我.txt")
        third_party(bundle)
        portable_zip=out/f"{ASSET_SLUG}-{VERSION}-Windows-x64.zip"
        zip_tree(bundle,portable_zip)
        products.append(portable_zip)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob(f"{ASSET_SLUG}-{VERSION}-*.zip"))}
    (out/"SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n,h in hashes.items()),encoding="utf-8")
    print(json.dumps({"files":[str(p) for p in products],"sha256":hashes},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
