"""Top-view vehicle drawings for tkinter Canvas.

Vehicles are built from rotated polygons (body, hood/trunk panels, glass, wheels, lights,
mirrors).  Shapes are defined once in local coordinates (x = forward, y = right) and
transformed per frame by position, heading and scale.

  CAR  64 x 30   sedan with windshield, roof, rear glass, mirrors
  EV   64 x 30   same body + cyan under-glow, roof bolt emblem, charge-port light
  VIP  64 x 30   dark body with gold racing stripes and gold trim
  BIKE 50 x 24   two wheels, tank, handlebar, rider and helmet (clearly smaller)
"""
import math

CAR_PALETTE = ["#D9434E", "#3B7DDD", "#E8EDF2", "#AAB4C0", "#4B5563", "#E5B83A",
               "#2FB7A6", "#E0782F", "#3AA56A", "#8B5CF6", "#C2410C", "#0EA5E9"]
VIP_PALETTE = ["#15171C", "#262B36", "#F2EFE6"]
BIKE_PALETTE = ["#D9434E", "#3B7DDD", "#E5B83A", "#2FB7A6", "#E0782F", "#8B5CF6"]
GOLD = "#D4AF37"
SIZE = {"CAR": (64, 30), "EV": (64, 30), "VIP": (64, 30), "BIKE": (50, 24)}


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shade(hex_color, f):
    """Lighten (f>1) or darken (f<1) a colour."""
    r, g, b = _rgb(hex_color)
    if f >= 1:
        r, g, b = (int(v + (255 - v) * (f - 1)) for v in (r, g, b))
    else:
        r, g, b = (int(v * f) for v in (r, g, b))
    return "#%02x%02x%02x" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _xf(pts, cx, cy, c, s, k):
    out = []
    for px, py in pts:
        out.append(cx + k * (px * c - py * s))
        out.append(cy + k * (px * s + py * c))
    return out


def _mirror(pts):
    return [(x, -y) for x, y in pts]


def _rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


# ---- local shapes (car) ----------------------------------------------------------------
BODY = [(-32, -9), (-30, -13), (-26, -15), (22, -15), (28, -13), (31, -9), (32, -4),
        (32, 4), (31, 9), (28, 13), (22, 15), (-26, 15), (-30, 13), (-32, 9)]
HOOD = [(11, -12), (26, -11.5), (30, -8), (30, 8), (26, 11.5), (11, 12)]
TRUNK = [(-30, -9), (-24, -12), (-19, -12), (-19, 12), (-24, 12), (-30, 9)]
GREENHOUSE = [(-20, -11), (-15, -13), (6, -13), (15, -10), (15, 10), (6, 13), (-15, 13), (-20, 11)]
ROOF = [(-15, -9), (4, -9), (8, -7), (8, 7), (4, 9), (-15, 9), (-17, 7), (-17, -7)]
HEADLIGHT = [(29.5, -12), (32, -9.5), (32, -5.5), (29, -7)]
TAILLIGHT = [(-32, -11), (-31, -12.5), (-29.5, -12), (-29.5, -6.5), (-32, -6.5)]
MIRROR_L = [(9, -15), (13, -17.5), (14.5, -15.5), (11, -14)]
WHEELS = [(20, -15.5), (20, 15.5), (-20, -15.5), (-20, 15.5)]
BOLT = [(0.5, -6), (-4.5, 1), (-0.5, 1), (-2, 6.5), (4.5, -1.5), (0.5, -1.5), (3, -6)]
BADGE = [(26, 0), (24, -2.2), (22, 0), (24, 2.2)]

# ---- local shapes (motorcycle) ------------------------------------------------------------
B_WHEEL_R = _rect(-16, 0, 15, 6)
B_WHEEL_F = _rect(16, 0, 15, 6)
B_TANK = [(-6, -5), (3, -6.5), (9, -4), (11, 0), (9, 4), (3, 6.5), (-6, 5), (-10, 0)]
B_SEAT = [(-17, -4.5), (-9, -5), (-5, -4), (-5, 4), (-9, 5), (-17, 4.5)]
B_TORSO = [(-9, -7), (-1, -9), (4, -6.5), (4, 6.5), (-1, 9), (-9, 7)]


