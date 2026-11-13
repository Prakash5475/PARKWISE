"""Reusable premium widgets built on CustomTkinter + raw Canvas."""
import math
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from gui import theme as T
from gui.theme import font


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", T.PANEL)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.LINE)
        super().__init__(master, **kw)


def card_title(parent, text, sub=None, pad=(18, 0)):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(f, text=text, font=font(14, "bold"), text_color=T.TEXT).pack(anchor="w")
    if sub:
        ctk.CTkLabel(f, text=sub, font=font(11), text_color=T.MUTED).pack(anchor="w")
    return f


def button(parent, text, command, kind="secondary", icon=None, width=None, height=36, **kw):
    styles = {
        "primary": dict(fg_color=T.CYAN, hover_color="#5FE3F5", text_color="#06222A"),
        "secondary": dict(fg_color=T.PANEL2, hover_color="#22304D", text_color=T.TEXT,
                          border_width=1, border_color=T.LINE),
        "danger": dict(fg_color="#3A1C25", hover_color="#54222E", text_color="#FF9AA3",
                       border_width=1, border_color="#5B2A36"),
        "success": dict(fg_color="#12382A", hover_color="#18503A", text_color="#7BE8B2",
                        border_width=1, border_color="#1D5A41"),
        "ghost": dict(fg_color="transparent", hover_color=T.PANEL2, text_color=T.MUTED),
    }[kind]
    opts = dict(text=text, command=command, height=height, corner_radius=9, font=font(12, "bold"),
                image=icon, compound="left")
    if width:
        opts["width"] = width
    opts.update(styles)
    opts.update(kw)
    return ctk.CTkButton(parent, text_color_disabled="#5C6B85", **opts)


def entry(parent, placeholder="", width=200, **kw):
    return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, height=36, corner_radius=9,
                        fg_color=T.PANEL2, border_color=T.LINE, text_color=T.TEXT,
                        placeholder_text_color=T.DIM, font=font(12), **kw)


def option(parent, values, width=160, command=None, **kw):
    o = ctk.CTkOptionMenu(parent, values=values, width=width, height=36, corner_radius=9, fg_color=T.PANEL2,
                          button_color="#22304D", button_hover_color="#2B3C5E", text_color=T.TEXT,
                          dropdown_fg_color=T.PANEL2, dropdown_text_color=T.TEXT,
                          dropdown_hover_color="#22304D", font=font(12), dropdown_font=font(12),
                          command=command, **kw)
    return o


def segmented(parent, values, command=None, width=None, **kw):
    return ctk.CTkSegmentedButton(parent, values=values, command=command, height=34, corner_radius=9,
                                  fg_color=T.PANEL2, selected_color="#1E4A78", selected_hover_color="#245A92",
                                  unselected_color=T.PANEL2, unselected_hover_color="#22304D",
                                  text_color=T.TEXT, font=font(12, "bold"), **kw)


def switch(parent, text, command=None, **kw):
    return ctk.CTkSwitch(parent, text=text, command=command, font=font(12), text_color=T.TEXT,
                         progress_color=T.CYAN, button_color="#DCE6F5", button_hover_color="#FFFFFF",
                         fg_color="#2A3650", **kw)


class Pill(ctk.CTkLabel):
    """Small status chip."""
    def __init__(self, master, text="", color=T.MUTED, **kw):
        super().__init__(master, text=text, font=font(11, "bold"), corner_radius=99, height=22,
                         padx=10, **kw)
        self.set(text, color)

    def set(self, text, color):
        self.configure(text=f"  {text}  ", text_color=color, fg_color=_tint(color))


def _tint(hexc, a=0.16, base=(17, 24, 39)):
    h = hexc.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#%02x%02x%02x" % tuple(int(base[i] * (1 - a) + c * a) for i, c in enumerate((r, g, b)))


tint = _tint


