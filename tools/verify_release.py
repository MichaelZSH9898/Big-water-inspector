"""Verify release contents and execute the unpacked bundle without desktop UI."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from PIL import Image
from tools.build_release import PROJECT_NAME, VERSION

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/verification"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    missing=[]
    checked=0
    for p in [ROOT/"README.md",ROOT/"README.en.md",ROOT/"CONTRIBUTING.md",ROOT/"ASSET_NOTICES.md"]+list((ROOT/"docs").glob("*.md")):
        for target in re.findall(r"\]\(([^)]+)\)",p.read_text(encoding="utf-8-sig")):
            if re.match(r"[a-z]+://",target) or target.startswith("#"):
                continue
            checked+=1
            if not (p.parent/target.split("#")[0]).exists():
                missing.append(f"{p.relative_to(ROOT)} -> {target}")
    assert not missing,missing
    releases=ROOT/"release"
    archives={}
    for suffix in ("源码","Windows-x64"):
        path=releases/f"{PROJECT_NAME}-{VERSION}-{suffix}.zip"
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            names=z.namelist()
            forbidden=[n for n in names if any(x in Path(n).parts for x in ("logs","data","_to_delete","__pycache__","build","outputs")) or n.endswith("/state.json")]
            assert not forbidden,forbidden
            archives[suffix]={"files":len(names),"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"private_runtime_files":forbidden}
            if suffix=="源码":
                assert f"{PROJECT_NAME}/启动督察员.bat" in names
                assert f"{PROJECT_NAME}/docs/VALIDATION.md" in names
                assert f"{PROJECT_NAME}/docs/media/desktop-demo.gif" in names
            else:
                dest=OUT/"含 空格路径"
                dest.mkdir(exist_ok=True)
                for name in names:
                    assert (dest/name).resolve().is_relative_to(dest.resolve())
                z.extractall(dest)
    exe=OUT/"含 空格路径"/PROJECT_NAME/(PROJECT_NAME+".exe")
    check=OUT/"unpacked-portable.json"
    subprocess.run([str(exe),"--self-check",str(check)],check=True,timeout=60)
    subprocess.run([str(exe),"-m","persona.render","--preview",str(OUT/"child-render.png"),"--size","1080x96"],check=True,timeout=60)
    assert (OUT/"child-render.png").stat().st_size>1000
    portable=json.loads(check.read_text(encoding="utf-8"))
    assert portable["passed"] and portable["frozen"]
    gif=Image.open(ROOT/"docs/media/desktop-demo.gif")
    total=0
    for index in range(gif.n_frames):
        gif.seek(index)
        total+=gif.info["duration"]
    social=Image.open(ROOT/"docs/media/social-preview.jpg")
    assert social.size==(1280,640)
    assert (ROOT/"docs/media/social-preview.jpg").stat().st_size<1_000_000
    result={"passed":True,"local_links_checked":checked,"missing_links":missing,
        "archives":archives,"portable":portable,"renderer_child_process":True,
        "gif":{"frames":gif.n_frames,"duration_ms":total,"bytes":(ROOT/"docs/media/desktop-demo.gif").stat().st_size},
        "social_preview":{"width":1280,"height":640},"desktop_captured":False,
        "not_tested":["live overlay and focus behavior","meeting and DND detection","multi-monitor and DPI on actual hardware","full portable resource measurements"]}
    (OUT/"release-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
