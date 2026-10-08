from __future__ import annotations

import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from translator_core import (
    ENGINES,
    TranslationCancelled,
    apply_translation,
    load_settings,
    resolve_data_folder,
    save_settings,
    translate_game,
)


COLORS = {
    "bg": "#0f1117",
    "card": "#181b24",
    "border": "#262a36",
    "input": "#11141b",
    "text": "#e6e8ee",
    "muted": "#8b91a1",
    "accent": "#7c5cff",
    "accent_hover": "#6a48f5",
    "accent_pressed": "#5a3ae0",
    "success": "#2ecc8f",
    "danger": "#ff5c7a",
    "button": "#242836",
    "button_hover": "#2e3344",
}

FONT = "Segoe UI"

SOURCE_LANGUAGES = {
    "Inglês": "en",
    "Espanhol": "es",
    "Japonês": "ja",
    "Francês": "fr",
    "Alemão": "de",
}

TARGET_LANGUAGES = {
    "Português": "pt",
    "Inglês": "en",
    "Espanhol": "es",
    "Francês": "fr",
    "Alemão": "de",
}


class TranslatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Tradutor RPG Maker MV")
        self.minsize(680, 440)
        height = min(560, self.winfo_screenheight() - 100)
        width = min(820, self.winfo_screenwidth() - 40)
        self.geometry(f"{width}x{height}+{(self.winfo_screenwidth() - width) // 2}+{max((self.winfo_screenheight() - height) // 2 - 30, 0)}")
        self.configure(bg=COLORS["bg"])
        self.cancel_event = threading.Event()
        self.messages: queue.Queue[tuple] = queue.Queue()
        self.last_output: Path | None = None
        self.settings = load_settings()

        self.game_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.from_var = tk.StringVar(value="Inglês")
        self.to_var = tk.StringVar(value="Português")
        self.status_var = tk.StringVar(value="Selecione a pasta do jogo para começar.")
        self.percent_var = tk.StringVar(value="0%")
        self.progress_var = tk.DoubleVar(value=0)
        self.engine_var = tk.StringVar(value=ENGINES[self.settings["engine"]].name)

        self._setup_style()
        self._build()
        self.after(100, self._poll_messages)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        c = COLORS

        style.configure(".", background=c["bg"], foreground=c["text"], font=(FONT, 10), borderwidth=0)
        style.configure("TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("Card.TLabel", background=c["card"], foreground=c["text"])
        style.configure("Title.TLabel", font=(FONT, 17, "bold"))
        style.configure("Subtitle.TLabel", foreground=c["muted"], font=(FONT, 10))
        style.configure("Section.TLabel", background=c["card"], foreground=c["muted"], font=(FONT, 9, "bold"))
        style.configure("Field.TLabel", background=c["card"], foreground=c["text"], font=(FONT, 10))
        style.configure("Status.TLabel", background=c["card"], foreground=c["text"], font=(FONT, 10))
        style.configure("Percent.TLabel", background=c["card"], foreground=c["accent"], font=(FONT, 10, "bold"))
        style.configure("Badge.TLabel", background=c["accent"], foreground="#ffffff", font=(FONT, 8, "bold"), padding=(8, 2))

        style.configure(
            "TEntry",
            fieldbackground=c["input"],
            foreground=c["text"],
            insertcolor=c["text"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=6,
        )
        style.map("TEntry", bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])])

        style.configure(
            "TCombobox",
            fieldbackground=c["input"],
            background=c["button"],
            foreground=c["text"],
            arrowcolor=c["text"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["input"])],
            foreground=[("readonly", c["text"])],
            selectbackground=[("readonly", c["input"])],
            selectforeground=[("readonly", c["text"])],
            bordercolor=[("focus", c["accent"])],
            background=[("active", c["button_hover"])],
        )
        self.option_add("*TCombobox*Listbox.background", c["card"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

        style.configure(
            "TButton",
            background=c["button"],
            foreground=c["text"],
            bordercolor=c["border"],
            lightcolor=c["button"],
            darkcolor=c["button"],
            focuscolor=c["button"],
            padding=(12, 5),
            font=(FONT, 10),
        )
        style.map(
            "TButton",
            background=[("disabled", c["card"]), ("pressed", c["border"]), ("active", c["button_hover"])],
            foreground=[("disabled", c["muted"])],
            lightcolor=[("active", c["button_hover"])],
            darkcolor=[("active", c["button_hover"])],
        )

        style.configure(
            "Accent.TButton",
            background=c["accent"],
            foreground="#ffffff",
            bordercolor=c["accent"],
            lightcolor=c["accent"],
            darkcolor=c["accent"],
            focuscolor=c["accent"],
            padding=(20, 7),
            font=(FONT, 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", c["button"]), ("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
            foreground=[("disabled", c["muted"])],
            bordercolor=[("disabled", c["border"])],
            lightcolor=[("disabled", c["button"]), ("active", c["accent_hover"])],
            darkcolor=[("disabled", c["button"]), ("active", c["accent_hover"])],
        )

        style.configure(
            "Danger.TButton",
            background=c["button"],
            foreground=c["danger"],
        )
        style.map(
            "Danger.TButton",
            background=[("disabled", c["card"]), ("active", c["button_hover"])],
            foreground=[("disabled", c["muted"])],
        )

        style.configure(
            "Card.TRadiobutton",
            background=c["card"],
            foreground=c["text"],
            font=(FONT, 10, "bold"),
            indicatorbackground=c["input"],
            indicatorforeground=c["accent"],
            indicatorrelief="flat",
            focuscolor=c["card"],
            padding=(0, 2),
        )
        style.map(
            "Card.TRadiobutton",
            background=[("active", c["card"])],
            indicatorbackground=[("selected", c["accent"]), ("active", c["button_hover"])],
        )
        style.configure("Hint.TLabel", background=c["card"], foreground=c["muted"], font=(FONT, 9))

        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=c["input"],
            background=c["accent"],
            bordercolor=c["input"],
            lightcolor=c["accent"],
            darkcolor=c["accent"],
            thickness=8,
        )

        style.configure(
            "Vertical.TScrollbar",
            background=c["button"],
            troughcolor=c["input"],
            bordercolor=c["input"],
            arrowcolor=c["muted"],
            lightcolor=c["button"],
            darkcolor=c["button"],
        )
        style.map("Vertical.TScrollbar", background=[("active", c["button_hover"])])

    def _card(self, parent: tk.Widget, title: str) -> ttk.Frame:
        border = tk.Frame(parent, bg=COLORS["border"])
        border.pack(fill="x", pady=(0, 10))
        card = ttk.Frame(border, style="Card.TFrame", padding=(16, 12))
        card.pack(fill="both", expand=True, padx=1, pady=1)
        ttk.Label(card, text=title.upper(), style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        return card

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=(20, 14))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        title_row = ttk.Frame(header)
        title_row.grid(row=0, column=0, sticky="w")
        ttk.Label(title_row, text="Tradutor RPG Maker MV", style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, text="OFFLINE", style="Badge.TLabel").pack(side="left", padx=(12, 0), pady=(4, 0))
        ttk.Label(
            header,
            text="Traduz diálogos e textos dos arquivos JSON, preservando os comandos do RPG Maker.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.settings_button = ttk.Button(header, text="⚙  Configurações", command=self._open_settings)
        self.settings_button.grid(row=0, column=1, rowspan=2, sticky="e")

        folders = self._card(outer, "Configuração")
        form = ttk.Frame(folders, style="Card.TFrame")
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Jogo", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 14), pady=3)
        ttk.Entry(form, textvariable=self.game_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(form, text="Procurar…", command=self._choose_game).grid(row=0, column=2, padx=(10, 0), pady=3)

        ttk.Label(form, text="Saída", style="Field.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 14), pady=3)
        ttk.Entry(form, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(form, text="Procurar…", command=self._choose_output).grid(row=1, column=2, padx=(10, 0), pady=3)

        ttk.Label(form, text="Idioma", style="Field.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 14), pady=3)
        languages = ttk.Frame(form, style="Card.TFrame")
        languages.grid(row=2, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Label(languages, text="De", style="Field.TLabel").pack(side="left")
        ttk.Combobox(
            languages,
            textvariable=self.from_var,
            values=list(SOURCE_LANGUAGES),
            width=14,
            state="readonly",
        ).pack(side="left", padx=(10, 14))
        ttk.Label(languages, text="→", style="Percent.TLabel").pack(side="left")
        ttk.Label(languages, text="Para", style="Field.TLabel").pack(side="left", padx=(14, 0))
        ttk.Combobox(
            languages,
            textvariable=self.to_var,
            values=list(TARGET_LANGUAGES),
            width=14,
            state="readonly",
        ).pack(side="left", padx=10)

        ttk.Label(form, text="Modelo", style="Field.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 14), pady=3)
        ttk.Label(form, textvariable=self.engine_var, style="Field.TLabel").grid(
            row=3, column=1, columnspan=2, sticky="w", pady=3
        )

        buttons = ttk.Frame(outer)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        self.start_button = ttk.Button(buttons, text="Traduzir", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            buttons, text="Cancelar", style="Danger.TButton", command=self.cancel_event.set, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=10)
        self.apply_button = ttk.Button(
            buttons, text="Aplicar ao jogo (com backup)", command=self._apply, state="disabled"
        )
        self.apply_button.pack(side="right")

        progress_border = tk.Frame(outer, bg=COLORS["border"])
        progress_border.pack(fill="both", expand=True)
        progress_card = ttk.Frame(progress_border, style="Card.TFrame", padding=(16, 12))
        progress_card.pack(fill="both", expand=True, padx=1, pady=1)

        status_row = ttk.Frame(progress_card, style="Card.TFrame")
        status_row.pack(fill="x", pady=(0, 6))
        ttk.Label(status_row, text="PROGRESSO", style="Section.TLabel").pack(side="left")
        ttk.Label(status_row, textvariable=self.percent_var, style="Percent.TLabel").pack(side="right")

        ttk.Progressbar(
            progress_card,
            variable=self.progress_var,
            maximum=100,
            style="Accent.Horizontal.TProgressbar",
        ).pack(fill="x")
        self.status_label = ttk.Label(progress_card, textvariable=self.status_var, style="Status.TLabel", wraplength=720)
        self.status_label.pack(anchor="w", pady=(6, 8))

        log_frame = tk.Frame(progress_card, bg=COLORS["border"])
        log_frame.pack(fill="both", expand=True)
        log_inner = tk.Frame(log_frame, bg=COLORS["input"])
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.log = tk.Text(
            log_inner,
            height=3,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            bg=COLORS["input"],
            fg=COLORS["muted"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=6,
        )
        scrollbar = ttk.Scrollbar(log_inner, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("success", foreground=COLORS["success"])
        self.log.tag_configure("error", foreground=COLORS["danger"])
        self.log.tag_configure("time", foreground=COLORS["accent"])

        progress_card.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(event.width - 40, 200)))

    def _set_status(self, text: str, kind: str = "normal") -> None:
        self.status_var.set(text)
        color = {"success": COLORS["success"], "error": COLORS["danger"]}.get(kind, COLORS["text"])
        self.status_label.configure(foreground=color)

    def _set_progress(self, value: float) -> None:
        self.progress_var.set(value)
        self.percent_var.set(f"{value:.0f}%")

    def _suggest_output(self, data: Path) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_var.set(str(data.parent / f"data_pt_{stamp}"))

    def load_game(self, selected: str) -> None:
        self.game_var.set(selected)
        try:
            data = resolve_data_folder(selected)
            self._suggest_output(data)
            self._set_status(f"Dados encontrados em: {data}", "success")
        except Exception as exc:
            self._set_status(str(exc), "error")

    def _choose_game(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta do jogo RPG Maker MV")
        if selected:
            self.load_game(selected)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Selecione onde criar a pasta traduzida", mustexist=True)
        if selected:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_var.set(str(Path(selected) / f"data_pt_{stamp}"))

    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", datetime.now().strftime("%H:%M:%S  "), "time")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self) -> None:
        try:
            data = resolve_data_folder(self.game_var.get())
        except Exception as exc:
            messagebox.showerror("Pasta inválida", str(exc))
            return
        output = self.output_var.get().strip()
        if not output:
            self._suggest_output(data)
            output = self.output_var.get()
        self.cancel_event.clear()
        self.settings_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.apply_button.configure(state="disabled")
        self._set_progress(0)
        self._set_status("Iniciando tradução…")
        self._append_log(f"Origem: {data}")
        self._append_log(f"Saída: {output}")
        engine_id = self.settings["engine"]
        self._append_log(f"Modelo: {ENGINES[engine_id].name}")
        from_code = SOURCE_LANGUAGES[self.from_var.get()]
        to_code = TARGET_LANGUAGES[self.to_var.get()]
        threading.Thread(
            target=self._worker, args=(data, output, from_code, to_code, engine_id), daemon=True
        ).start()

    def _worker(self, data: Path, output: str, from_code: str, to_code: str, engine_id: str) -> None:
        def progress(done: int, total: int, status: str) -> None:
            self.messages.put(("progress", done, total, status))
        try:
            result = translate_game(
                data,
                output,
                from_code,
                to_code,
                progress,
                self.cancel_event.is_set,
                engine_id=engine_id,
            )
            self.messages.put(("done", *result))
        except TranslationCancelled:
            self.messages.put(("cancelled",))
        except Exception as exc:
            self.messages.put(("error", str(exc), traceback.format_exc()))

    def _poll_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message[0]
                if kind == "progress":
                    _, done, total, status = message
                    self._set_progress((done / max(total, 1)) * 100)
                    self._set_status(status)
                elif kind == "done":
                    _, output, text_count, file_count = message
                    self.last_output = output
                    self._set_progress(100)
                    self._set_status(f"Concluído: {text_count} textos em {file_count} arquivos.", "success")
                    self._append_log(f"Concluído. Tradução salva em {output}", "success")
                    self._finish_controls(can_apply=True)
                    messagebox.showinfo("Tradução concluída", f"Arquivos traduzidos salvos em:\n{output}")
                elif kind == "cancelled":
                    self._set_status("Tradução cancelada.", "error")
                    self._append_log("Operação cancelada pelo usuário.", "error")
                    self._finish_controls()
                elif kind == "error":
                    _, error, details = message
                    self._set_status(f"Erro: {error}", "error")
                    self._append_log(details, "error")
                    self._finish_controls()
                    messagebox.showerror("Erro na tradução", error)
        except queue.Empty:
            pass
        self.after(100, self._poll_messages)

    def _finish_controls(self, can_apply: bool = False) -> None:
        self.settings_button.configure(state="normal")
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.apply_button.configure(state="normal" if can_apply else "disabled")

    def _open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Configurações")
        dialog.configure(bg=COLORS["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)

        outer = ttk.Frame(dialog, padding=(20, 16))
        outer.pack(fill="both", expand=True)
        card = self._card(outer, "Modelo de tradução")
        selected = tk.StringVar(value=self.settings["engine"])
        for engine in ENGINES.values():
            ttk.Radiobutton(
                card, text=engine.name, value=engine.id, variable=selected, style="Card.TRadiobutton"
            ).pack(anchor="w", pady=(6, 0))
            ttk.Label(card, text=engine.description, style="Hint.TLabel", wraplength=440, justify="left").pack(
                anchor="w", padx=(24, 0)
            )
            if not engine.files:
                status = f"Baixa cada idioma na primeira tradução ({engine.size})."
            elif engine.is_installed():
                status = f"Baixado ({engine.size})."
            else:
                status = f"Será baixado na primeira tradução ({engine.size})."
            ttk.Label(card, text=status, style="Hint.TLabel").pack(anchor="w", padx=(24, 0))

        def save() -> None:
            self.settings["engine"] = selected.get()
            try:
                save_settings(self.settings)
            except OSError as exc:
                messagebox.showerror("Erro ao salvar", str(exc), parent=dialog)
                return
            self.engine_var.set(ENGINES[selected.get()].name)
            self._append_log(f"Modelo selecionado: {ENGINES[selected.get()].name}")
            dialog.destroy()

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="Salvar", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right", padx=10)

        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + max((self.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.focus_set()

    def _apply(self) -> None:
        if not self.last_output:
            return
        if not messagebox.askyesno(
            "Aplicar tradução",
            "Isso substituirá os JSON do jogo após criar um backup completo. Continuar?",
        ):
            return
        try:
            backup = apply_translation(self.game_var.get(), self.last_output)
            self._append_log(f"Tradução aplicada. Backup: {backup}", "success")
            messagebox.showinfo("Tradução aplicada", f"Backup criado em:\n{backup}")
        except Exception as exc:
            messagebox.showerror("Erro ao aplicar", str(exc))


if __name__ == "__main__":
    app = TranslatorApp()
    if len(sys.argv) > 1:
        app.load_game(sys.argv[1])
    app.mainloop()