def draw_vehicle(cv, x, y, heading, vtype, color, k=1.0, tag="veh", lights=True):
    """Draw one vehicle centred on (x, y).  *k* scales logical units to pixels."""
    a = math.radians(heading)
    c, s = math.cos(a), math.sin(a)

    def poly(pts, fill, outline="", width=1, smooth=False, stipple=""):
        kw = {"stipple": stipple} if stipple else {}
        cv.create_polygon(_xf(pts, x, y, c, s, k), fill=fill, outline=outline, width=width,
                          smooth=smooth, tags=tag, **kw)

    if vtype == "BIKE":
        _draw_bike(cv, x, y, c, s, k, color, tag, poly)
        return

    # shadow (screen-space offset, not rotated)
    sh = _xf(BODY, x, y, c, s, k)
    cv.create_polygon([v + (2.5 * k if i % 2 == 0 else 3.5 * k) for i, v in enumerate(sh)],
                      fill="#000000", stipple="gray50", smooth=True, tags=tag)
    if vtype == "EV":                                  # cyan under-glow ring
        poly([(px * 1.07, py * 1.12) for px, py in BODY], "", "#29D3EC", 1.6, True)
    body = color
    dark = shade(color, 0.72)
    light_c = shade(color, 1.18)
    glass = "#2B3B52" if vtype == "VIP" else "#7FB6D6"
    for wx, wy in WHEELS:                               # wheels first (poke out from body)
        poly(_rect(wx, wy, 11, 4.5), "#0B0F16", "#38455C", 1)
    poly(BODY, body, GOLD if vtype == "VIP" else dark, 1.6 if vtype == "VIP" else 1.2, True)
    poly(HOOD, light_c, "", 1, True)
    poly(TRUNK, light_c, "", 1, True)
    poly(GREENHOUSE, glass, dark, 1, True)
    poly(ROOF, shade(color, 0.95), dark, 1, True)
    poly([(-3, -6), (6, -6), (7.5, -4.5), (-3, -4.5)], shade(glass, 1.35), "")   # glass gloss
    if vtype == "VIP":
        for yy in (-2.6, 2.6):                          # gold racing stripes
            cv.create_line(_xf([(-30, yy), (-17, yy)], x, y, c, s, k), fill=GOLD, width=max(1, 1.4 * k), tags=tag)
            cv.create_line(_xf([(15, yy), (30, yy)], x, y, c, s, k), fill=GOLD, width=max(1, 1.4 * k), tags=tag)
        poly(BADGE, GOLD, "")
    if vtype == "EV":
        poly(BOLT, "#FFFFFF", "#29D3EC", 1)
        poly(_rect(-26, -12, 3.2, 3.2), "#2FD27F", "")  # charge-port light
    if lights:
        for pts in (HEADLIGHT, _mirror(HEADLIGHT)):
            poly(pts, "#FFF1B8", "#E5C76B", 1)
        for pts in (TAILLIGHT, _mirror(TAILLIGHT)):
            poly(pts, "#FF3B4A", "#9B1C28", 1)
    poly(MIRROR_L, dark, "")
    poly(_mirror(MIRROR_L), dark, "")


def _draw_bike(cv, x, y, c, s, k, color, tag, poly):
    sh = _xf(B_TANK, x, y, c, s, k)
    cv.create_polygon([v + (2 * k if i % 2 == 0 else 3 * k) for i, v in enumerate(sh)],
                      fill="#000000", stipple="gray50", smooth=True, tags=tag)
    poly(B_WHEEL_R, "#0B0F16", "#3A4658", 1.2)
    poly(B_WHEEL_F, "#0B0F16", "#3A4658", 1.2)
    cv.create_line(_xf([(16, 0), (7, 0)], x, y, c, s, k), fill="#9AA6B8", width=max(1, 2 * k), tags=tag)   # fork
    poly(B_SEAT, "#1C222D", "#0B0F16", 1, True)
    poly(B_TANK, color, shade(color, 0.7), 1.2, True)
    cv.create_line(_xf([(8, -12), (8, 12)], x, y, c, s, k), fill="#1C222D", width=max(2, 3.2 * k),
                   capstyle="round", tags=tag)                                                              # handlebar
    for yy in (-5, 5):                                                                                      # arms
        cv.create_line(_xf([(0, yy * 1.15), (8, yy * 1.9)], x, y, c, s, k), fill=shade(color, 0.55),
                       width=max(2, 3.6 * k), capstyle="round", tags=tag)
    poly(B_TORSO, shade(color, 0.55), shade(color, 0.35), 1.2, True)                                                            # rider
    poly([(2 + dx * 5.4, dy * 5.4) for dx, dy in
          ((math.cos(t), math.sin(t)) for t in [i * math.pi / 6 for i in range(12)])],
         shade(color, 1.25), "#10151D", 1.2, True)                                                          # helmet
    poly(_rect(24, 0, 2.8, 5), "#FFF1B8", "#E5C76B", 1)                                                   # headlight
    poly(_rect(-24, 0, 2.4, 4.4), "#FF3B4A", "#9B1C28", 1)                                                # tail light