class KPI(Card):
    """A metric tile: label, big value, optional sub-text, accent bar."""
    def __init__(self, master, title, accent=T.CYAN, value="-", sub=""):
        super().__init__(master)
        self.accent = accent
        bar = ctk.CTkFrame(self, width=3, height=34, corner_radius=2, fg_color=accent)
        bar.place(x=0, y=18)
        ctk.CTkLabel(self, text=title.upper(), font=font(10, "bold"), text_color=T.MUTED).pack(anchor="w", padx=18, pady=(14, 0))
        self.value = ctk.CTkLabel(self, text=value, font=font(26, "bold"), text_color=T.TEXT)
        self.value.pack(anchor="w", padx=18)
        self.sub = ctk.CTkLabel(self, text=sub, font=font(11), text_color=T.MUTED)
        self.sub.pack(anchor="w", padx=18, pady=(0, 13))

    def set(self, value, sub=None, color=None):
        if self.value.cget("text") != str(value):
            self.value.configure(text=str(value))
        if color:
            self.value.configure(text_color=color)
        if sub is not None and self.sub.cget("text") != sub:
            self.sub.configure(text=sub)


class Gauge(tk.Canvas):
    """Ring gauge for facility occupancy with segmented tick marks."""
    def __init__(self, master, size=190, **kw):
        super().__init__(master, width=size, height=size, bg=T.PANEL, highlightthickness=0, **kw)
        self.size, self._last = size, None

    def set(self, percent, caption="occupied"):
        key = (round(percent, 1), caption)
        if key == self._last:
            return
        self._last = key
        self.delete("all")
        s, pad = self.size, 14
        box = (pad, pad, s - pad, s - pad)
        self.create_arc(*box, start=225, extent=-270, style="arc", outline="#1E2A44", width=14)
        color = T.GREEN if percent < 60 else T.AMBER if percent < 85 else T.RED
        if percent > 0:
            self.create_arc(*box, start=225, extent=-270 * min(percent, 100) / 100, style="arc",
                            outline=color, width=14)
        self.create_text(s / 2, s / 2 - 6, text=f"{percent:.0f}%", fill=T.TEXT, font=T.tkfont_tuple(30, "bold"))
        self.create_text(s / 2, s / 2 + 24, text=caption, fill=T.MUTED, font=T.tkfont_tuple(10))


class StatusBar(tk.Canvas):
    """Horizontal stacked bar (occupied / incoming / reserved / free)."""
    def __init__(self, master, height=10, **kw):
        super().__init__(master, height=height, bg=T.PANEL, highlightthickness=0, **kw)
        self.vals = (0, 0, 0, 1)
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, occupied, incoming, reserved, free):
        if (occupied, incoming, reserved, free) != self.vals:
            self.vals = (occupied, incoming, reserved, free)
            self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        tot = sum(self.vals) or 1
        self.create_rectangle(0, 0, w, h, fill="#1A2540", outline="")
        x = 0
        for v, c in zip(self.vals, (T.RED, T.CYAN, T.AMBER, T.GREEN)):
            ww = w * v / tot
            if v:
                self.create_rectangle(x, 0, x + ww, h, fill=c if c != T.GREEN else "#1F7A52", outline="")
            x += ww


def setup_tree_style(master):
    st = ttk.Style(master)
    st.theme_use("clam")
    st.configure("PW.Treeview", background=T.PANEL, fieldbackground=T.PANEL, foreground=T.TEXT,
                 borderwidth=0, rowheight=34, font=T.tkfont_tuple(10))
    st.configure("PW.Treeview.Heading", background="#0F1730", foreground=T.MUTED, relief="flat",
                 font=T.tkfont_tuple(9, "bold"), padding=(10, 9), borderwidth=0)
    st.layout("PW.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.map("PW.Treeview", background=[("selected", "#1B3A66")], foreground=[("selected", "#FFFFFF")])
    st.map("PW.Treeview.Heading", background=[("active", "#16213F")])
    st.configure("PW.Vertical.TScrollbar", background="#1E2A44", troughcolor=T.PANEL, bordercolor=T.PANEL,
                 arrowcolor=T.PANEL, lightcolor="#1E2A44", darkcolor="#1E2A44", gripcount=0, width=9)
    st.map("PW.Vertical.TScrollbar", background=[("active", "#34476E")])


class Table(ctk.CTkFrame):
    """Styled Treeview with scrollbar, zebra rows, incremental updates and empty state."""
    def __init__(self, master, columns, empty_text="No data yet", **kw):
        super().__init__(master, fg_color=T.PANEL, corner_radius=12, **kw)
        self.columns = columns            # list of (key, title, width, anchor)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings",
                                 style="PW.Treeview", selectmode="browse")
        self.tree.configure(takefocus=False)
        for key, title, w, anchor in columns:
            self.tree.heading(key, text=title.upper())
            self.tree.column(key, width=w, anchor=anchor, stretch=True, minwidth=40)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style="PW.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 4))
        self.tree.tag_configure("odd", background="#0F1829")
        self.tree.tag_configure("even", background=T.PANEL)
        self.empty = ctk.CTkLabel(self, text=empty_text, font=font(13), text_color=T.DIM)
        self._tags = {}

    def tag_color(self, tag, fg):
        self.tree.tag_configure(tag, foreground=fg)

    def set_rows(self, rows):
        """rows: list of (iid, values, tag|None). Updates in place to keep selection/scroll."""
        want = [r[0] for r in rows]
        have = list(self.tree.get_children())
        for iid in have:
            if iid not in want:
                self.tree.delete(iid)
        for i, (iid, values, tag) in enumerate(rows):
            tags = ("odd" if i % 2 else "even",) + ((tag,) if tag else ())
            if self.tree.exists(iid):
                if tuple(self.tree.item(iid, "values")) != tuple(str(v) for v in values):
                    self.tree.item(iid, values=values)
                self.tree.item(iid, tags=tags)
                if self.tree.index(iid) != i:
                    self.tree.move(iid, "", i)
            else:
                self.tree.insert("", i, iid=iid, values=values, tags=tags)
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def selected(self):
        s = self.tree.selection()
        return s[0] if s else None


