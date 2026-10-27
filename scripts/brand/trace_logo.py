"""ECOM logo -> SVG outlines via potrace (no fonts). Needs: pip install --target .omc/tmp/pylib potracer"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, '.omc', 'tmp', 'pylib'))
import numpy as np
import potrace
from PIL import Image

S = 4
BBOX = (61, 159, 442, 307)
src = Image.open(os.path.join(HERE, 'ecom-logo-source.png')).convert('RGBA')
logo = src.crop(BBOX)  # 381x148
W, H = logo.size
MARK_X1, TEXT_X0, WORD_Y1 = 102, 129, 64

def trace(box):
    """box in logo coords (x0,y0,x1,y1) -> (w,h,path d)"""
    a = logo.getchannel('A').crop(box)
    w, h = a.size
    a = a.resize((w * S, h * S), Image.LANCZOS)
    bm = potrace.Bitmap(np.array(a) <= 128)
    pl = bm.trace(turdsize=8, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
                  alphamax=1.0, opticurve=True, opttolerance=0.2)
    f = lambda p: f"{p.x / S:.2f} {p.y / S:.2f}"
    d = []
    for c in pl:
        d.append(f"M{f(c.start_point)}")
        for s in c.segments:
            if s.is_corner:
                d.append(f"L{f(s.c)}L{f(s.end_point)}")
            else:
                d.append(f"C{f(s.c1)} {f(s.c2)} {f(s.end_point)}")
        d.append("Z")
    return w, h, ''.join(d)

def save(name, box):
    w, h, d = trace(box)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
           f'<path fill="currentColor" fill-rule="evenodd" d="{d}"/></svg>\n')
    out = os.path.join(ROOT, 'app', 'public', 'brand', name)
    open(out, 'w', encoding='utf-8').write(svg)
    print(name, w, h, len(svg))

save('ecom-mark.svg', (0, 0, MARK_X1, H))
# ecom-word.svg 는 여기서 쓰지 않는다 — 옛 잘린 영역이라 글자가 깨진다. split_logo 가 만든 것을 그대로 둔다.
save('ecom-logo.svg', (0, 0, W, H))
