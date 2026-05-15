Import customtkinter as ctk
import subprocess
import os
import threading
import json
import requests
import zipfile
import shutil
import sys
import uuid
import time
import base64
import zlib
import marshal

def _ensure_deps():
    req = {"minecraft_launcher_lib": "minecraft-launcher-lib", "PIL": "pillow"}
    for mod, pkg in req.items():
        try: __import__(mod)
        except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])

_ensure_deps()
import minecraft_launcher_lib
from PIL import Image, ImageDraw, ImageTk

WIN_BG = "#191919"           
WIN_SIDEBAR = "#202020"      
WIN_STATUS = "#1E1E1E"       
WIN_TEXT = "#FFFFFF"         
WIN_MUTED = "#AAAAAA"        
WIN_ACCENT = "#FFA54C"       
WIN_HOVER = "#2D2D2D"        
WIN_BORDER = "#333333"       

LANG_DATA = {
    "EN": {
        "title": "Extension.P Launcher", "launch": "LAUNCH", "working": "WORKING...",
        "folder": "FOLDER", "setting": "SETTINGS", "account": "ACCOUNT",
        "ready": "READY", "out": "OUTPUT", "ram": "ALLOCATED RAM", 
        "save": "SAVE CONFIG", "res": "RESOLUTION", "fs": "FULLSCREEN", "java": "CUSTOM JAVA PATH",
        "terminal": "TERMINAL"
    }
}

VERSION = "1.21.1" 
ctk.set_appearance_mode("dark")

def generate_p_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 10, 54, 54), radius=12, fill=WIN_ACCENT)
    draw.rounded_rectangle((22, 22, 42, 42), radius=6, fill=WIN_SIDEBAR)
    return img

class JavaEngine:
    def __init__(self, root, log_callback): 
        self.root = root
        self.log = log_callback

    def get_path(self):
        if not os.path.exists(self.root): return None
        for r, d, files in os.walk(self.root):
            for file in files:
                if file.lower() == "java.exe":
                    return os.path.abspath(os.path.join(r, file))
        sys_j = shutil.which("java.exe") or shutil.which("java")
        return os.path.abspath(sys_j) if sys_j else None

    def provision(self):
        self.log("[JavaEngine/INFO]: Downloading Runtime...")
        url = "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse?project=jdk"
        zip_p = os.path.join(self.root, "runtime.zip")
        try:
            os.makedirs(self.root, exist_ok=True)
            r = requests.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with open(zip_p, "wb") as f:
                for chunk in r.iter_content(8192): 
                    if chunk: f.write(chunk)
            self.log("[JavaEngine/INFO]: Extracting Runtime...")
            with zipfile.ZipFile(zip_p, 'r') as z: 
                z.extractall(self.root)
            os.remove(zip_p)
            self.log("[JavaEngine/INFO]: Runtime provisioned successfully.")
        except Exception as e:
            self.log(f"[JavaEngine/ERROR]: Failed to provision Java: {e}")