class Toast:
    """Non-blocking notification in the bottom-right corner."""
    def __init__(self, root):
        self.root, self._after = root, None
        self.frame = ctk.CTkFrame(root, corner_radius=12, fg_color=T.PANEL2, border_width=1, border_color=T.LINE)
        self.bar = ctk.CTkFrame(self.frame, width=4, corner_radius=2, fg_color=T.CYAN)
        self.bar.pack(side="left", fill="y", padx=(8, 0), pady=8)
        self.label = ctk.CTkLabel(self.frame, text="", font=font(12), text_color=T.TEXT, justify="left", wraplength=340)
        self.label.pack(side="left", padx=14, pady=12)

    def show(self, message, kind="info", ms=3800):
        color = {"info": T.CYAN, "success": T.GREEN, "warning": T.AMBER, "error": T.RED}[kind]
        self.bar.configure(fg_color=color)
        self.label.configure(text=message)
        self.frame.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        self.frame.lift()
        if self._after:
            self.root.after_cancel(self._after)
        self._after = self.root.after(ms, self.frame.place_forget)


def confirm(parent, title, message, confirm_text="Confirm", danger=False):
    """Modal confirmation dialog. Returns True / False."""
    top = ctk.CTkToplevel(parent)
    top.title(title)
    top.configure(fg_color=T.PANEL)
    top.resizable(False, False)
    top.transient(parent.winfo_toplevel())
    result = {"v": False}
    ctk.CTkLabel(top, text=title, font=font(16, "bold"), text_color=T.TEXT).pack(anchor="w", padx=26, pady=(24, 6))
    ctk.CTkLabel(top, text=message, font=font(12), text_color=T.MUTED, justify="left", wraplength=380).pack(anchor="w", padx=26)
    row = ctk.CTkFrame(top, fg_color="transparent")
    row.pack(fill="x", padx=26, pady=22)

    def done(v):
        result["v"] = v
        top.grab_release()
        top.destroy()

    button(row, confirm_text, lambda: done(True), "danger" if danger else "primary", width=120).pack(side="right")
    button(row, "Cancel", lambda: done(False), "secondary", width=100).pack(side="right", padx=8)
    top.protocol("WM_DELETE_WINDOW", lambda: done(False))
    top.update_idletasks()
    p = parent.winfo_toplevel()
    top.geometry(f"+{p.winfo_rootx() + (p.winfo_width() - top.winfo_width()) // 2}"
                 f"+{p.winfo_rooty() + (p.winfo_height() - top.winfo_height()) // 3}")
    top.after(60, lambda: (top.grab_set(), top.focus_force()))
    parent.wait_window(top)
    return result["v"]


def field_label(parent, text):
    return ctk.CTkLabel(parent, text=text, font=font(11, "bold"), text_color=T.MUTED, anchor="w")
