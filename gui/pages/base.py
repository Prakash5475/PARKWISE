import customtkinter as ctk
from gui import theme as T


class Page(ctk.CTkFrame):
    """Base class for every page. The app calls update_data() about once per second
    while the page is visible, and on_show()/on_hide() when navigating."""
    key = ""
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.visible = False

    def on_show(self):
        self.visible = True
        self.update_data(self.app.get_snapshot())

    def on_hide(self):
        self.visible = False

    def update_data(self, snap):
        pass