class PLAManager:
    def __init__(self, app):
        self.app = app
        self.base_dir = self.app.base_dir
        self.plugins_dir = os.path.join(self.base_dir, "plugins")
        self.store_api_url = "https://api.github.com/repos/ScriptArchitector/PLA/releases/latest"
        os.makedirs(self.plugins_dir, exist_ok=True)

    def _check_auth(self):
        creator_file = os.path.join(self.app.base_dir, "creator.json")
        if os.path.exists(creator_file):
            try:
                with open(creator_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if str(data.get("Pla manager app", "")).lower() == "true":
                        return True
            except: pass
        return False

    def sync_critical_updates(self):
        try:
            response = requests.get(self.store_api_url, timeout=10)
            if response.status_code == 200:
                assets = response.json().get("assets", [])
                for asset in assets:
                    name = asset["name"]
                    if name.endswith("3.pla") and not os.path.exists(os.path.join(self.plugins_dir, name)):
                        r = requests.get(asset["browser_download_url"], stream=True)
                        if r.status_code == 200:
                            with open(os.path.join(self.plugins_dir, name), "wb") as f:
                                for chunk in r.iter_content(8192): f.write(chunk)
                            self.app.write_log(f"[PLA Manager]: Critical update fetched -> {name}")
        except: pass

    def load_plugins(self):
        for file in os.listdir(self.plugins_dir):
            if file.endswith(".pla"):
                try:
                    with open(os.path.join(self.plugins_dir, file), "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        raw_data = "".join(l for l in lines if not l.startswith("#")).strip()
                    plugin_namespace = {}
                    exec(marshal.loads(zlib.decompress(base64.b85decode(raw_data))), plugin_namespace)
                    if "main" in plugin_namespace:
                        self.app.after(0, plugin_namespace["main"], self.app)
                except Exception as e:
                    self.app.write_log(f"[PLA Manager/ERROR]: Module hook failed -> {file}")

    def run(self):
        if not self._check_auth():
            return
        self.app.write_log("[PLA Manager]: Core initialized. Secure mode active.")
        self.sync_critical_updates()
        self.load_plugins()

class PLAStore(ctk.CTkToplevel):
    def __init__(self, app_master):
        super().__init__(app_master)
        self.app = app_master
        self.title("PLA Store")
        self.geometry("500x650")
        self.attributes("-topmost", True)
        self.configure(fg_color=WIN_BG)
        
        ctk.CTkLabel(self, text="PLUGIN STORE", font=("Segoe UI", 18, "bold"), text_color=WIN_ACCENT).pack(pady=(20, 5))
        self.status_lbl = ctk.CTkLabel(self, text="Connecting...", font=("Segoe UI", 11), text_color=WIN_MUTED)
        self.status_lbl.pack(pady=(0, 10))
        
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.api_url = "https://api.github.com/repos/ScriptArchitector/PLA/releases/latest"
        threading.Thread(target=self.fetch, daemon=True).start()

    def fetch(self):
        try:
            r = requests.get(self.api_url, timeout=10)
            if r.status_code == 200:
                self.app.after(0, lambda: self.status_lbl.configure(text="Connected."))
                for asset in r.json().get("assets", []):
                    name = asset["name"]
                    if name.endswith("1.pla") or name.endswith("2.pla"):
                        url = asset["browser_download_url"]
                        self.app.after(0, lambda n=name, u=url: self.build_item(n, u))
            else:
                self.app.after(0, lambda: self.status_lbl.configure(text="API Error."))
        except:
            self.app.after(0, lambda: self.status_lbl.configure(text="Network Error."))

    def build_item(self, name, url):
        frame = ctk.CTkFrame(self.scroll_frame, fg_color=WIN_HOVER, corner_radius=6)
        frame.pack(fill="x", pady=5)
        
        disp_name = name.replace(".pla", "")[:-1]
        
        ctk.CTkLabel(frame, text=disp_name, font=("Segoe UI", 13, "bold"), text_color=WIN_TEXT).pack(side="left", padx=15, pady=15)
        if name.endswith("2.pla"):
            ctk.CTkLabel(frame, text="RECOMMENDED", font=("Segoe UI", 10, "bold"), text_color="#D93838").pack(side="left")
        
        target_path = os.path.join(self.app.base_dir, "plugins", name)
        if os.path.exists(target_path):
            ctk.CTkButton(frame, text="INSTALLED", width=80, fg_color=WIN_BORDER, state="disabled").pack(side="right", padx=15)
        else:
            btn = ctk.CTkButton(frame, text="INSTALL", width=80, fg_color=WIN_ACCENT, text_color="black")
            btn.configure(command=lambda b=btn, n=name, u=url: self.download_plugin(b, n, u))
            btn.pack(side="right", padx=15)

    def download_plugin(self, btn, name, url):
        btn.configure(state="disabled", text="WORKING...")
        def _dl():
            try:
                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(os.path.join(self.app.base_dir, "plugins", name), "wb") as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                    self.app.after(0, lambda: btn.configure(text="RESTART", fg_color=WIN_BORDER))
                else:
                    self.app.after(0, lambda: btn.configure(state="normal", text="ERROR"))
            except:
                self.app.after(0, lambda: btn.configure(state="normal", text="ERROR"))
        threading.Thread(target=_dl, daemon=True).start()

class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        appdata_base = os.getenv("APPDATA") or os.path.expanduser("~")
        self.base_dir = os.path.join(appdata_base, ".p_launcher")
        self.cfg_path = os.path.join(self.base_dir, "engine_settings.json")
        self.log_cfg_path = os.path.join(self.base_dir, "log.json")
        self.rt_dir = os.path.join(self.base_dir, "runtime")
        self.mods_dir = os.path.join(self.base_dir, "mods")
        
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.rt_dir, exist_ok=True)
        os.makedirs(self.mods_dir, exist_ok=True)
        with open(os.path.join(self.base_dir, "creator.json"), "w") as f: json.dump({"Pla manager app": "true"}, f)

        self.cfg = self.load_cfg()
        self.log_cfg = self.load_log_cfg()
        
        self.title(LANG_DATA["EN"]["title"])
        self.geometry("1100x650")
        self.configure(fg_color=WIN_BG)
        
        self.app_icon = ImageTk.PhotoImage(generate_p_icon())
        self.iconphoto(True, self.app_icon)

        self.java_engine = JavaEngine(self.rt_dir, self.write_log)
        self.max_progress = 1
        self.debug_mode = False
        self.debug_console = None

        self.setup_ui()
        self.apply_terminal_mode()
        
        threading.Thread(target=PLAManager(self).run, daemon=True).start()

    def load_cfg(self):
        defaults = {"nickname": "Player", "saved_accounts": ["Player"], "ram_gb": 4, "res": "1280x720", "fs": False, "java_path": "", "terminal_mode": False}
        if os.path.exists(self.cfg_path):
            try:
                with open(self.cfg_path, "r", encoding="utf-8") as f: return {**defaults, **json.load(f)}
            except: pass
        return defaults

    def load_log_cfg(self):
        defaults = {"AllowTerminal": False}
        if os.path.exists(self.log_cfg_path):
            try:
                with open(self.log_cfg_path, "r", encoding="utf-8") as f: return {**defaults, **json.load(f)}
            except: pass
        return defaults

    def save_cfg(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f: json.dump(self.cfg, f, indent=4)

    def compile_pla(self, source_path):
        try:
            if not os.path.exists(source_path):
                self.write_log(f"[Compiler/ERROR]: File not found -> {source_path}")
                return
            with open(source_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            code_obj = compile(source_code, '<string>', 'exec')
            marshaled = marshal.dumps(code_obj)
            compressed = zlib.compress(marshaled)
            encoded = base64.b85encode(compressed).decode('utf-8')
            
            out_path = source_path.replace(".py", ".pla")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("# EXTENSION.P COMPILED MODULE\n" + encoded)
            self.write_log(f"[Compiler/INFO]: Successfully compiled to -> {os.path.basename(out_path)}")
        except Exception as e:
            self.write_log(f"[Compiler/ERROR]: Build failed -> {str(e)}")

    def setup_ui(self):
        t = LANG_DATA["EN"]
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, fg_color=WIN_SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text=t["title"], font=("Segoe UI", 16, "bold"), text_color=WIN_ACCENT).pack(pady=(25, 20))
        
        ctk.CTkButton(sidebar, text=f" {t['folder']}", fg_color="transparent", text_color=WIN_TEXT, hover_color=WIN_HOVER, anchor="w", font=("Segoe UI", 13), command=lambda: os.startfile(self.base_dir)).pack(fill="x", padx=5, pady=2)
        ctk.CTkButton(sidebar, text=f" {t['setting']}", fg_color="transparent", text_color=WIN_TEXT, hover_color=WIN_HOVER, anchor="w", font=("Segoe UI", 13), command=self.open_settings).pack(fill="x", padx=5, pady=2)
        
        main_area = ctk.CTkFrame(self, fg_color=WIN_BG, corner_radius=0)
        main_area.grid(row=0, column=1, sticky="nsew")

        action_bar = ctk.CTkFrame(main_area, height=65, fg_color=WIN_BG, corner_radius=0)
        action_bar.pack(fill="x", padx=15, pady=15)

        acc_frame = ctk.CTkFrame(action_bar, fg_color="transparent")
        acc_frame.pack(side="left")
        ctk.CTkLabel(acc_frame, text=f"{t['account']}:", font=("Segoe UI", 14), text_color=WIN_TEXT).grid(row=0, column=0, padx=(0, 10))
        
        self.account_combo = ctk.CTkComboBox(acc_frame, width=150, height=35, values=self.cfg.get("saved_accounts", []))
        self.account_combo.grid(row=0, column=1, padx=(0, 10))
        self.account_combo.set(self.cfg["nickname"])

        self.launch_btn = ctk.CTkButton(action_bar, text=f"{t['launch']}", width=140, height=35, font=("Segoe UI", 14, "bold"), fg_color=WIN_ACCENT, hover_color="#CC7A00", text_color="black", command=self.start_launch)
        self.launch_btn.pack(side="right")

        log_container = ctk.CTkFrame(main_area, fg_color="transparent")
        log_container.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.log_box = ctk.CTkTextbox(log_container, font=("Consolas", 11), text_color=WIN_TEXT, fg_color="transparent", corner_radius=0)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

        self.term_entry = ctk.CTkEntry(log_container, font=("Consolas", 12), fg_color=WIN_STATUS, border_color=WIN_BORDER, placeholder_text="Enter launcher command...")
        self.term_entry.bind("<Return>", self.handle_terminal_cmd)
        
        statusbar = ctk.CTkFrame(self, height=28, fg_color=WIN_STATUS, corner_radius=0)
        statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.ps_status = ctk.CTkLabel(statusbar, text=t["ready"], font=("Segoe UI", 11), text_color=WIN_MUTED)
        self.ps_status.pack(side="left", padx=10)
        self.ps_bar = ctk.CTkProgressBar(statusbar, width=150, height=8, progress_color=WIN_ACCENT, fg_color="#333333", corner_radius=0)
        self.ps_bar.pack(side="right", padx=15, pady=10)
        self.ps_bar.set(0)

    def set_max_progress(self, max_val):
        self.max_progress = max_val if max_val > 0 else 1

    def update_progress(self, progress):
        self.after(0, lambda: self.ps_bar.set(progress / self.max_progress))

    def write_log(self, text):
        self.after(0, self._write_log_safe, text)

    def _write_log_safe(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def apply_terminal_mode(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        if self.cfg.get("terminal_mode") and self.log_cfg.get("AllowTerminal"):
            self.term_entry.pack(fill="x", pady=(5, 0))
            self.log_box.insert("end", "Extension.P Terminal Active. Type '--help' for list.\n")
        else:
            self.term_entry.pack_forget()
            self.log_box.insert("end", "[Launcher/INFO]: Standing by.\n")
        self.log_box.configure(state="disabled")

    def handle_terminal_cmd(self, event):
        cmd = self.term_entry.get().strip()
        self.term_entry.delete(0, "end")
        if not cmd: return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"> {cmd}\n")
        
        args = cmd.split()
        base = args[0].lower()

        if base in ["--help", "--list"]:
            self.log_box.insert("end", "Commands:\n--mods\n--memory [GB]\n--nick [Name]\n--reset\n--install-fabric\n--compile [path.py]\n--clear\n--exit\n")
        elif base == "--mods":
            os.startfile(self.mods_dir)
        elif base == "--memory" and len(args) > 1:
            self.cfg["ram_gb"] = int(args[1])
            self.save_cfg(); self.log_box.insert("end", f"RAM set to {args[1]}GB\n")
        elif base == "--nick" and len(args) > 1:
            self.cfg["nickname"] = args[1]; self.account_combo.set(args[1])
            self.save_cfg(); self.log_box.insert("end", f"Nick changed to {args[1]}\n")
        elif base == "--reset":
            self.cfg = {"nickname": "Player", "ram_gb": 4, "res": "1280x720"}; self.save_cfg()
            self.log_box.insert("end", "Config reset to defaults.\n")
        elif base == "--compile" and len(args) > 1:
            target_file = " ".join(args[1:])
            threading.Thread(target=self.compile_pla, args=(target_file,), daemon=True).start()
        elif base == "--clear":
            self.log_box.delete("1.0", "end")
        elif base == "--exit":
            self.destroy()
        elif base == "--install-fabric":
            def _install_fab():
                j = self.cfg.get("java_path", "").strip() or self.java_engine.get_path()
                if j: minecraft_launcher_lib.fabric.install_fabric(VERSION, self.base_dir, java=j)
            threading.Thread(target=_install_fab, daemon=True).start()
            self.log_box.insert("end", "Fabric installation started in background...\n")
        else:
            self.log_box.insert("end", "Unknown launcher command.\n")
        self.log_box.see("end"); self.log_box.configure(state="disabled")

    def open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Properties")
        win.geometry("400x570")
        win.attributes("-topmost", True)
        win.configure(fg_color=WIN_BG)
        t = LANG_DATA["EN"]
        
        tab_frame = ctk.CTkFrame(win, fg_color="#2D2D2D", height=30, corner_radius=0)
        tab_frame.pack(fill="x")
        ctk.CTkLabel(tab_frame, text="General Settings", font=("Segoe UI", 12, "bold")).pack(side="left", padx=15)

        content = ctk.CTkFrame(win, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(content, text=t["res"], font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 5))
        self.res_var = ctk.StringVar(value=self.cfg.get("res", "1280x720"))
        ctk.CTkOptionMenu(content, variable=self.res_var, values=["854x480", "1280x720", "1920x1080"], fg_color=WIN_ACCENT, button_color="#CC7A00").pack(fill="x", pady=(0, 15))

        self.fs_var = ctk.BooleanVar(value=self.cfg.get("fs", False))
        ctk.CTkSwitch(content, text=t["fs"], variable=self.fs_var, progress_color=WIN_ACCENT).pack(anchor="w", pady=(0, 15))

        if self.log_cfg.get("AllowTerminal", False):
            self.term_var = ctk.BooleanVar(value=self.cfg.get("terminal_mode", False))
            ctk.CTkSwitch(content, text=t["terminal"], variable=self.term_var, progress_color=WIN_ACCENT).pack(anchor="w", pady=(0, 15))

        ctk.CTkFrame(content, height=1, fg_color=WIN_BORDER).pack(fill="x", pady=10)

        ctk.CTkLabel(content, text=t["ram"], font=("Segoe UI", 13, "bold")).pack(anch
