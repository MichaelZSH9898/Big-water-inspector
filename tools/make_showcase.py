"""Build marketing media from a fictional desktop and the app's own renderer.

Never reads a screenshot, user files, running apps, or live desktop state.
Run: python -B -m tools.make_showcase
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core import config
from overlay.layered_window import place
from persona import render
from persona.loader import load
from winapi.monitors import Monitor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media"
FONT = ROOT / "persona/default_mom/fonts/ZCOOLKuaiLe-Regular.ttf"
LATIN = ROOT / "persona/default_mom/fonts/Nunito-Variable.ttf"
INK = "#4D3536"
MUTED = "#887677"
ROSE = "#BD6D86"
W, H = 1280, 820
DW, DH = 1200, 675
DX, DY = 40, 104


def font(size, latin=False):
    return ImageFont.truetype(str(LATIN if latin else FONT), size)


def text(d, pos, value, size=24, fill=INK, latin=False):
    d.text(pos, value, font=font(size, latin), fill=fill)


def desktop(late=False):
    im = Image.new("RGBA", (DW, DH), "#E7EDEB")
    d = ImageDraw.Draw(im)
    # Entire desktop is drawn here: no OS capture API is used.
    for y in range(DH):
        k = y / DH
        d.line((0, y, DW, y), fill=(int(232-13*k), int(239-12*k), int(236-3*k)))
    d.ellipse((760, -170, 1370, 440), fill="#D7E1DC")
    d.ellipse((930, 130, 1400, 670), fill="#CBD9D3")
    d.rounded_rectangle((60, 50, 812, 570), radius=18, fill="#B7C9C1")
    d.rounded_rectangle((54, 42, 806, 558), radius=18, fill="#FFFDFA")
    d.rounded_rectangle((54, 42, 806, 94), radius=18, fill="#F5F0EB")
    d.rectangle((54, 74, 806, 94), fill="#F5F0EB")
    text(d, (80, 57), "随手记 / 今日计划", 20)
    for x, color in ((734,"#CFBFB6"),(758,"#CFBFB6"),(782,"#CFBFB6")):
        d.ellipse((x-4, 64, x+4, 72), fill=color)
    text(d, (92, 123), "先把今天，过好一点。", 36)
    text(d, (94, 182), "少开几个窗口，也给自己留一点空白。", 20, MUTED)
    for y, label, done in ((252,"完成手上的一件小事",True),(328,"离开椅子，活动一下",False),(404,"给空杯子接一杯水",False)):
        d.rounded_rectangle((92,y,123,y+31),radius=8,fill="#DCE8DF" if done else "#F8F2EC",outline="#BDCEC1",width=2)
        if done:
            d.line((100,y+16,107,y+23,116,y+9),fill="#638B73",width=3)
        text(d,(145,y-1),label,25)
        d.line((145,y+50,756,y+50),fill="#EEE8E1",width=1)
    text(d,(94,505),"不用一直在线，也值得被好好照顾。",20,MUTED)
    text(d,(876,68),"晚一点，也别忘了吃饭" if late else "今天也要照顾好自己",21,"#6E8878")
    d.rectangle((0,DH-48,DW,DH),fill="#F6F8F6")
    for x in (430,441):
        for y in (641,652):
            d.rectangle((x,y,x+8,y+8),fill="#718D85")
    d.rounded_rectangle((470,637,638,665),radius=14,fill="#E5EBE7")
    text(d,(489,641),"搜索",16,MUTED)
    for x,c in ((665,"#CCB89B"),(708,"#7E9CA3"),(751,"#AB8AA1")):
        d.rounded_rectangle((x,641,x+22,663),radius=6,fill=c)
    icon=Image.open(ROOT/"assets/tray/tea_3.ico").convert("RGBA").resize((26,26),Image.Resampling.LANCZOS)
    im.alpha_composite(icon,(1064,639))
    text(d,(1110,637),"20:18" if late else "14:32",15,INK,True)
    text(d,(1104,655),"11 / 03",12,MUTED,True)
    return im


def outer(title, caption):
    im=Image.new("RGBA",(W,H),"#FFF9F2")
    d=ImageDraw.Draw(im)
    text(d,(42,20),title,37)
    text(d,(44,68),caption,20,MUTED)
    d.rounded_rectangle((35,99,1245,784),radius=19,fill="#D9D7D0")
    text(d,(44,793),"合成桌面演示 · 使用应用原生妈妈形象与气泡 · 非实机录屏",17,MUTED)
    return im


def flash(scene, line=None):
    p=load("default_mom")
    cfg=config.load()
    return render.render_flash(p,scene,line or p.lines_for("zh")[scene][0],"zh",
        cfg.raw["appearance"]["hair_color"],"east_asian",DH,96)


def frame(scene=None, alpha=1.0, custom=False):
    late=scene=="overtime_care"
    labels={None:("桌面里，多了一位妈妈。","她会催你喝水，也会惦记你有没有吃饭。"),
        "side_peek":("坐这多久了你，腰还要不要了！","工作告一段落，她从屏幕边缘探出头。"),
        "unlock_scold":("一回来，就被妈妈发现了。","解锁训话 · 提醒你记得喝水"),
        "overtime_care":("嘴上唠叨，心里惦记。","加班关怀 · 再忙，也别忘了吃饭")}
    title,caption=labels[scene]
    if custom:
        title,caption="换成你最熟悉的那一句。","自定义台词预览 · 在设置里点气泡，就能修改"
    out=outer(title,caption)
    desk=desktop(late)
    if scene:
        overlay=flash(scene,"别光顾着改代码，水喝了吗？" if custom else None)
        monitor=Monitor(0,0,DW,DH,0,0,DW,DH-48,96,True,"fictional")
        anchor={"side_peek":"right_edge","unlock_scold":"top_center","overtime_care":"bottom_right"}[scene]
        x,y=place(anchor,*overlay.size,monitor)
        if alpha<1:
            overlay=overlay.copy()
            overlay.putalpha(overlay.getchannel("A").point(lambda a:round(a*alpha)))
        desk.alpha_composite(overlay,(x,y))
    out.alpha_composite(desk,(DX,DY))
    return out.convert("RGB")


def social_preview():
    im=Image.new("RGBA",(1280,640),"#FFF8EF")
    d=ImageDraw.Draw(im)
    text(d,(66,60),"大水理论最严厉的母亲",32,ROSE)
    text(d,(66,140),"妈妈，怎么在",58)
    text(d,(66,213),"我电脑里？",58)
    text(d,(70,326),"催你喝水、起身，也惦记你有没有吃饭。",25,MUTED)
    d.rounded_rectangle((68,404,312,452),radius=24,fill="#F1D6DF")
    text(d,(95,415),"Windows 桌面提醒",23)
    text(d,(70,538),"自定义妈妈形象  /  自定义台词  /  本地运行",22,MUTED)
    p=load("default_mom")
    fig=render.compose_pose(p,"peek","#4F3F3B","east_asian")
    bbox=fig.getbbox()
    fig=fig.crop(bbox)
    fig.thumbnail((470,500),Image.Resampling.LANCZOS)
    im.alpha_composite(fig,(810,640-fig.height))
    return im.convert("RGB")


def custom_comparison():
    im=Image.new("RGBA",(1280,440),"#FFF9F2")
    d=ImageDraw.Draw(im)
    text(d,(42,24),"把唠叨，改成你熟悉的那一句。",36)
    for x,title,line in ((40,"默认台词",None),(660,"你来改一句","别光顾着改代码，水喝了吗？")):
        d.rounded_rectangle((x,95,x+580,412),radius=20,fill="#E5EEEA")
        text(d,(x+24,116),title,23,ROSE)
        img=flash("side_peek",line)
        img.thumbnail((550,220),Image.Resampling.LANCZOS)
        im.alpha_composite(img,(x+580-img.width,195))
    return im.convert("RGB")


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    from settings_ui.model import SettingsModel
    from settings_ui.ui_render import UiState, render_ui
    m=SettingsModel()
    state=UiState(lang=m.lang,hair=m.hair,character=m.character,
        hair_presets=m.presets("hair"),characters=m.characters(),display_name=m.display_name(),
        traits=m.traits(),card_name=m.card_name(),figure=m.figure(),previews=m.preview(),
        stats={"water_min":0,"sitting_min":0,"effective_today_min":0})
    render_ui(state)[0].convert("RGB").save(ROOT/"docs/settings_zh.png",optimize=True)
    frames,durations=[],[]
    def append(im,ms):
        frames.append(im.quantize(colors=192,method=Image.Quantize.MEDIANCUT))
        durations.append(ms)
    for scene,custom in (("side_peek",False),("unlock_scold",False),("side_peek",True),("overtime_care",False)):
        append(frame(scene,custom=custom),3000 if custom else 1500)
        for alpha in (.8,.6,.4,.2,0):
            append(frame(scene,alpha,custom),100)
        append(frame(),600)
    frames[0].save(OUT/"desktop-demo.gif",save_all=True,append_images=frames[1:],duration=durations,
                   loop=0,optimize=True,disposal=2)
    frame("side_peek").save(OUT/"desktop-preview.png",optimize=True)
    frame("overtime_care").save(OUT/"overtime-preview.png",optimize=True)
    social_preview().save(OUT/"social-preview.jpg",quality=94,optimize=True)
    custom_comparison().save(OUT/"custom-lines.png",optimize=True)
    (OUT/"provenance.json").write_text(json.dumps({"synthetic_desktop":True,"desktop_capture":False,
        "renderer":"persona.render.render_flash","placement":"overlay.layered_window.place",
        "default_show_ms":1500,"fade_ms":500,"custom_preview_show_ms":3000,
        "scene_gaps_compressed":True,"duration_ms":sum(durations),
        "personal_data_used":False},indent=2),encoding="utf-8")
    print(json.dumps({p.name:p.stat().st_size for p in OUT.iterdir()},ensure_ascii=False))


if __name__=="__main__":
    main()
