"""Draw the home-screen icons: a glowing indigo button on near-black."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "docs"


def icon(size):
    s = size * 4  # draw large, downsample for smooth edges
    img = Image.new("RGB", (s, s), "#0E0F10")
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    r = int(s * 0.33)
    c = s // 2
    ImageDraw.Draw(glow).ellipse((c - r - s // 20, c - r - s // 20, c + r + s // 20, c + r + s // 20), fill=(106, 117, 247, 90))
    img.paste(glow.filter(ImageFilter.GaussianBlur(s // 30)), (0, 0), glow.filter(ImageFilter.GaussianBlur(s // 30)))
    d = ImageDraw.Draw(img)
    # radial-ish fill: stacked circles from dark rim to light centre
    steps = 40
    for i in range(steps):
        t = i / steps
        rr = int(r * (1 - t * 0.55))
        col = tuple(int(a + (b - a) * t) for a, b in zip((78, 88, 214), (138, 147, 255)))
        off = int(r * 0.12 * t)
        d.ellipse((c - rr - off, c - rr - off, c + rr - off, c + rr - off), fill=col)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", int(s * 0.12))
    except OSError:
        font = ImageFont.load_default()
    d.text((c, c), "URGE", fill="#F7F7F7", font=font, anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
    icon(size).save(OUT / name)
    print("wrote", name)
