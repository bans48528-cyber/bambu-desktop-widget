import tkinter as tk
from tkinter import messagebox

from bambu_core import CONFIG_PATH, ConfigError, load_config, update_config


def main():
    try:
        config = load_config()
    except ConfigError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("配置错误", str(exc), parent=root)
        root.destroy()
        return

    root = tk.Tk()
    root.title("Bambu 挂件配置")
    root.configure(bg="#0f172a")
    root.resizable(False, True)
    root.geometry("420x440")

    actions = tk.Frame(root, bg="#0f172a")
    actions.pack(side="bottom", fill="x", padx=18, pady=(8, 16))

    body = tk.Frame(root, bg="#0f172a")
    body.pack(fill="both", expand=True, padx=18, pady=16)
    body.columnconfigure(1, weight=1)

    title = tk.Label(body, text="打印机连接", bg="#0f172a", fg="#f8fafc", font=("Microsoft YaHei UI", 13, "bold"))
    title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    printer_ip = tk.StringVar(value=config.get("printer_ip", ""))
    serial = tk.StringVar(value=config.get("serial", ""))
    access_code = tk.StringVar(value=config.get("access_code", ""))
    printer_name = tk.StringVar(value=config.get("printer_name", "Bambu"))
    opacity = tk.StringVar(value=str(config.get("opacity", 0.94)))
    font_size = tk.StringVar(value=str(config.get("font_size", 14)))
    remaining_time_unit = tk.StringVar(value=config.get("remaining_time_unit", "minutes"))
    show_access = tk.BooleanVar(value=False)

    def field(row, label, variable, show=None):
        tk.Label(body, text=label, bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9)).grid(row=row, column=0, sticky="w", pady=6)
        entry = tk.Entry(body, textvariable=variable, show=show, bg="#111827", fg="#f8fafc",
                         insertbackground="#f8fafc", relief="flat", font=("Segoe UI", 10))
        entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=5)
        return entry

    field(1, "打印机 IP", printer_ip)
    field(2, "序列号", serial)
    access_entry = field(3, "访问码", access_code, show="*")
    field(4, "显示名称", printer_name)

    tk.Label(body, text="剩余时间单位", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9)).grid(row=5, column=0, sticky="w", pady=6)
    unit_menu = tk.OptionMenu(body, remaining_time_unit, "minutes", "seconds", "auto")
    unit_menu.configure(bg="#111827", fg="#f8fafc", activebackground="#1f2937", activeforeground="#f8fafc", relief="flat", highlightthickness=0)
    unit_menu["menu"].configure(bg="#111827", fg="#f8fafc", activebackground="#1f2937")
    unit_menu.grid(row=5, column=1, sticky="ew", pady=6)

    field(6, "透明度 0.3-1.0", opacity)

    tk.Label(body, text="基础字号 5-30", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9)).grid(row=7, column=0, sticky="w", pady=6)
    font_size_input = tk.Spinbox(body, from_=5, to=30, increment=1, textvariable=font_size,
                                 bg="#111827", fg="#f8fafc", buttonbackground="#1f2937",
                                 insertbackground="#f8fafc", relief="flat", font=("Segoe UI", 10))
    font_size_input.grid(row=7, column=1, sticky="ew", pady=6, ipady=4)

    def toggle_access():
        access_entry.configure(show="" if show_access.get() else "*")

    tk.Checkbutton(body, text="显示访问码", variable=show_access, command=toggle_access,
                   bg="#0f172a", fg="#cbd5e1", selectcolor="#111827",
                   activebackground="#0f172a", activeforeground="#f8fafc",
                   font=("Microsoft YaHei UI", 9)).grid(row=8, column=1, sticky="w", pady=(4, 0))

    hint = tk.Label(body, text=f"保存后会写入 {CONFIG_PATH.name}，主窗口会自动重载。", bg="#0f172a", fg="#94a3b8",
                    font=("Microsoft YaHei UI", 8))
    hint.grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 8))

    def save_and_close():
        try:
            alpha = float(opacity.get())
        except ValueError:
            messagebox.showerror("配置错误", "透明度必须是数字。", parent=root)
            return
        if not 0.3 <= alpha <= 1.0:
            messagebox.showerror("配置错误", "透明度范围是 0.3 到 1.0。", parent=root)
            return
        try:
            base_font_size = int(font_size.get())
        except ValueError:
            messagebox.showerror("配置错误", "字号必须是整数。", parent=root)
            return
        if not 5 <= base_font_size <= 30:
            messagebox.showerror("配置错误", "字号范围是 5 到 30。", parent=root)
            return
        if not printer_ip.get().strip() or not serial.get().strip() or not access_code.get().strip():
            messagebox.showerror("配置错误", "打印机 IP、序列号和访问码不能为空。", parent=root)
            return

        def apply_changes(updated):
            updated["printer_ip"] = printer_ip.get().strip()
            updated["serial"] = serial.get().strip()
            updated["access_code"] = access_code.get().strip()
            updated["printer_name"] = printer_name.get().strip() or "Bambu"
            updated["remaining_time_unit"] = remaining_time_unit.get()
            updated["opacity"] = alpha
            updated["font_size"] = base_font_size

        try:
            update_config(apply_changes)
        except ConfigError as exc:
            messagebox.showerror("配置错误", str(exc), parent=root)
            return
        root.destroy()

    cancel = tk.Button(actions, text="取消", command=root.destroy, bg="#1f2937", fg="#e5e7eb",
                       activebackground="#374151", activeforeground="#f8fafc", relief="flat",
                       font=("Microsoft YaHei UI", 9), padx=16, pady=6)
    save = tk.Button(actions, text="保存", command=save_and_close, bg="#10b981", fg="#04130c",
                     activebackground="#34d399", activeforeground="#04130c", relief="flat",
                     font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=6, default="active")
    save.pack(side="right")
    cancel.pack(side="right", padx=(0, 8))

    root.bind("<Escape>", lambda _event: root.destroy())
    root.bind("<Return>", lambda _event: save_and_close())
    root.bind("<Control-s>", lambda _event: save_and_close())
    root.update_idletasks()
    required_height = min(root.winfo_screenheight() - 80, max(440, root.winfo_reqheight()))
    root.minsize(420, required_height)
    root.geometry(f"420x{required_height}")
    access_entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
