"""sheet.py out.jpg cols label1=img1 label2=img2 ... — tile images with labels into a JPG under 400 KB."""
import sys
from PIL import Image, ImageDraw, ImageFont
out, cols = sys.argv[1], int(sys.argv[2])
items = [a.split("=", 1) for a in sys.argv[3:]]
ims = [(l, Image.open(p).convert("RGB")) for l, p in items]
w = max(i.width for _, i in ims); h = max(i.height for _, i in ims)
tw = min(w, 1600 // cols); th = int(h * tw / w)
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (tw * cols, th * rows), (30, 30, 30))
d = ImageDraw.Draw(sheet)
try:
    f = ImageFont.truetype("arial.ttf", 18)
except Exception:
    f = ImageFont.load_default()
for k, (l, im) in enumerate(ims):
    x, y = (k % cols) * tw, (k // cols) * th
    sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
    d.rectangle([x, y, x + 8 + 10 * len(l), y + 26], fill=(0, 0, 0))
    d.text((x + 5, y + 3), l, fill=(255, 255, 255), font=f)
q = 88
while True:
    sheet.save(out, quality=q)
    import os
    if os.path.getsize(out) < 400_000 or q < 40:
        break
    q -= 6
print(out, sheet.size, os.path.getsize(out), "q", q)
