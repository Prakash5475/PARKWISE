"""Crisp vector icons drawn with Pillow (4x supersampled) -> CTkImage. No emojis, no files."""
from PIL import Image, ImageDraw
import customtkinter as ctk

_CACHE = {}
S = 4   # supersampling


def _draw(name, d, n, col, w):
    p = lambda v: v * n / 24 * S          # 24-unit design grid
    lw = int(w * n / 24 * S)
    if name == "dashboard":
        for x, y, ww, hh in ((3, 3, 8, 10), (13, 3, 8, 6), (13, 11, 8, 10), (3, 15, 8, 6)):
            d.rounded_rectangle([p(x), p(y), p(x + ww), p(y + hh)], radius=p(2), outline=col, width=lw)
    elif name == "monitor":
        d.rounded_rectangle([p(2.5), p(4), p(21.5), p(17)], radius=p(2.5), outline=col, width=lw)
        d.line([p(8), p(21), p(16), p(21)], fill=col, width=lw)
        d.line([p(12), p(17), p(12), p(21)], fill=col, width=lw)
        d.line([p(5.5), p(11), p(9), p(11), p(11), p(7.5), p(13.5), p(13.5), p(15), p(11), p(18.5), p(11)], fill=col, width=lw, joint="curve")
    elif name == "manage":
        for y, kx in ((6, 8), (12, 16), (18, 10)):
            d.line([p(3), p(y), p(21), p(y)], fill=col, width=lw)
            d.ellipse([p(kx - 2.6), p(y - 2.6), p(kx + 2.6), p(y + 2.6)], fill="#0C1322", outline=col, width=lw)
    elif name == "tickets":
        d.rounded_rectangle([p(2.5), p(6), p(21.5), p(18)], radius=p(2.2), outline=col, width=lw)
        d.line([p(15), p(7), p(15), p(17)], fill=col, width=int(lw * .8))
        d.line([p(6), p(10.5), p(11), p(10.5)], fill=col, width=lw)
        d.line([p(6), p(13.5), p(10), p(13.5)], fill=col, width=lw)
    elif name == "analytics":
        for x, top in ((4, 13), (10, 6), (16, 10)):
            d.rounded_rectangle([p(x), p(top), p(x + 4), p(20)], radius=p(1.2), outline=col, width=lw)
    elif name == "logs":
        for y in (6, 12, 18):
            d.ellipse([p(3), p(y - 1), p(5), p(y + 1)], fill=col)
            d.line([p(8), p(y), p(21), p(y)], fill=col, width=lw)
    elif name == "system":
        d.rounded_rectangle([p(6), p(6), p(18), p(18)], radius=p(2), outline=col, width=lw)
        d.rounded_rectangle([p(9.5), p(9.5), p(14.5), p(14.5)], radius=p(1), fill=col)
        for t in (9, 12, 15):
            d.line([p(t), p(2.5), p(t), p(6)], fill=col, width=lw)
            d.line([p(t), p(18), p(t), p(21.5)], fill=col, width=lw)
            d.line([p(2.5), p(t), p(6), p(t)], fill=col, width=lw)
            d.line([p(18), p(t), p(21.5), p(t)], fill=col, width=lw)
    elif name == "logo":
        d.rounded_rectangle([p(1), p(1), p(23), p(23)], radius=p(6), fill=col)
        d.line([p(9), p(18), p(9), p(6.5), p(13.2), p(6.5)], fill="#0C1322", width=int(lw * 1.5), joint="curve")
        d.arc([p(7), p(6.5), p(17.2), p(15)], -90, 90, fill="#0C1322", width=int(lw * 1.5))
    elif name == "refresh":
        d.arc([p(4), p(4), p(20), p(20)], 40, 330, fill=col, width=lw)
        d.polygon([p(17), p(1.8), p(21.5), p(7.5), p(14.5), p(8)], fill=col)
    elif name == "download":
        d.line([p(12), p(3), p(12), p(15)], fill=col, width=lw)
        d.line([p(6.5), p(10), p(12), p(15.5), p(17.5), p(10)], fill=col, width=lw, joint="curve")
        d.line([p(4), p(20), p(20), p(20)], fill=col, width=lw)
    elif name == "plus":
        d.line([p(12), p(4), p(12), p(20)], fill=col, width=lw)
        d.line([p(4), p(12), p(20), p(12)], fill=col, width=lw)
    elif name == "play":
        d.polygon([p(7), p(4.5), p(20), p(12), p(7), p(19.5)], fill=col)
    elif name == "stop":
        d.rounded_rectangle([p(5.5), p(5.5), p(18.5), p(18.5)], radius=p(2), fill=col)
    elif name == "pdf":
        d.rounded_rectangle([p(5), p(2.5), p(19), p(21.5)], radius=p(2), outline=col, width=lw)
        d.line([p(8.5), p(10), p(15.5), p(10)], fill=col, width=lw)
        d.line([p(8.5), p(14), p(15.5), p(14)], fill=col, width=lw)
        d.line([p(8.5), p(17.5), p(12.5), p(17.5)], fill=col, width=lw)
    elif name == "search":
        d.ellipse([p(4), p(4), p(16), p(16)], outline=col, width=lw)
        d.line([p(14), p(14), p(20.5), p(20.5)], fill=col, width=lw)
    elif name == "car":
        d.rounded_rectangle([p(3), p(10), p(21), p(18)], radius=p(3), outline=col, width=lw)
        d.line([p(6), p(10), p(8.5), p(5.5), p(15.5), p(5.5), p(18), p(10)], fill=col, width=lw, joint="curve")
        for x in (7.5, 16.5):
            d.ellipse([p(x - 1.6), p(16.4), p(x + 1.6), p(20)], fill=col)


def icon(name, size=20, color="#8A9AB3", weight=1.9):
    key = (name, size, color, weight)
    if key not in _CACHE:
        img = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
        _draw(name, ImageDraw.Draw(img), size, color, weight)
        img = img.resize((size, size), Image.LANCZOS)
        _CACHE[key] = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    return _CACHE[key]
