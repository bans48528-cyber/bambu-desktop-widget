import sys
import tkinter as tk


def main():
    job_name = "Bambu"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        job_name = sys.argv[1].strip()

    root = tk.Tk()
    root.title("打印完成")
    root.configure(bg="#0f172a")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width = 320
    height = 150
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max(0, screen_width - width - 28)
    y = max(0, screen_height - height - 72)
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(root, bg="#0f172a", padx=18, pady=16)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="打印完成",
        bg="#0f172a",
        fg="#dcfce7",
        font=("Microsoft YaHei UI", 14, "bold"),
    ).pack(anchor="w")

    tk.Label(
        frame,
        text=job_name,
        bg="#0f172a",
        fg="#cbd5e1",
        font=("Microsoft YaHei UI", 10),
        wraplength=280,
        justify="left",
    ).pack(anchor="w", pady=(8, 0))

    tk.Button(
        frame,
        text="知道了",
        command=root.destroy,
        bg="#10b981",
        fg="#04130c",
        activebackground="#34d399",
        activeforeground="#04130c",
        relief="flat",
        font=("Microsoft YaHei UI", 9, "bold"),
        padx=14,
        pady=5,
    ).pack(anchor="e", pady=(16, 0))

    root.after(20000, root.destroy)
    root.after(200, root.lift)
    root.mainloop()


if __name__ == "__main__":
    main()
