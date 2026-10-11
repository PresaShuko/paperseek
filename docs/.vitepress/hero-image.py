"""Generate the homepage hero (docs/public/images/hero.webp).

A dusk coast printed from scholarly words: the lighthouse beam is the search,
the stratified cliffs are stacked pages, and the lit constellation is the set
of papers it finds. Requires Pillow and NumPy:

    python docs/.vitepress/hero-image.py docs/public/images/hero.webp
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
W, H = 2400, 840
rng = np.random.default_rng(21)
Y, X = np.mgrid[0:H, 0:W]; y = Y / H; x = X / W
def noise(scale, octaves=4, seed=0, aspect=1.0):
    r = np.random.default_rng(seed); out = np.zeros((H, W)); tot = 0
    for o in range(octaves):
        s = scale * 2 ** o; g = r.random((max(2, int(H / W * s / aspect)) + 2, int(s) + 2))
        out += np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float) / 255 / 2 ** o; tot += 1 / 2 ** o
    return out / tot
def mix(a, b, t):
    t = np.clip(t, 0, 1)[..., None]; a = np.asarray(a, float); b = np.asarray(b, float); return a * (1 - t) + b * t
HZ = .62
# dusk sky
sky = mix((30, 38, 82), (122, 98, 140), (y / HZ) ** 1.3)
sky = mix(sky, (246, 190, 140), np.clip((y - HZ * .55) / (HZ * .45), 0, 1) ** 1.8)
sun = np.exp(-(((x - .66) * 2.6) ** 2 + ((y - HZ) * 6) ** 2))
sky = mix(sky, (255, 222, 170), sun * .9)
cl = noise(5, 5, seed=3, aspect=3)
cloud = np.clip((cl - .55) * 5, 0, 1) * np.exp(-((y - .4) / .1) ** 2)
sky = mix(sky, mix((236, 150, 130), (120, 90, 130), (.45 - y) * 4), cloud * .7)
img = sky.copy()
# lighthouse position and beam direction (towards upper right)
LX, LY = .205 * W, .17 * H
ang = np.deg2rad(-11); dx, dy = np.cos(ang), np.sin(ang)
vx, vy = X - LX, Y - LY
along = vx * dx + vy * dy; perp = np.abs(-vx * dy + vy * dx)
beam = np.clip(along / W, 0, 1) ** .3 * np.exp(-(perp / (30 + along * .16)) ** 2) * (along > 0) * np.exp(-along / (W * 1.4))
# stars and citation constellations
starlayer = Image.new('RGBA', (W, H)); sd = ImageDraw.Draw(starlayer)
def lit(px, py):
    a = (px - LX) * dx + (py - LY) * dy; p = abs(-(px - LX) * dy + (py - LY) * dx); return a > 0 and p < 30 + a * .16
clusters = [(.42, .12), (.58, .3), (.8, .14), (.93, .36), (.33, .38), (.7, .05)]
for k, (ux, uy) in enumerate(clusters):
    pts = [(ux * W + rng.normal(0, 70), uy * H + rng.normal(0, 40)) for _ in range(rng.integers(5, 8))]
    on = sum(lit(*p) for p in pts) >= len(pts) / 2
    for i in range(1, len(pts)):
        j = int(np.argmin([np.hypot(pts[i][0] - q[0], pts[i][1] - q[1]) for q in pts[:i]]))
        sd.line([pts[i], pts[j]], fill=(150, 236, 236, 170) if on else (220, 220, 240, 55), width=2 if on else 1)
    for p in pts:
        r = 4.5 if on else 3
        sd.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=(240, 255, 252, 255) if on else (240, 236, 250, 200))
for _ in range(260):
    px, py = rng.uniform(0, W), rng.uniform(0, H * .5) ** 1.1
    r = rng.uniform(.8, 2.2); a = int(rng.uniform(60, 200) * (1 - py / (H * .55)))
    sd.ellipse((px - r, py - r, px + r, py + r), fill=(255, 250, 240, max(a, 0)))
# far island
isl = HZ - .045 * np.exp(-((x - .44) / .07) ** 2) - .02 * np.exp(-((x - .5) / .04) ** 2) - .012 * noise(30, 3, seed=16)[0][None, :]
img = mix(img, mix((112, 96, 132), (150, 120, 140), (y - .5) * 4), (y > isl) & (y < HZ))
# stratified sea cliffs on the right: rock layers like the edges of stacked pages
n1 = noise(14, 4, seed=7)[0][None, :]; n2 = noise(40, 3, seed=13)
top = .26 + .07 * np.sin(x * 7 + 1) + .05 * n1
left = .6 + .03 * (noise(3, 4, seed=14, aspect=.1)[:, :1] - .5) + .07 * np.clip((top + .06 - y) * 4, 0, 1)
face = (y > top) & (x > left) & (y < HZ)
stack = (np.abs(x - .565) < .018 + .006 * (y - .4) * 4) & (y > .4 + .02 * n2) & (y < HZ)
face = face | stack
pos = Y + (x - .6) * 120 + noise(5, 2, seed=8) * 40
edges = np.cumsum(rng.integers(5, 15, 600)).astype(float)
band = np.clip(np.searchsorted(edges, pos), 1, 599)
frac = (pos - edges[band - 1]) / (edges[band] - edges[band - 1])
tone = rng.uniform(.8, 1.1, 600)[band] * (1 - .32 * np.exp(-(frac / .16) ** 2))
streak = 1 - .1 * np.clip((noise(80, 2, seed=15, aspect=8) - .5) * 4, 0, 1)
rock = mix((150, 100, 76), (236, 192, 142), np.clip(sun * 1.6 + (HZ - y) * .6, 0, 1))
rock = rock * (tone * streak * (1 - np.clip((x - .62) / .4, 0, 1) * .3) * (1 - .25 * np.clip((y - HZ + .05) / .05, 0, 1)))[..., None]
img = np.where(face[..., None], rock, img)
cap = face & (y < top + .02 + .01 * n2) & ~stack
img = np.where(cap[..., None], mix(img, (72, 92, 62), .8), img)
# headland on the left, the lighthouse on its crest
crest = .205
head = .43 - .05 * np.exp(-((x - crest) / .06) ** 2) + .5 * np.clip((x - .26) / .12, 0, 1) ** 1.4 + .015 * (noise(24, 3, seed=10)[0][None, :] - .5) + .05 * np.clip((.08 - x) / .08, 0, 1)
land = (y > head) & (y < HZ + .02)
hl = mix((34, 34, 52), (98, 80, 90), noise(16, 4, seed=11) * .7 + np.clip((.3 - x) * 2, 0, 1) * .3)
hl = mix(hl, (196, 140, 118), np.clip(1 - (y - head) * 40, 0, 1) * .5)
img = np.where(land[..., None], hl, img)
BASE = float(head[0, int(crest * W)]) * H
# sea with reflections and the beam's path
sea = y >= HZ
d = np.clip((y - HZ) / (1 - HZ), 0, 1)
rip = noise(60, 3, seed=12, aspect=.15)
hz = int(HZ * H)
src = np.clip(2 * hz - Y + ((rip - .5) * 18).astype(int), 0, hz - 1)
mirror = img[src, np.clip(X + ((rip - .5) * 10).astype(int), 0, W - 1)]
sc = mix((64, 78, 124), (14, 26, 60), d ** .6)
sc = mix(sc, mirror * .8, np.clip(1 - d * 2.2, 0, 1) * .7)
refl = np.exp(-((x - .66) / (.02 + .09 * d)) ** 2) * (rip > .5) * (1 - d) ** .8
sc = mix(sc, (255, 214, 160), refl * .8)
img = np.where(sea[..., None], sc, img)
img = mix(img, (255, 244, 210), beam * .8)
img = np.where(sea[..., None], mix(img, (255, 246, 214), np.exp(-((x - .44 - d * .1) / (.04 + .1 * d)) ** 2) * (rip > .55) * .35 * (1 - d)), img)
im = Image.fromarray(img.clip(0, 255).astype(np.uint8)).convert('RGBA')
im.alpha_composite(starlayer.filter(ImageFilter.GaussianBlur(.6)))
# lighthouse; the lantern carries the mark's two teal bars
d2 = ImageDraw.Draw(im); lx, bt, tp = LX, BASE + 6, LY + 20
d2.polygon([(lx - 24, bt), (lx + 24, bt), (lx + 15, tp), (lx - 15, tp)], fill=(214, 206, 204))
d2.polygon([(lx + 4, bt), (lx + 24, bt), (lx + 15, tp), (lx + 2, tp)], fill=(160, 150, 160))
for yy in np.arange(tp + 30, bt - 20, 56):
    w0 = 15 + (yy - tp) / (bt - tp) * 9
    d2.polygon([(lx - w0, yy), (lx + w0, yy), (lx + w0 + 1, yy + 22), (lx - w0 - 1, yy + 22)], fill=(150, 62, 60))
d2.rectangle((lx - 21, tp - 6, lx + 21, tp), fill=(44, 42, 52))
d2.rectangle((lx - 13, tp - 38, lx + 13, tp - 6), fill=(255, 238, 196))
d2.polygon([(lx - 9, tp - 31), (lx + 3, tp - 31), (lx + 7, tp - 25), (lx - 5, tp - 25)], fill=(59, 184, 195))
d2.polygon([(lx - 10, tp - 20), (lx + 5, tp - 20), (lx + 9, tp - 13), (lx - 6, tp - 13)], fill=(59, 184, 195))
d2.polygon([(lx - 17, tp - 38), (lx + 17, tp - 38), (lx, tp - 60)], fill=(44, 42, 52))
glow = Image.new('L', (W, H)); ImageDraw.Draw(glow).ellipse((lx - 60, tp - 80, lx + 60, tp + 40), fill=160)
im = Image.composite(Image.new('RGBA', (W, H), (255, 240, 200, 255)), im, glow.filter(ImageFilter.GaussianBlur(30)))
im = im.convert('RGB').filter(ImageFilter.GaussianBlur(.9))
# character mosaic, like a finely printed plate
cw, ch = 7, 11
MONO = [Path('C:/Windows/Fonts/consola.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'), Path('/System/Library/Fonts/Menlo.ttc')]
font = ImageFont.truetype(str(next(p for p in MONO if p.exists())), 11)
small = np.asarray(im.resize((W // cw, H // ch), Image.BILINEAR), float)
out = Image.fromarray(np.clip(np.asarray(im, float) * .94 + 255 * .06, 0, 255).astype(np.uint8)); od = ImageDraw.Draw(out)
words = ('abstract introduction methods results discussion references citation evidence corpus query review '
         'journal archive index cohort sample hypothesis findings literature survey dataset analysis keywords '
         'meta-analysis systematic retrieval ranking relevance authors venue year volume issue pages doi ').split()
cols = small.shape[1]
for j in range(small.shape[0]):
    line = ''
    while len(line) < cols: line += words[int(rng.integers(0, len(words)))] + ' '
    for i, letter in enumerate(line[:cols]):
        if letter != ' ': od.text((i * cw, j * ch - 1), letter, fill=tuple(int(v) for v in small[j, i] * .84), font=font)
out.save(sys.argv[1], quality=80, method=6)
