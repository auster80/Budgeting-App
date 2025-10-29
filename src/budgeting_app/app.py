"""Tkinter application wiring for the budgeting desktop app."""

from __future__ import annotations

import threading
import tkinter as tk
import urllib.parse
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable

from .ai import ClassificationResult
from .csv_importer import CSVTransaction
from .models import Transaction
from .viewmodels import BudgetViewModel, CSVImportPreview
from .widgets import CurrencyEntry, LabeledEntry, Table


class BudgetApp(tk.Tk):
    """Main application window."""

    def __init__(self, viewmodel: BudgetViewModel) -> None:
        super().__init__()
        self.title("Budgeting App")
        self.geometry("1200x720")
        self.resizable(True, True)
        self.viewmodel = viewmodel
        self.bg_color = "#0b1426"
        self.card_bg = "#101d32"
        self.card_border = "#1d304b"
        self.surface_dark = "#0f1b2d"
        self.surface_muted = "#152641"
        self.surface_hover = "#1d3150"
        self.surface_selected = "#27466d"
        self.text_color = "#f4f8ff"
        self.muted_text = "#8ca1c7"
        self.heading_color = "#d7e3ff"
        self.status_bg = "#081020"
        self.disabled_bg = "#1a273d"
        self.disabled_fg = "#4f607a"
        self.accent_teal = "#4fd1c5"
        self.accent_green = "#4ade80"
        self.accent_red = "#f87171"
        self.accent_pink = "#f472b6"
        self.accent_purple = "#c084fc"

        self.configure(bg=self.bg_color)
        self.option_add("*Font", "{Segoe UI} 10")
        self.option_add("*TCombobox*Listbox.background", self.surface_dark)
        self.option_add("*TCombobox*Listbox.foreground", self.text_color)
        self.option_add("*TCombobox*Listbox.selectBackground", self.surface_selected)
        self.option_add("*TCombobox*Listbox.selectForeground", self.text_color)
        self.option_add("*Entry.insertBackground", self.accent_teal)
        self.category_lookup: dict[str, str] = {}
        self.category_name_by_id: dict[str, str] = {}
        self.category_colors: dict[str, str] = {}
        self._color_palette = [
            "#4E79A7",
            "#F28E2B",
            "#E15759",
            "#76B7B2",
            "#59A14F",
            "#EDC948",
            "#B07AA1",
            "#FF9DA7",
            "#9C755F",
            "#BAB0AC",
        ]
        self._color_index = 0
        self.status_var = tk.StringVar(value="Ready")
        self.ai_active = False
        self.ai_suggestions: dict[str, ClassificationResult] = {}
        self.ai_log_visible = False
        self._ai_worker_thread: threading.Thread | None = None
        self._ai_stop_event: threading.Event | None = None
        self._ai_refresh_pending = False
        self._suspend_ai_refresh = False
        self._category_chart_window: CategoryChartWindow | None = None

        self.balance_total_var = tk.StringVar(value="0.00")
        self.income_total_var = tk.StringVar(value="0.00")
        self.expenses_total_var = tk.StringVar(value="0.00")
        self.plan_gap_var = tk.StringVar(value="0.00")

        self._configure_styles()
        self._build_menu()
        self._build_layout()

        self.viewmodel.add_listener(self._on_data_changed)
        self.viewmodel.load()
        self.protocol("WM_DELETE_WINDOW", self._handle_exit)

    # ------------------------------------------------------------------ #
    # Layout helpers
    # ------------------------------------------------------------------ #
    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background=self.bg_color)
        style.configure("Card.TFrame", background=self.card_bg)
        style.configure("CardTable.TFrame", background=self.card_bg)

        style.configure(
            "TLabel",
            background=self.card_bg,
            foreground=self.text_color,
        )
        style.configure(
            "Heading.TLabel",
            background=self.card_bg,
            foreground=self.heading_color,
            font=("Segoe UI", 14, "bold"),
        )
        style.configure(
            "Subheading.TLabel",
            background=self.card_bg,
            foreground=self.muted_text,
            font=("Segoe UI", 10),
        )

        style.configure(
            "Primary.TButton",
            background=self.accent_teal,
            foreground=self.bg_color,
            padding=(16, 10),
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#5fe0d4"), ("pressed", "#44b6ab"), ("disabled", self.disabled_bg)],
            foreground=[("disabled", self.disabled_fg)],
        )

        style.configure(
            "Secondary.TButton",
            background=self.surface_dark,
            foreground=self.muted_text,
            padding=(14, 10),
            borderwidth=1,
            focusthickness=0,
            font=("Segoe UI", 10),
            relief="flat",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self.surface_hover), ("disabled", self.disabled_bg)],
            foreground=[("disabled", self.disabled_fg)],
            bordercolor=[("!disabled", self.card_border), ("focus", self.accent_teal)],
        )

        style.configure(
            "Danger.TButton",
            background=self.accent_red,
            foreground=self.bg_color,
            padding=(16, 10),
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#fb6b6b"), ("pressed", "#dd4d4d"), ("disabled", self.disabled_bg)],
            foreground=[("disabled", self.disabled_fg)],
        )

        style.configure(
            "Card.TCombobox",
            fieldbackground=self.surface_dark,
            background=self.surface_dark,
            foreground=self.text_color,
            bordercolor=self.card_border,
            lightcolor=self.card_border,
            darkcolor=self.card_border,
            arrowcolor=self.text_color,
            padding=(10, 6),
        )
        style.map(
            "Card.TCombobox",
            fieldbackground=[("readonly", self.surface_dark)],
            background=[("readonly", self.surface_dark)],
            foreground=[("disabled", self.disabled_fg)],
        )

        style.configure(
            "TEntry",
            fieldbackground=self.surface_dark,
            foreground=self.text_color,
            bordercolor=self.card_border,
            darkcolor=self.card_border,
            lightcolor=self.card_border,
            insertcolor=self.accent_teal,
            padding=(8, 6),
        )
        style.map(
            "TEntry",
            fieldbackground=[("!disabled", self.surface_dark)],
            bordercolor=[("focus", self.accent_teal)],
        )

        style.configure(
            "Budget.Treeview",
            background=self.surface_dark,
            foreground=self.text_color,
            fieldbackground=self.surface_dark,
            bordercolor=self.card_border,
            borderwidth=0,
            rowheight=32,
            font=("Segoe UI", 10),
        )
        style.map(
            "Budget.Treeview",
            background=[("selected", self.surface_selected)],
            foreground=[("selected", self.text_color)],
        )
        style.configure(
            "Budget.Treeview.Heading",
            background=self.surface_dark,
            foreground=self.muted_text,
            bordercolor=self.card_border,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        style.map(
            "Budget.Treeview.Heading",
            background=[("active", self.surface_dark)],
            foreground=[("active", self.heading_color)],
        )

        style.configure(
            "Treeview.Heading",
            background=self.surface_dark,
            foreground=self.muted_text,
            bordercolor=self.card_border,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", self.surface_dark)],
            foreground=[("active", self.heading_color)],
        )

        style.configure(
            "Vertical.TScrollbar",
            background=self.surface_dark,
            troughcolor=self.card_bg,
            bordercolor=self.card_border,
            lightcolor=self.card_border,
            darkcolor=self.card_border,
            arrowcolor=self.text_color,
        )

        style.configure(
            "Horizontal.TScrollbar",
            background=self.surface_dark,
            troughcolor=self.card_bg,
        )

    def _build_layout(self) -> None:
        container = tk.Frame(self, bg=self.bg_color)
        container.pack(fill="both", expand=True, padx=32, pady=(32, 16))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        self._build_totals_section(container)

        content = tk.Frame(container, bg=self.bg_color)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=4)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        self._build_categories_section(content)
        self._build_transactions_section(content)

        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            bg=self.status_bg,
            fg=self.muted_text,
            font=("Segoe UI", 9),
            padx=16,
            pady=8,
        )
        status_bar.pack(fill="x", side="bottom")

    def _build_totals_section(self, parent: tk.Widget) -> None:
        totals = tk.Frame(parent, bg=self.bg_color)
        totals.grid(row=0, column=0, sticky="ew", pady=(0, 24))
        totals.columnconfigure(0, weight=1)
        totals.columnconfigure(1, weight=1)
        totals.columnconfigure(2, weight=1)
        totals.columnconfigure(3, weight=1)
        totals.columnconfigure(4, weight=0)

        metrics = [
            ("Total Balance", self.balance_total_var, self.accent_teal),
            ("Income", self.income_total_var, self.accent_green),
            ("Expenses", self.expenses_total_var, self.accent_red),
            ("Plan Gap", self.plan_gap_var, self.accent_purple),
        ]

        for index, (label, variable, accent) in enumerate(metrics):
            card = self._create_metric_card(totals, label, variable, accent)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 16, 16))

        actions = tk.Frame(totals, bg=self.bg_color)
        actions.grid(row=0, column=len(metrics), sticky="e")

        ttk.Button(
            actions,
            text="Save Budget",
            command=self._save_budget,
            style="Primary.TButton",
        ).pack(side="right")

    def _build_categories_section(self, parent: tk.Widget) -> None:
        card, body = self._create_section_card(
            parent,
            "Categories",
            row=0,
            column=0,
            padx=(0, 24),
        )
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        form = tk.Frame(body, bg=self.card_bg)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        self.category_name_input = LabeledEntry(form, label="Name")
        self.category_name_input.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.category_plan_input = CurrencyEntry(form, label="Planned Amount")
        self.category_plan_input.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        ttk.Button(
            form,
            text="Add Category",
            style="Primary.TButton",
            command=self._handle_add_category,
        ).grid(row=0, column=2, sticky="ew")
        form.columnconfigure(2, weight=0)

        self.category_table = Table(
            body,
            columns=("name", "planned", "actual", "difference"),
            headings={
                "name": "Name",
                "planned": "Planned",
                "actual": "Actual",
                "difference": "Difference",
            },
            style="CardTable.TFrame",
            tree_style="Budget.Treeview",
        )
        self.category_table.grid(row=1, column=0, sticky="nsew")
        self.category_table.tree.configure(style="Budget.Treeview")
        self.category_table.tree.bind("<<TreeviewSelect>>", self._handle_category_selection)
        self.category_table.tree.bind("<Button-3>", self._show_category_context_menu)
        self.category_table.tree.bind(
            "<Control-Button-1>", self._show_category_context_menu, add="+"
        )

        self.category_context_menu = tk.Menu(self, tearoff=0)
        self.category_context_menu.add_command(
            label="Edit...",
            command=self._handle_edit_category,
        )

        actions = tk.Frame(body, bg=self.card_bg)
        actions.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        ttk.Button(
            actions,
            text="Delete Selected Category",
            command=self._handle_delete_category,
            style="Danger.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ttk.Button(
            actions,
            text="Visualise Actuals...",
            command=self._open_category_visualisation,
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _build_transactions_section(self, parent: tk.Widget) -> None:
        card, body = self._create_section_card(
            parent,
            "Transactions",
            row=0,
            column=1,
            accent_color=self.accent_pink,
        )
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        form = tk.Frame(body, bg=self.card_bg)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        for idx in range(5):
            form.columnconfigure(idx, weight=1)

        self.txn_description_input = LabeledEntry(form, label="Description")
        self.txn_description_input.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.txn_amount_input = CurrencyEntry(form, label="Amount")
        self.txn_amount_input.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        self.txn_date_input = LabeledEntry(form, label="Date (YYYY-MM-DD)", width=14)
        self.txn_date_input.grid(row=0, column=2, sticky="ew", padx=(0, 12))

        tk.Label(
            form,
            text="Category",
            bg=self.card_bg,
            fg=self.muted_text,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(8, 4))

        self.txn_category_input = ttk.Combobox(
            form,
            state="readonly",
            style="Card.TCombobox",
        )
        self.txn_category_input.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 0), padx=(0, 12))

        ttk.Button(
            form,
            text="Add Transaction",
            style="Primary.TButton",
            command=self._handle_add_transaction,
        ).grid(row=1, column=2, sticky="ew")

        ttk.Button(
            form,
            text="Import CSV...",
            command=self._handle_import_csv,
            style="Secondary.TButton",
        ).grid(row=1, column=3, sticky="ew", padx=(12, 0))

        ttk.Button(
            form,
            text="Import Credit Card...",
            command=self._handle_import_credit_card_statement,
            style="Secondary.TButton",
        ).grid(row=1, column=4, sticky="ew", padx=(12, 0))

        self.transaction_table = Table(
            body,
            columns=(
                "occurred_on",
                "description",
                "company",
                "account",
                "category",
                "amount",
                "suggestion",
                "apply",
            ),
            headings={
                "occurred_on": "Date",
                "description": "Description",
                "company": "Company",
                "account": "Account",
                "category": "Category",
                "amount": "Amount",
                "suggestion": "AI Suggestion",
                "apply": "Apply",
            },
            selectmode="extended",
            column_options={
                "amount": {"width": 120, "anchor": "e", "stretch": False},
                "apply": {"width": 70, "anchor": "center", "stretch": False},
                "suggestion": {"width": 180},
            },
            style="CardTable.TFrame",
            tree_style="Budget.Treeview",
        )
        self.transaction_table.grid(row=1, column=0, sticky="nsew")
        self.transaction_table.bind_yview(self._on_transaction_viewport_changed)
        self.transaction_table.tree.bind("<ButtonRelease-1>", self._handle_transaction_click)
        self.transaction_table.tree.bind(
            "<<TreeviewSelect>>", self._update_transaction_actions_state
        )

        assign_frame = tk.Frame(body, bg=self.card_bg)
        assign_frame.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        assign_frame.columnconfigure(1, weight=1)

        tk.Label(
            assign_frame,
            text="Assign category to selected",
            bg=self.card_bg,
            fg=self.muted_text,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.assign_category_input = ttk.Combobox(
            assign_frame,
            state="readonly",
            style="Card.TCombobox",
        )
        self.assign_category_input.grid(row=0, column=1, sticky="ew", padx=(12, 12))
        ttk.Button(
            assign_frame,
            text="Assign",
            command=self._handle_assign_transaction_category,
            style="Primary.TButton",
        ).grid(row=0, column=2, sticky="ew")

        controls = tk.Frame(assign_frame, bg=self.card_bg)
        controls.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(2, weight=1)
        controls.columnconfigure(3, weight=1)

        self.ai_start_button = ttk.Button(
            controls,
            text="Start AI Categorisation",
            command=self._start_ai_classification,
            style="Secondary.TButton",
        )
        self.ai_start_button.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 8))

        self.ai_stop_button = ttk.Button(
            controls,
            text="Stop AI Categorisation",
            command=self._stop_ai_classification,
            state="disabled",
            style="Secondary.TButton",
        )
        self.ai_stop_button.grid(row=0, column=2, sticky="ew", padx=8)

        self.search_company_button = ttk.Button(
            controls,
            text="Search Company Online",
            command=self._open_company_search,
            state="disabled",
            style="Secondary.TButton",
        )
        self.search_company_button.grid(row=0, column=3, sticky="ew")

        self.ai_log_button = ttk.Button(
            assign_frame,
            text="Show AI Log",
            command=self._toggle_ai_log,
            style="Secondary.TButton",
        )
        self.ai_log_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        self.ai_log_frame = tk.Frame(body, bg=self.surface_dark, highlightbackground=self.card_border, highlightthickness=1)
        self.ai_log_frame.grid(row=3, column=0, sticky="nsew", pady=(16, 0))
        self.ai_log_frame.columnconfigure(0, weight=1)
        self.ai_log_frame.rowconfigure(1, weight=1)

        header = tk.Frame(self.ai_log_frame, bg=self.surface_dark)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
        tk.Label(
            header,
            text="AI Classification Log",
            bg=self.surface_dark,
            fg=self.heading_color,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", anchor="w")

        self.ai_log_text = scrolledtext.ScrolledText(
            self.ai_log_frame,
            height=8,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            bg=self.surface_muted,
            fg=self.text_color,
            insertbackground=self.accent_teal,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.card_border,
            highlightcolor=self.accent_teal,
        )
        self.ai_log_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.ai_log_frame.grid_remove()

        ttk.Button(
            body,
            text="Delete Selected Transaction",
            command=self._handle_delete_transaction,
            style="Danger.TButton",
        ).grid(row=4, column=0, sticky="ew", pady=(16, 0))

    def _create_section_card(
        self,
        parent: tk.Widget,
        title: str,
        *,
        row: int,
        column: int,
        columnspan: int = 1,
        padx: tuple[int, int] | int = 0,
        pady: tuple[int, int] | int = 0,
        accent_color: str | None = None,
    ) -> tuple[tk.Frame, tk.Frame]:
        accent = accent_color or self.accent_teal
        card = tk.Frame(
            parent,
            bg=self.card_bg,
            highlightbackground=self.card_border,
            highlightthickness=1,
            bd=0,
        )
        card.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=padx, pady=pady)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        accent_bar = tk.Frame(card, bg=accent, height=3)
        accent_bar.grid(row=0, column=0, sticky="ew")

        header = tk.Frame(card, bg=self.card_bg)
        header.grid(row=1, column=0, sticky="ew", padx=24, pady=(18, 6))
        tk.Label(
            header,
            text=title,
            bg=self.card_bg,
            fg=self.heading_color,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", anchor="w")

        body = tk.Frame(card, bg=self.card_bg)
        body.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))
        body.grid_columnconfigure(0, weight=1)

        return card, body

    def _create_metric_card(
        self,
        parent: tk.Widget,
        title: str,
        variable: tk.StringVar,
        accent_color: str,
    ) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=self.surface_dark,
            highlightbackground=self.card_border,
            highlightthickness=1,
            bd=0,
        )
        card.grid_columnconfigure(0, weight=1)

        accent_bar = tk.Frame(card, bg=accent_color, height=3)
        accent_bar.grid(row=0, column=0, sticky="ew")

        content = tk.Frame(card, bg=self.surface_dark)
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=16)

        tk.Label(
            content,
            text=title,
            bg=self.surface_dark,
            fg=self.muted_text,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            content,
            textvariable=variable,
            bg=self.surface_dark,
            fg=accent_color,
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(
            content,
            text="This month",
            bg=self.surface_dark,
            fg=self.muted_text,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        return card

    @staticmethod
    def _format_currency(value: float) -> str:
        return f"{value:,.2f}"

    # ------------------------------------------------------------------ #
    # Event handlers
    # ------------------------------------------------------------------ #
    def _handle_add_category(self) -> None:
        name = self.category_name_input.get().strip()
        planned = self.category_plan_input.get().strip() or "0"
        if not name:
            messagebox.showinfo("Missing Data", "Please provide a category name.")
            return
        try:
            self.viewmodel.add_category(name, planned)
            self.category_name_input.set("")
            self.category_plan_input.set("")
            self._set_status(f"Added category '{name}'.")
        except ValueError:
            messagebox.showerror("Invalid Amount", "Planned amount must be numeric.")

    def _handle_delete_category(self) -> None:
        selected = self.category_table.tree.selection()
        if not selected:
            messagebox.showinfo("Select Category", "Select a category to delete.")
            return
        category_id = selected[0]
        if messagebox.askyesno("Delete Category", "Delete the selected category?"):
            self.viewmodel.delete_category(category_id)
            self._set_status("Category deleted.")

    def _open_category_visualisation(self) -> None:
        data = self._build_chart_data()
        if not data["incomes"]["categories"] and not data["expenses"]["categories"]:
            messagebox.showinfo(
                "No Data",
                "Add categories with transactions to visualise actual values.",
                parent=self,
            )
            return

        if self._category_chart_window and self._category_chart_window.winfo_exists():
            self._category_chart_window.update_data(data)
            self._category_chart_window.lift()
            self._category_chart_window.focus_set()
            return

        self._category_chart_window = CategoryChartWindow(
            self,
            data,
            on_close=self._handle_chart_window_closed,
        )

    def _handle_chart_window_closed(self) -> None:
        self._category_chart_window = None

    def _handle_add_transaction(self) -> None:
        description = self.txn_description_input.get().strip()
        amount = self.txn_amount_input.get().strip()
        occurred_on = self.txn_date_input.get().strip()
        category_label = self.txn_category_input.get()

        if not description or not amount or not category_label:
            messagebox.showinfo(
                "Missing Data", "Description, amount, and category are required."
            )
            return
        category_id = self.category_lookup.get(category_label)
        if not category_id:
            messagebox.showerror("Unknown Category", "Select a valid category.")
            return
        try:
            self.viewmodel.add_transaction(
                description=description,
                amount=amount,
                category_id=category_id,
                occurred_on=occurred_on,
            )
            self.txn_description_input.set("")
            self.txn_amount_input.set("")
            self.txn_date_input.set("")
            self._set_status(f"Transaction '{description}' added.")
        except ValueError:
            messagebox.showerror("Invalid Amount", "Transaction amount must be numeric.")
        except Exception as exc:  # noqa: BLE001 - user-friendly message
            messagebox.showerror("Error", str(exc))

    def _handle_delete_transaction(self) -> None:
        selected = self.transaction_table.tree.selection()
        if not selected:
            messagebox.showinfo("Select Transaction", "Select a transaction to delete.")
            return
        transaction_id = selected[0]
        if messagebox.askyesno("Delete Transaction", "Delete the selected transaction?"):
            self.viewmodel.delete_transaction(transaction_id)
            self._set_status("Transaction deleted.")

    def _handle_assign_transaction_category(self) -> None:
        selected = self.transaction_table.tree.selection()
        if not selected:
            messagebox.showinfo("Select Transaction", "Select a transaction first.")
            return
        category_label = self.assign_category_input.get()
        if not category_label:
            messagebox.showinfo("Select Category", "Choose a category to assign.")
            return
        category_id = self.category_lookup.get(category_label)
        if not category_id:
            messagebox.showerror("Unknown Category", "Select a valid category.")
            return
        try:
            self.viewmodel.set_transactions_category(selected, category_id)
            self.transaction_table.tree.selection_set(())
            self._update_transaction_actions_state()
            count = len(selected)
            label = "transaction" if count == 1 else "transactions"
            self._set_status(f"Assigned category to {count} {label}.")
        except KeyError as exc:  # noqa: BLE001
            messagebox.showerror("Error", str(exc))

    def _start_ai_classification(self) -> None:
        if self.ai_active:
            return
        self.ai_active = True
        self.ai_start_button.configure(state="disabled")
        self.ai_stop_button.configure(state="normal")
        self._set_status("AI classification started.")
        self.ai_suggestions.clear()
        self._apply_ai_suggestions_to_table()
        self.viewmodel.clear_ai_log()
        self.viewmodel.add_ai_log_entry("AI classification started by user.")
        self._refresh_ai_log()
        self._request_ai_refresh()

    def _stop_ai_classification(self) -> None:
        if not self.ai_active:
            return
        self.ai_active = False
        self.ai_start_button.configure(state="normal")
        self.ai_stop_button.configure(state="disabled")
        if self._ai_stop_event:
            self._ai_stop_event.set()
        if self._ai_worker_thread and self._ai_worker_thread.is_alive():
            self._ai_worker_thread.join(timeout=1.0)
        self._ai_worker_thread = None
        self._ai_stop_event = None
        self._ai_refresh_pending = False
        self._on_data_changed(self.viewmodel.ledger)
        self.viewmodel.add_ai_log_entry("AI classification stopped by user.")
        self._refresh_ai_log()
        self._set_status("AI classification stopped.")

    def _handle_transaction_click(self, event) -> None:
        tree = self.transaction_table.tree
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        column = tree.identify_column(event.x)
        try:
            column_index = int(column.replace("#", "")) - 1
        except ValueError:
            return
        columns = tree["columns"]
        if column_index < 0 or column_index >= len(columns):
            return
        if columns[column_index] != "apply":
            return
        item_id = tree.identify_row(event.y)
        if not item_id:
            return
        suggestion = self.ai_suggestions.get(item_id)
        if not suggestion:
            return
        self._accept_ai_suggestion(item_id, suggestion.category_name)

    def _accept_ai_suggestion(self, transaction_id: str, category_name: str) -> None:
        try:
            created = self.viewmodel.accept_ai_suggestion(transaction_id, category_name)
        except Exception as exc:  # noqa: BLE001 - user-friendly message
            messagebox.showerror("Error", str(exc))
            return

        if created:
            self._set_status(
                f"Created category '{category_name}' and assigned it to the transaction."
            )
        else:
            self._set_status(f"Assigned suggested category '{category_name}'.")
        self.ai_suggestions.pop(transaction_id, None)

    def _build_import_preview_message(self, preview: CSVImportPreview) -> str:
        """Create a user-friendly summary for the CSV import preview dialog."""

        lines = [
            f"New transactions to import: {preview.new_count}",
            f"Duplicate transactions to skip: {preview.duplicate_count}",
        ]

        if preview.new_transactions:
            lines.append("")
            lines.append("Preview of new transactions:")
            lines.append("(showing up to 5)")
            for record in preview.new_transactions[:5]:
                amount = f"{record.amount:.2f}"
                lines.append(
                    f"- {record.occurred_on} | {amount} | {record.description}"
                )
            remaining = preview.new_count - min(preview.new_count, 5)
            if remaining > 0:
                lines.append(f"...and {remaining} more transactions.")

        return "\n".join(lines)

    def _handle_import_csv(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            self._set_status("Import cancelled.")
            return
        try:
            preview = self.viewmodel.create_csv_import_preview(file_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import Failed", str(exc))
            self._set_status("Import failed.")
            return

        if preview.new_count == 0:
            if preview.duplicate_count:
                message = (
                    "No new transactions detected. "
                    f"Found {preview.duplicate_count} duplicates that will be skipped."
                )
            else:
                message = "The selected file does not contain any transactions to import."
            messagebox.showinfo("Import CSV", message)
            self._set_status("No new transactions were imported.")
            return

        summary = self._build_import_preview_message(preview)
        proceed = messagebox.askyesno(
            "Confirm Import",
            summary,
            icon="question",
            default="yes",
        )
        if not proceed:
            self._set_status("Import cancelled.")
            return

        try:
            imported = self.viewmodel.import_transactions_from_csv(preview)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import Failed", str(exc))
            self._set_status("Import failed.")
            return

        messagebox.showinfo(
            "Import Complete",
            (
                f"Imported {imported} new transactions.\n"
                f"Skipped {preview.duplicate_count} duplicates."
            ),
        )
        short_name = Path(file_path).name
        self._set_status(
            f"Imported {imported} transactions from {short_name}; "
            f"skipped {preview.duplicate_count} duplicates."
        )

    def _confirm_credit_card_replacement(
        self, transaction: Transaction, record: CSVTransaction
    ) -> bool:
        statement_amount = record.amount.quantize(Decimal("0.01"))
        description = (
            "A potential counterbooking was found in your ledger.\n\n"
            "Existing transaction:\n"
            "{txn_date} - {txn_desc}\n"
            "Amount: {txn_amount:.2f}\n\n"
            "Statement entry:\n"
            "{record_date} - {record_desc}\n"
            "Amount: {record_amount:.2f}\n\n"
            "Do you want to remove the ledger transaction?"
        ).format(
            txn_date=transaction.occurred_on,
            txn_desc=transaction.description,
            txn_amount=transaction.amount,
            record_date=record.occurred_on,
            record_desc=record.description,
            record_amount=statement_amount,
        )
        return messagebox.askyesno(
            "Remove Counterbooking", description, icon="question", default="yes", parent=self
        )

    def _handle_import_credit_card_statement(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select Credit Card Statement",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            self._set_status("Credit card import cancelled.")
            return

        try:
            imported = self.viewmodel.import_credit_card_statement(
                file_path,
                confirm_replacement=self._confirm_credit_card_replacement,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import Failed", str(exc))
            self._set_status("Credit card import failed.")
            return

        if imported == 0:
            messagebox.showinfo(
                "Import Credit Card",
                "No credit card transactions were imported.",
                parent=self,
            )
            self._set_status("No credit card transactions were imported.")
            return

        messagebox.showinfo(
            "Import Complete",
            f"Imported {imported} credit card transactions.",
            parent=self,
        )
        short_name = Path(file_path).name
        self._set_status(
            f"Imported {imported} credit card transactions from {short_name}."
        )

    def _persist_budget(self, *, show_confirmation: bool) -> bool:
        try:
            self.viewmodel.save()
        except Exception as exc:
            messagebox.showerror(
                "Save Failed",
                "Could not save budget data.\n\n" + str(exc),
                parent=self,
            )
            self._set_status("Save failed.")
            return False

        if show_confirmation:
            messagebox.showinfo(
                "Budget Saved", "Budget data saved successfully.", parent=self
            )
        self._set_status("Budget saved.")
        return True

    def _save_budget(self) -> None:
        self._persist_budget(show_confirmation=True)

    def _handle_exit(self) -> None:
        if self._persist_budget(show_confirmation=False):
            self.destroy()

    # ------------------------------------------------------------------ #
    # Data binding
    # ------------------------------------------------------------------ #
    def _on_data_changed(self, _ledger) -> None:
        categories = list(self.viewmodel.categories_for_table())
        transactions = list(self.viewmodel.transactions_for_table())

        self._prune_ai_suggestions()

        if self.ai_active and not self._suspend_ai_refresh:
            self._request_ai_refresh()
        self._suspend_ai_refresh = False

        self._ensure_category_colors(categories)

        self.category_table.populate(
            categories,
            key_field="category_id",
            tag_getter=self._get_category_tags,
        )
        self.transaction_table.populate(transactions, key_field="transaction_id")
        self._apply_ai_suggestions_to_table()
        self._apply_category_row_styles()

        planned_total = sum(float(row["planned"]) for row in categories)
        actual_total = sum(float(row["actual"]) for row in categories)
        income_total = sum(max(float(row["actual"]), 0.0) for row in categories)
        expense_total = sum(-min(float(row["actual"]), 0.0) for row in categories)
        balance = income_total - expense_total
        plan_gap = planned_total - actual_total

        self.balance_total_var.set(self._format_currency(balance))
        self.income_total_var.set(self._format_currency(income_total))
        self.expenses_total_var.set(self._format_currency(expense_total))
        self.plan_gap_var.set(self._format_currency(plan_gap))

        self.category_lookup = {row["name"]: row["category_id"] for row in categories}
        self.category_name_by_id = {row["category_id"]: row["name"] for row in categories}
        self.txn_category_input.configure(values=list(self.category_lookup.keys()))
        self.assign_category_input.configure(values=list(self.category_lookup.keys()))
        self._set_status("Budget data loaded.")
        self._refresh_ai_log()
        self._update_transaction_actions_state()

        if self._category_chart_window and self._category_chart_window.winfo_exists():
            self._category_chart_window.update_data(self._build_chart_data())
        elif self._category_chart_window:
            self._category_chart_window = None

    def _ensure_category_colors(self, categories: list[dict[str, str]]) -> None:
        existing_ids = {row.get("category_id", "") for row in categories if row.get("category_id")}
        stale_ids = [category_id for category_id in self.category_colors if category_id not in existing_ids]
        for category_id in stale_ids:
            self.category_colors.pop(category_id, None)

        for row in categories:
            category_id = row.get("category_id")
            if not category_id:
                continue
            if category_id not in self.category_colors:
                self.category_colors[category_id] = self._get_next_color()

    def _get_next_color(self) -> str:
        if not self._color_palette:
            return "#4E79A7"
        color = self._color_palette[self._color_index % len(self._color_palette)]
        self._color_index += 1
        return color

    def _get_category_tags(self, row: dict[str, str]) -> tuple[str, ...]:
        category_id = row.get("category_id")
        if not category_id:
            return ()
        if category_id not in self.category_colors:
            return ()
        return (f"category_color_{category_id}",)

    def _soften_category_color(self, color: str, *, opacity: float = 0.6) -> str:
        """Blend category colour with the table background to mimic transparency."""

        base = self.surface_dark.lstrip("#")
        active = color.lstrip("#")
        if len(base) != 6 or len(active) != 6:
            return color
        try:
            br, bg, bb = (int(base[i : i + 2], 16) for i in (0, 2, 4))
            ar, ag, ab = (int(active[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return color
        opacity = max(0.0, min(opacity, 1.0))
        inv_opacity = 1.0 - opacity
        rr = int(ar * opacity + br * inv_opacity)
        rg = int(ag * opacity + bg * inv_opacity)
        rb = int(ab * opacity + bb * inv_opacity)
        return f"#{rr:02X}{rg:02X}{rb:02X}"

    def _apply_category_row_styles(self) -> None:
        if not hasattr(self, "category_table"):
            return
        tree = self.category_table.tree
        for category_id, color in self.category_colors.items():
            tag = f"category_color_{category_id}"
            softened = self._soften_category_color(color)
            tree.tag_configure(
                tag,
                background=softened,
                foreground=self._get_contrasting_text(softened),
            )

    @staticmethod
    def _get_contrasting_text(color: str) -> str:
        color = color.lstrip("#")
        if len(color) != 6:
            return "#000000"
        try:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
        except ValueError:
            return "#000000"
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        return "#000000" if brightness > 140 else "#FFFFFF"

    def _build_chart_data(self) -> dict[str, dict[str, object]]:
        categories = list(self.viewmodel.categories_for_table())
        self._ensure_category_colors(categories)

        ledger = self.viewmodel.ledger
        incomes_categories: list[dict[str, object]] = []
        expenses_categories: list[dict[str, object]] = []
        category_type: dict[str, str] = {}

        for row in categories:
            category_id = row.get("category_id")
            if not category_id:
                continue
            color = self.category_colors.get(category_id)
            if not color:
                color = self._get_next_color()
                self.category_colors[category_id] = color
            name = row.get("name", "")
            try:
                actual_value = float(row.get("actual", "0") or 0.0)
            except (TypeError, ValueError):
                actual_value = 0.0
            entry = {
                "id": category_id,
                "name": name,
                "color": color,
                "value": abs(actual_value) if actual_value < 0 else actual_value,
            }
            if actual_value >= 0:
                incomes_categories.append(entry)
                category_type[category_id] = "income"
            else:
                expenses_categories.append(entry)
                category_type[category_id] = "expense"

        income_date_totals: dict[str, dict[date, float]] = {}
        expense_date_totals: dict[str, dict[date, float]] = {}

        for txn in ledger.transactions:
            category_id = txn.category_id
            if not category_id or category_id not in category_type:
                continue
            if getattr(txn, "is_internal_transfer", False):
                continue
            try:
                txn_date = datetime.fromisoformat(txn.occurred_on).date()
            except ValueError:
                continue
            value = abs(float(txn.amount))
            target = income_date_totals if category_type[category_id] == "income" else expense_date_totals
            daily_totals = target.setdefault(category_id, {})
            daily_totals[txn_date] = daily_totals.get(txn_date, 0.0) + value

        income_dates = sorted({date for totals in income_date_totals.values() for date in totals})
        expense_dates = sorted({date for totals in expense_date_totals.values() for date in totals})

        income_series = self._normalise_series(income_date_totals, incomes_categories, income_dates)
        expense_series = self._normalise_series(expense_date_totals, expenses_categories, expense_dates)

        return {
            "incomes": {
                "categories": incomes_categories,
                "dates": income_dates,
                "series": income_series,
            },
            "expenses": {
                "categories": expenses_categories,
                "dates": expense_dates,
                "series": expense_series,
            },
        }

    def _normalise_series(
        self,
        date_totals: dict[str, dict[date, float]],
        categories: list[dict[str, object]],
        dates: list[date],
    ) -> dict[str, list[float]]:
        series: dict[str, list[float]] = {}
        for category in categories:
            category_id = str(category["id"])
            per_date = date_totals.get(category_id, {})
            running_total = 0.0
            values: list[float] = []
            for current_date in dates:
                running_total += per_date.get(current_date, 0.0)
                values.append(running_total)
            series[category_id] = values
        return series

    def _apply_ai_suggestions_to_table(self) -> None:
        """Populate the AI suggestion column for the rendered transactions."""

        if not hasattr(self, "transaction_table"):
            return

        tree = self.transaction_table.tree
        columns = set(tree["columns"])
        if "suggestion" not in columns or "apply" not in columns:
            return

        for item_id in tree.get_children(""):
            self._update_ai_row(
                item_id,
                self.ai_suggestions.get(item_id),
                resort=False,
            )

        self.transaction_table.resort()

    def _prune_ai_suggestions(self) -> None:
        if not self.ai_suggestions:
            return
        valid_unassigned = {
            txn.transaction_id
            for txn in self.viewmodel.ledger.transactions
            if txn.transaction_id and not txn.category_id
        }
        stale_ids = [
            transaction_id
            for transaction_id in list(self.ai_suggestions)
            if transaction_id not in valid_unassigned
        ]
        for transaction_id in stale_ids:
            self.ai_suggestions.pop(transaction_id, None)

    def _update_ai_row(
        self,
        transaction_id: str,
        suggestion: ClassificationResult | None,
        *,
        resort: bool = True,
    ) -> None:
        if not hasattr(self, "transaction_table"):
            return
        tree = self.transaction_table.tree
        if not tree.exists(transaction_id):
            return
        if suggestion:
            tree.set(transaction_id, "suggestion", self._format_ai_suggestion(suggestion))
            tree.set(transaction_id, "apply", "✅")
        else:
            tree.set(transaction_id, "suggestion", "")
            tree.set(transaction_id, "apply", "")

        if resort:
            self.transaction_table.resort()

    @staticmethod
    def _format_ai_suggestion(suggestion: ClassificationResult) -> str:
        return f"{suggestion.category_name} ({suggestion.confidence:.0%})"

    def _on_partial_ai_suggestion(
        self, transaction_id: str, suggestion: ClassificationResult
    ) -> None:
        if not self.ai_active:
            return
        if not self._transaction_is_unassigned(transaction_id):
            self.ai_suggestions.pop(transaction_id, None)
            self._update_ai_row(transaction_id, None)
            return
        self.ai_suggestions[transaction_id] = suggestion
        self._update_ai_row(transaction_id, suggestion)

    def _transaction_is_unassigned(self, transaction_id: str) -> bool:
        for txn in self.viewmodel.ledger.transactions:
            if txn.transaction_id == transaction_id:
                return not txn.category_id
        return False

    def _handle_category_selection(self, _event) -> None:
        selected = self.category_table.tree.selection()
        if not selected:
            return
        category_id = selected[0]
        category_name = self.category_name_by_id.get(category_id)
        if not category_name:
            return
        self.assign_category_input.set(category_name)

    def _show_category_context_menu(self, event) -> None:
        tree = self.category_table.tree
        row_id = tree.identify_row(event.y)
        if not row_id:
            tree.selection_remove(tree.selection())
            return
        tree.selection_set(row_id)
        tree.focus(row_id)
        try:
            self.category_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.category_context_menu.grab_release()

    def _handle_edit_category(self) -> None:
        selected = self.category_table.tree.selection()
        if not selected:
            messagebox.showinfo(
                "Select Category",
                "Select a category to edit.",
                parent=self,
            )
            return
        category_id = selected[0]
        category = self.viewmodel.ledger.categories.get(category_id)
        if not category:
            messagebox.showerror(
                "Category Missing",
                "The selected category could not be found.",
                parent=self,
            )
            return

        dialog = tk.Toplevel(self)
        dialog.title("Edit Category")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        container = ttk.Frame(dialog, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        name_input = LabeledEntry(container, label="Name")
        name_input.grid(row=0, column=0, sticky="ew")
        name_input.set(category.name)

        amount_input = CurrencyEntry(container, label="Planned Amount")
        amount_input.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        amount_input.set(f"{category.planned_amount:.2f}")

        button_frame = ttk.Frame(container)
        button_frame.grid(row=2, column=0, sticky="e", pady=(12, 0))

        updated_name: str | None = None

        def on_save() -> None:
            nonlocal updated_name
            new_name = name_input.get().strip()
            planned = amount_input.get().strip() or "0"
            if not new_name:
                messagebox.showinfo(
                    "Missing Data", "Please provide a category name.", parent=dialog
                )
                return
            try:
                self.viewmodel.update_category(
                    category_id,
                    name=new_name,
                    planned_amount=planned,
                )
            except ValueError:
                messagebox.showerror(
                    "Invalid Amount",
                    "Planned amount must be numeric.",
                    parent=dialog,
                )
                return
            except KeyError:
                messagebox.showerror(
                    "Category Missing",
                    "The selected category could not be found.",
                    parent=dialog,
                )
                dialog.destroy()
                return
            updated_name = new_name
            dialog.destroy()

        def on_cancel() -> None:
            dialog.destroy()

        ttk.Button(button_frame, text="Cancel", command=on_cancel).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Save", command=on_save, style="Primary.TButton").grid(
            row=0, column=1
        )

        dialog.bind("<Return>", lambda _event: on_save())
        dialog.bind("<Escape>", lambda _event: on_cancel())
        dialog.wait_window()

        if updated_name is not None:
            self._set_status(f"Updated category '{updated_name}'.")

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(
            label="Import Credit Card Statement...",
            command=self._handle_import_credit_card_statement,
        )
        file_menu.add_command(label="Import CSV...", command=self._handle_import_csv)
        file_menu.add_command(label="Save Budget", command=self._save_budget)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._handle_exit)
        menu_bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about_dialog)
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menu_bar)

    def _show_about_dialog(self) -> None:
        messagebox.showinfo(
            "About Budgeting App",
            "Budgeting App\nKeep track of categories, transactions, and imports.\n",
        )

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _toggle_ai_log(self) -> None:
        self.ai_log_visible = not self.ai_log_visible
        if self.ai_log_visible:
            self.ai_log_frame.grid()
            self.ai_log_button.configure(text="Hide AI Log")
            self._refresh_ai_log()
        else:
            self.ai_log_frame.grid_remove()
            self.ai_log_button.configure(text="Show AI Log")

    def _refresh_ai_log(self) -> None:
        if not hasattr(self, "ai_log_text"):
            return
        entries = self.viewmodel.get_ai_log()
        self.ai_log_text.configure(state="normal")
        self.ai_log_text.delete("1.0", tk.END)
        if entries:
            self.ai_log_text.insert("1.0", "\n".join(entries) + "\n")
        self.ai_log_text.configure(state="disabled")
        if self.ai_log_visible:
            self.ai_log_text.see(tk.END)

    def _request_ai_refresh(self) -> None:
        if not self.ai_active:
            return
        self._ai_refresh_pending = True
        if not self._ai_worker_thread or not self._ai_worker_thread.is_alive():
            self._launch_ai_worker()

    def _on_transaction_viewport_changed(self) -> None:
        """Reprioritise AI categorisation when the visible rows change."""

        if not self.ai_active or self._suspend_ai_refresh:
            return
        worker = self._ai_worker_thread
        was_running = worker is not None and worker.is_alive()
        self._request_ai_refresh()
        if was_running and self._ai_stop_event and not self._ai_stop_event.is_set():
            self._ai_stop_event.set()

    def _transaction_processing_order(self) -> list[str]:
        """Return transaction IDs in the order AI categorisation should follow."""

        if not hasattr(self, "transaction_table"):
            return []

        tree = self.transaction_table.tree
        children = list(tree.get_children(""))
        if not children:
            return []

        try:
            tree.update_idletasks()
        except Exception:
            pass

        viewport_height = max(tree.winfo_height(), 1)
        visible: list[str] = []
        after_visible: list[str] = []
        before_visible: list[str] = []
        encountered_visible = False

        for item_id in children:
            bbox = tree.bbox(item_id)
            is_visible = False
            if bbox:
                _x, y, _width, height = bbox
                if viewport_height <= 1:
                    is_visible = True
                else:
                    is_visible = (y + height) >= 0 and y <= viewport_height
            if is_visible:
                encountered_visible = True
                visible.append(item_id)
            elif not encountered_visible:
                before_visible.append(item_id)
            else:
                after_visible.append(item_id)

        ordered = visible + after_visible + before_visible
        if not ordered:
            ordered = children

        return [
            transaction_id
            for transaction_id in ordered
            if transaction_id and self._transaction_is_unassigned(transaction_id)
        ]

    def _update_transaction_actions_state(self, _event=None) -> None:
        """Enable or disable transaction actions that require a selection."""

        has_selection = bool(self.transaction_table.tree.selection())
        state = "normal" if has_selection else "disabled"
        if hasattr(self, "search_company_button"):
            self.search_company_button.configure(state=state)

    def _open_company_search(self) -> None:
        """Open a browser window searching Google for the selected transaction's company."""

        tree = self.transaction_table.tree
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select Transaction", "Select a transaction first.")
            return

        columns = list(tree["columns"])
        values = tree.item(selected[0], "values")

        def _value_for(column: str) -> str:
            try:
                index = columns.index(column)
            except ValueError:
                return ""
            if index >= len(values):
                return ""
            return str(values[index]).strip()

        company = _value_for("company")

        if not company:
            messagebox.showinfo(
                "No Company Information",
                "The selected transaction does not include company details to search.",
            )
            return

        query = company
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        webbrowser.open_new(url)
        self._set_status(f"Opened web search for '{query}'.")

    def _launch_ai_worker(self) -> None:
        if not self.ai_active or not self._ai_refresh_pending:
            return
        processing_order = self._transaction_processing_order()
        stop_event = threading.Event()
        self._ai_stop_event = stop_event
        self._ai_refresh_pending = False

        def worker() -> None:
            collected: dict[str, ClassificationResult] = {}

            def log_message(message: str) -> None:
                self.viewmodel.add_ai_log_entry(message)
                self.after(0, self._refresh_ai_log)

            def should_abort() -> bool:
                return stop_event.is_set() or not self.ai_active

            def handle_suggestion(transaction_id: str, result: ClassificationResult) -> None:
                collected[transaction_id] = result
                self.after(
                    0,
                    lambda tid=transaction_id, res=result: self._on_partial_ai_suggestion(
                        tid, res
                    ),
                )

            try:
                suggestions = self.viewmodel.suggest_categories_for_unassigned(
                    logger=log_message,
                    should_abort=should_abort,
                    on_suggestion=handle_suggestion,
                    preferred_order=processing_order,
                )
            except Exception as exc:  # noqa: BLE001 - surface unexpected failures
                self.viewmodel.add_ai_log_entry(f"AI classification error: {exc}")
                suggestions = {}
            finally:
                self.after(0, self._refresh_ai_log)

            if should_abort():
                self.after(
                    0,
                    lambda results=dict(collected): self._on_ai_worker_finished(
                        results,
                        stop_event,
                        aborted=True,
                    ),
                )
                return

            final_results = suggestions or collected
            self.after(
                0,
                lambda results=dict(final_results): self._on_ai_worker_finished(
                    results,
                    stop_event,
                    aborted=False,
                ),
            )

        thread = threading.Thread(target=worker, daemon=True)
        self._ai_worker_thread = thread
        thread.start()

    @staticmethod
    def _merge_ai_suggestions(
        existing: dict[str, ClassificationResult],
        updates: dict[str, ClassificationResult],
        *,
        replace: bool,
    ) -> dict[str, ClassificationResult]:
        if replace:
            return dict(updates)
        merged = dict(existing)
        merged.update(updates)
        return merged

    def _on_ai_worker_finished(
        self,
        suggestions: dict[str, ClassificationResult],
        stop_event: threading.Event,
        *,
        aborted: bool,
    ) -> None:
        if self._ai_stop_event is stop_event and self.ai_active:
            filtered = {
                txn_id: result
                for txn_id, result in suggestions.items()
                if self._transaction_is_unassigned(txn_id)
            }
            self.ai_suggestions = self._merge_ai_suggestions(
                self.ai_suggestions,
                filtered,
                replace=not aborted,
            )
            self._suspend_ai_refresh = True
            self._on_data_changed(self.viewmodel.ledger)

        if self._ai_stop_event is stop_event:
            self._ai_worker_thread = None
            self._ai_stop_event = None
            if self.ai_active and self._ai_refresh_pending:
                self._launch_ai_worker()


class CategoryChartWindow(tk.Toplevel):
    """Popup window that renders category charts."""

    def __init__(
        self,
        master: BudgetApp,
        data: dict[str, dict[str, object]],
        *,
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title("Category Visualisation")
        self.transient(master)
        self.resizable(True, True)
        self._on_close = on_close
        self._data: dict[str, dict[str, object]] = data
        self.chart_type_var = tk.StringVar(value="Bar")
        self._tooltip = _CanvasTooltip(self)

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.chart_type_var.trace_add("write", lambda *_: self._render_charts())
        self.update_data(data)

    def _build_layout(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(3, weight=1)

        controls = ttk.Frame(container)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Chart Type:").grid(row=0, column=0, sticky="w")
        self.chart_selector = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self.chart_type_var,
            values=("Bar", "Line", "Pie"),
        )
        self.chart_selector.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        income_frame = ttk.Labelframe(container, text="Income", padding=6)
        income_frame.grid(row=2, column=0, sticky="nsew")
        expense_frame = ttk.Labelframe(container, text="Expenses", padding=6)
        expense_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        income_frame.columnconfigure(0, weight=1)
        income_frame.rowconfigure(0, weight=1)
        expense_frame.columnconfigure(0, weight=1)
        expense_frame.rowconfigure(0, weight=1)

        self.income_canvas = tk.Canvas(income_frame, background="white", height=260)
        self.income_canvas.grid(row=0, column=0, sticky="nsew")
        self.expense_canvas = tk.Canvas(expense_frame, background="white", height=260)
        self.expense_canvas.grid(row=0, column=0, sticky="nsew")

        self.income_canvas.bind("<Configure>", lambda _event: self._render_charts())
        self.expense_canvas.bind("<Configure>", lambda _event: self._render_charts())

    def _handle_close(self) -> None:
        if self._on_close:
            callback = self._on_close
            self._on_close = None
            callback()
        self.destroy()

    def update_data(self, data: dict[str, dict[str, object]]) -> None:
        self._data = data
        self._render_charts()

    def _render_charts(self) -> None:
        chart_type = self.chart_type_var.get() or "Bar"
        self._draw_chart(
            self.income_canvas,
            self._data.get("incomes", {}),
            chart_type,
            "No income data available.",
        )
        self._draw_chart(
            self.expense_canvas,
            self._data.get("expenses", {}),
            chart_type,
            "No expense data available.",
        )

    def _draw_chart(
        self,
        canvas: tk.Canvas,
        payload: dict[str, object],
        chart_type: str,
        empty_message: str,
    ) -> None:
        canvas.delete("all")
        categories: list[dict[str, object]] = list(payload.get("categories", []))
        dates: list[date] = list(payload.get("dates", []))
        series: dict[str, list[float]] = dict(payload.get("series", {}))

        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 200)
        if chart_type == "Bar":
            self._draw_bar_chart(canvas, categories, width, height, empty_message)
        elif chart_type == "Line":
            self._draw_line_chart(canvas, categories, dates, series, width, height, empty_message)
        else:
            self._draw_pie_chart(canvas, categories, width, height, empty_message)

    def _draw_bar_chart(
        self,
        canvas: tk.Canvas,
        categories: list[dict[str, object]],
        width: int,
        height: int,
        empty_message: str,
    ) -> None:
        if not categories:
            self._draw_empty(canvas, width, height, empty_message)
            return
        max_value = max(float(entry.get("value", 0.0)) for entry in categories)
        if max_value <= 0:
            self._draw_empty(canvas, width, height, empty_message)
            return

        margin_x = 60
        margin_y = 40
        plot_width = max(width - 2 * margin_x, 50)
        plot_height = max(height - 2 * margin_y, 50)
        base_y = height - margin_y
        canvas.create_line(margin_x, base_y, width - margin_x / 2, base_y, fill="#666666")

        count = len(categories)
        step = plot_width / count
        bar_width = step * 0.6

        for index, entry in enumerate(categories):
            value = float(entry.get("value", 0.0))
            color = str(entry.get("color", "#4E79A7"))
            ratio = value / max_value if max_value else 0
            bar_height = ratio * plot_height
            x_center = margin_x + step * index + step / 2
            x0 = x_center - bar_width / 2
            x1 = x_center + bar_width / 2
            y0 = base_y - bar_height
            bar = canvas.create_rectangle(x0, y0, x1, base_y, fill=color, outline="")
            self._bind_tooltip(canvas, bar, f"{entry.get('name', '')}: {value:.2f}")

    def _draw_line_chart(
        self,
        canvas: tk.Canvas,
        categories: list[dict[str, object]],
        dates: list[date],
        series: dict[str, list[float]],
        width: int,
        height: int,
        empty_message: str,
    ) -> None:
        if not categories or not dates:
            self._draw_empty(canvas, width, height, empty_message)
            return

        max_value = 0.0
        for entry in categories:
            values = series.get(str(entry.get("id")), [])
            if values:
                max_value = max(max_value, max(values))
        if max_value <= 0:
            self._draw_empty(canvas, width, height, empty_message)
            return

        margin_x = 60
        margin_y = 40
        plot_width = max(width - 2 * margin_x, 50)
        plot_height = max(height - 2 * margin_y, 50)
        base_y = height - margin_y
        canvas.create_line(margin_x, base_y, width - margin_x / 2, base_y, fill="#666666")

        if len(dates) == 1:
            x_positions = [margin_x + plot_width / 2]
        else:
            step = plot_width / (len(dates) - 1)
            x_positions = [margin_x + step * idx for idx in range(len(dates))]

        for entry in categories:
            category_id = str(entry.get("id"))
            values = series.get(category_id, [])
            if not values:
                continue
            color = str(entry.get("color", "#4E79A7"))
            points: list[float] = []
            for idx, value in enumerate(values):
                if idx >= len(x_positions):
                    break
                x = x_positions[idx]
                ratio = value / max_value if max_value else 0
                y = base_y - ratio * plot_height
                points.extend([x, y])
            if len(points) >= 4:
                line = canvas.create_line(points, fill=color, width=3, smooth=True)
                self._bind_tooltip(canvas, line, str(entry.get("name", "")))
            elif len(points) == 2:
                marker = canvas.create_oval(
                    points[0] - 4,
                    points[1] - 4,
                    points[0] + 4,
                    points[1] + 4,
                    fill=color,
                    outline="white",
                )
                self._bind_tooltip(canvas, marker, str(entry.get("name", "")))
            for idx, value in enumerate(values):
                if idx >= len(x_positions):
                    break
                x = x_positions[idx]
                ratio = value / max_value if max_value else 0
                y = base_y - ratio * plot_height
                marker = canvas.create_oval(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    fill=color,
                    outline="white",
                )
                date_label = dates[idx].isoformat() if idx < len(dates) else ""
                tooltip_text = f"{entry.get('name', '')}: {value:.2f} on {date_label}"
                self._bind_tooltip(canvas, marker, tooltip_text)

    def _draw_pie_chart(
        self,
        canvas: tk.Canvas,
        categories: list[dict[str, object]],
        width: int,
        height: int,
        empty_message: str,
    ) -> None:
        total = sum(
            float(entry.get("value", 0.0))
            for entry in categories
            if float(entry.get("value", 0.0)) > 0
        )
        if not categories or total <= 0:
            self._draw_empty(canvas, width, height, empty_message)
            return

        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 20
        bbox = (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
        start_angle = 0.0
        for entry in categories:
            value = float(entry.get("value", 0.0))
            if value <= 0:
                continue
            extent = (value / total) * 360
            arc = canvas.create_arc(
                bbox,
                start=start_angle,
                extent=extent,
                fill=str(entry.get("color", "#4E79A7")),
                outline="white",
                width=2,
            )
            self._bind_tooltip(canvas, arc, f"{entry.get('name', '')}: {value:.2f}")
            start_angle += extent

    def _draw_empty(self, canvas: tk.Canvas, width: int, height: int, message: str) -> None:
        canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill="#666666",
            font=("Segoe UI", 11, "italic"),
        )

    def _bind_tooltip(self, canvas: tk.Canvas, item: int, text: str) -> None:
        if not text:
            return

        def _show(event) -> None:
            self._tooltip.show(
                text,
                event.widget.winfo_rootx() + event.x + 12,
                event.widget.winfo_rooty() + event.y + 12,
            )

        def _hide(_event) -> None:
            self._tooltip.hide()

        canvas.tag_bind(item, "<Enter>", _show)
        canvas.tag_bind(item, "<Leave>", _hide)
        canvas.tag_bind(item, "<Motion>", _show)


class _CanvasTooltip:
    """Simple tooltip helper for canvas hover interactions."""

    def __init__(self, master: tk.Widget) -> None:
        self._master = master
        self._window: tk.Toplevel | None = None
        self._label: ttk.Label | None = None

    def show(self, text: str, x: int, y: int) -> None:
        if not text:
            return
        if self._window is None or not self._window.winfo_exists():
            self._window = tk.Toplevel(self._master)
            self._window.overrideredirect(True)
            self._window.attributes("-topmost", True)
            self._label = ttk.Label(
                self._window,
                text=text,
                background="#FFFFE0",
                relief="solid",
                borderwidth=1,
                padding=(6, 2),
            )
            self._label.pack()
        elif self._label:
            self._label.configure(text=text)
        if self._window:
            self._window.geometry(f"+{x}+{y}")
            self._window.deiconify()

    def hide(self) -> None:
        if self._window and self._window.winfo_exists():
            self._window.withdraw()

def run_app(data_file: str | None = None) -> None:
    """Convenience helper to start the Tkinter loop."""
    viewmodel = BudgetViewModel(data_file=data_file)
    app = BudgetApp(viewmodel)
    app.mainloop()
