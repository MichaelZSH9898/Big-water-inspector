"""Make a local, offline preview of the Markdown pages (development tool)."""
from pathlib import Path
import re
import shutil

import mistune

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/preview"
CSS='''*{box-sizing:border-box}body{margin:0;background:#f6f8fa;color:#24292f;font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}nav{background:#fff;border-bottom:1px solid #d0d7de;padding:16px 24px;font-size:14px}nav a{margin-left:18px}.page{max-width:1012px;margin:28px auto 80px;border:1px solid #d0d7de;border-radius:8px;background:white}.file{border-bottom:1px solid #d8dee4;padding:12px 28px;font-size:14px;color:#57606a}article{padding:32px 44px}a{color:#0969da;text-decoration:none}a:hover{text-decoration:underline}h1,h2{line-height:1.3;border-bottom:1px solid #d8dee4;padding-bottom:.3em}h1{font-size:32px;margin:0 0 16px}h2{font-size:24px;margin-top:32px}p{margin:0 0 16px}img{max-width:100%;height:auto}code{background:#eff1f3;border-radius:4px;padding:2px 5px;font:85% ui-monospace,Consolas,monospace}pre{background:#f6f8fa;padding:16px;overflow:auto}pre code{padding:0;background:none}table{border-collapse:collapse;display:block;overflow:auto;margin-bottom:16px}th,td{padding:8px 13px;border:1px solid #d0d7de}tr:nth-child(even){background:#f6f8fa}sub{display:block;color:#68707a;line-height:1.6}summary{cursor:pointer;margin:16px 0}hr{border:0;border-top:1px solid #d0d7de;margin:28px 0}@media(max-width:650px){body{font-size:15px}.page{margin:12px 8px;border-radius:5px}article{padding:24px 16px}.file{padding:10px 16px}nav{padding:12px}h1{font-size:27px}h2{font-size:21px}nav a{margin-left:10px}}'''


def slug(text):
    return re.sub(r"[^\w\-\u4e00-\u9fff ]","",re.sub("<[^>]*>","",text)).lower().replace(" ","-")


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    markdown=mistune.create_markdown(escape=False,plugins=["table"])
    paths=[ROOT/"README.md",ROOT/"README.en.md",ROOT/"CONTRIBUTING.md",ROOT/"ASSET_NOTICES.md",ROOT/"CHANGELOG.md",ROOT/"persona/README.md"]+list((ROOT/"docs").glob("*.md"))
    for p in paths:
        rel=p.relative_to(ROOT)
        body=markdown(p.read_text(encoding="utf-8-sig"))
        body=re.sub(r'(<h([1-6]))>(.*?)</h\2>',lambda m:f'{m[1]} id="{slug(m[3])}">{m[3]}</h{m[2]}>',body)
        body=re.sub(r'href="([^"#]*?)\.md([#"][^"]*)',r'href="\1.html\2',body)
        target=OUT/rel.with_suffix(".html")
        target.parent.mkdir(parents=True,exist_ok=True)
        depth=len(rel.parts)-1
        prefix="../"*depth
        html=f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>大水理论最严厉的母亲 · 项目预览</title><style>{CSS}</style><nav>README 本地预览<a href="{prefix}README.html">简体中文</a><a href="{prefix}README.en.html">English</a></nav><main class="page"><div class="file">{rel.as_posix()}</div><article>{body}</article></main></html>'
        target.write_text(html,encoding="utf-8")
    for p in (ROOT/"docs").rglob("*"):
        if p.is_file() and p.suffix.lower() in (".png",".jpg",".gif"):
            target=OUT/p.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,target)
    shutil.copy2(ROOT/"LICENSE",OUT/"LICENSE")
    print(OUT/"README.html")


if __name__=="__main__":
    main()
