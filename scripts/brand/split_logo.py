"""ecom-logo.svg 의 하위 도형을 나눠 lockup(마크 + ECOM, 태그라인 뺌)과 word(ECOM 글자 전체)를 만든다.
쓰는 법: python scripts/brand/split_logo.py  (ecom-lockup.svg · ecom-word.svg 를 쓰고 app/src/lib/brand.ts 의 lockup · word 를 갱신)
"""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
BRAND = os.path.join(ROOT, 'app', 'public', 'brand')

svg = open(os.path.join(BRAND, 'ecom-logo.svg'), encoding='utf-8').read()
d = re.search(r' d="([^"]+)"', svg).group(1)
subs = re.findall(r'M[^M]+', d)

def bbox(sp):
    n = [float(x) for x in re.findall(r'-?\d+\.?\d*', sp)]
    xs, ys = n[0::2], n[1::2]
    return min(xs), min(ys), max(xs), max(ys)

MARK_X1, TEXT_X0, TAG_Y0 = 102, 129, 95
mark, letters = [], []
for sp in subs:
    x0, y0, x1, y1 = bbox(sp)
    if x1 <= MARK_X1 + 1 and x0 < MARK_X1:
        mark.append(sp)
    elif y0 < TAG_Y0 and x0 >= TEXT_X0 - 1:
        letters.append(sp)          # 글자와 속 구멍(O 안쪽)
    # 그 밖(태그라인: 글자 아래 · 마크 오른쪽)은 뺀다
assert len(mark) == 1 and len(letters) == 5, (len(mark), len(letters))

def shift(sp, dx, dy):
    # 절대좌표 M L C 만 쓰는 경로: 숫자가 x y 쌍으로 이어진다
    cmds = re.findall(r'[MLCZ][^MLCZ]*', sp)
    out = []
    for c in cmds:
        k, rest = c[0], c[1:]
        nums = [float(x) for x in re.findall(r'-?\d+\.?\d*', rest)]
        pts = [f"{nums[i] - dx:.2f} {nums[i + 1] - dy:.2f}" for i in range(0, len(nums), 2)]
        out.append(k + (' '.join(pts) if k != 'C' else ' '.join(pts)))
    return ''.join(out)

def build(parts, x0, y0, x1, y1):
    d2 = ''.join(shift(p, x0, y0) for p in parts)
    w, h = x1 - x0, y1 - y0
    return f"0 0 {w} {h}", d2

# 마크 + 글자: 원본 좌표 x 1..377, y 0..132 / 글자만: x 129..377, y 27..91 (정수 경계 → 원본 그림과 겹쳐 검사)
lock_vb, lock_d = build(mark + letters, 1, 0, 377, 132)
word_vb, word_d = build(letters, 128, 26, 378, 92)

def write_svg(name, vb, dd):
    open(os.path.join(BRAND, name), 'w', encoding='utf-8').write(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><path fill="currentColor" fill-rule="evenodd" d="{dd}"/></svg>\n')
write_svg('ecom-lockup.svg', lock_vb, lock_d)
write_svg('ecom-word.svg', word_vb, word_d)

# brand.ts: 기존 mark · logo 는 두고 word 교체 + lockup 추가
ts_path = os.path.join(ROOT, 'app', 'src', 'lib', 'brand.ts')
ts = open(ts_path, encoding='utf-8').read()
head = ts.split('\n', 1)[0]
m = {k: re.search(k + r': \{\n    viewBox: "([^"]+)",\n    d: "([^"]+)",', ts) for k in ('mark', 'logo')}
ent = lambda k, vb, dd: f'  {k}: {{\n    viewBox: "{vb}",\n    d: "{dd}",\n  }},\n'
body = (head + "\nexport type BrandKey = 'mark' | 'word' | 'logo' | 'lockup'\n"
        "export const BRAND: Record<BrandKey, { viewBox: string; d: string }> = {\n"
        + ent('mark', *m['mark'].groups()) + ent('word', word_vb, word_d)
        + ent('logo', *m['logo'].groups()) + ent('lockup', lock_vb, lock_d) + '}\n')
open(ts_path, 'w', encoding='utf-8').write(body)
print('lockup', lock_vb, 'word', word_vb)
