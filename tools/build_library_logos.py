# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce separate data assets from Carbon's attributed source SVGs."""
from pathlib import Path
import io,sys
import cairosvg
import xml.etree.ElementTree as ET
from PIL import Image
root=Path(__file__).resolve().parents[1]
source=root/'MiSTer/Scripts/.config/mister_monitor/library/logos'
dest=root/'MiSTer/Scripts/.config/mister_monitor/library/logos'
dest.mkdir(parents=True,exist_ok=True)
rows=[]
for name,key in [('snes','snes'),('megadrive','genesis'),('mastersystem','sms'),('tg16','tgfx16'),('nes','nes'),('n64','n64'),('psx','psx')]:
    png=cairosvg.svg2png(bytestring=ET.tostring(ET.fromstring((source/(name+'.svg')).read_bytes())),output_width=720)
    im=Image.open(io.BytesIO(png)).convert('RGBA')
    bounds=im.getchannel('A').getbbox()
    assert bounds,name
    im=im.crop(bounds)
    im.thumbnail((336,96),Image.Resampling.LANCZOS)
    out=Image.new('RGB',(360,120),'white')
    out.paste(im,((360-im.width)//2,(120-im.height)//2),im)
    out.save(dest/(key+'.jpg'),quality=94,subsampling=0,progressive=False)
    rows.append((key,out))
preview=Image.new('RGB',(760,7*150),(16,28,40))
from PIL import ImageDraw
for i,(key,im) in enumerate(rows):
    preview.paste(im,(350,i*150+15))
    ImageDraw.Draw(preview).text((30,i*150+55),key,fill='white',font_size=24)
if len(sys.argv)>1:
    preview.save(sys.argv[1])
