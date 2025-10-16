"""Tkinter application wiring for the budgeting desktop app."""

from __future__ import annotations

import math
import threading
import tkinter as tk
import urllib.parse
import webbrowser
from datetime import datetime
from decimal import Decimal
from itertools import cycle
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, Wedge

from .ai import ClassificationResult
from .viewmodels import BudgetViewModel
from .widgets import CurrencyEntry, LabeledEntry, Table


class BudgetApp(tk.Tk):
    """Main application window."""

    def __init__(self, viewmodel: BudgetViewModel) -> None:
        super().__init__()
        self.title("Budgeting App")
        self.geometry("960x640")
        self.resizable(True, True)
        self.viewmodel = viewmodel
        self.category_lookup: dict[str, str] = {}
        self.category_name_by_id: dict[str, str] = {}
        self.category_colors: dict[str, str] = {}
        self._color_palette = cycle(
            [
                "#1f77b4",
                "#ff7f0e",
                "#2ca02c",
                "#d62728",
                "#9467bd",
                "#8c564b",
                "#e377c2",
                "#7f7f7f",
                "#bcbd22",
                "#17becf",
            ]
        )
        self._chart_window: tk.Toplevel | None = None
        self._chart_canvas: FigureCanvasTkAgg | None = None
        self._chart_figure: Figure | None = None
        self._chart_type_var: tk.StringVar | None = None
        self._chart_hover_cid: int | None = None
        self._chart_artist_labels: dict[object, str] = {}
        self._chart_annotation = None
        self.status_var = tk.StringVar(value="Ready")
        self.ai_active = False
        self.ai_suggestions: dict[str, ClassificationResult] = {}
        self.ai_log_visible = False
        self._ai_worker_thread: threading.Thread | None = None
        self._ai_stop_event: threading.Event | None = None
        self._ai_refresh_pending = False
        self._suspend_ai_refresh = False

        self._configure_styles()
        self._build_menu()
        self._build_layout()

        self.viewmodel.add_listener(self._on_data_changed)
        self.viewmodel.load()

    # ------------------------------------------------------------------ #
    # Layout helpers
    # ------------------------------------------------------------------ #
    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Card.TLabelframe", padding=12)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 12, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(1, weight=1)

        self._build_totals_section(container)
        self._build_categories_section(container)
        self._build_transactions_section(container)

    def _build_totals_section(self, parent: ttk.Frame) -> None:
        totals_frame = ttk.Frame(parent)
        totals_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        totals_frame.columnconfigure(0, weight=1)
        totals_frame.columnconfigure(1, weight=1)
        totals_frame.columnconfigure(2, weight=1)

        self.planned_total_var = tk.StringVar(value="0.00")
        self.actual_total_var = tk.StringVar(value="0.00")
        self.remaining_total_var = tk.StringVar(value="0.00")

        for idx, (label, var) in enumerate(
            [
                ("Planned Total:", self.planned_total_var),
                ("Actual Total:", self.actual_total_var),
                ("Remaining:", self.remaining_total_var),
            ]
        ):
            ttk.Label(totals_frame, text=label, font=("Segoe UI", 10, "bold")).grid(
                row=0, column=2 * idx, sticky="w"
            )
            ttk.Label(totals_frame, textvariable=var, font=("Consolas", 12)).grid(
                row=0, column=2 * idx + 1, sticky="w"
            )

        ttk.Button(
            totals_frame,
            text="Save Budget",
            command=self._save_budget,
            style="Primary.TButton",
        ).grid(row=0, column=6, sticky="e")

    def _build_categories_section(self, parent: ttk.Frame) -> None:
        categories_frame = ttk.Labelframe(
            parent,
            text="Budget Categories",
            style="Card.TLabelframe",
        )
        categories_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        categories_frame.columnconfigure(0, weight=1)

        form = ttk.Frame(categories_frame)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        self.category_name_input = LabeledEntry(form, label="Name")
        self.category_name_input.grid(row=0, column=0, sticky="ew")
        self.category_plan_input = CurrencyEntry(form, label="Planned Amount")
        self.category_plan_input.grid(row=0, column=1, sticky="ew")

        ttk.Button(
            form,
            text="Add Category",
            style="Primary.TButton",
            command=self._handle_add_category,
        ).grid(row=0, column=2, padx=(12, 0), sticky="ew")

        self.category_table = Table(
            categories_frame,
            columns=("name", "planned", "actual", "difference"),
            headings={
                "name": "Name",
                "planned": "Planned",
                "actual": "Actual",
                "difference": "Difference",
            },
        )
        self.category_table.grid(row=1, column=0, sticky="nsew")
        categories_frame.rowconfigure(1, weight=1)
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

        ttk.Button(
            categories_frame,
            text="Visualize Actuals",
            command=self._open_chart_window,
        ).grid(row=2, column=0, sticky="ew", pady=(6, 0))

        ttk.Button(
            categories_frame,
            text="Delete Selected Category",
            command=self._handle_delete_category,
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _build_transactions_section(self, parent: ttk.Frame) -> None:
        transactions_frame = ttk.Labelframe(parent, text="Transactions", style="Card.TLabelframe")
        transactions_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        transactions_frame.columnconfigure(0, weight=1)

        form = ttk.Frame(transactions_frame)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for idx in range(5):
            form.columnconfigure(idx, weight=1)

        self.txn_description_input = LabeledEntry(form, label="Description")
        self.txn_description_input.grid(row=0, column=0, sticky="ew")

        self.txn_amount_input = CurrencyEntry(form, label="Amount")
        self.txn_amount_input.grid(row=0, column=1, sticky="ew")

        self.txn_date_input = LabeledEntry(form, label="Date (YYYY-MM-DD)", width=14)
        self.txn_date_input.grid(row=0, column=2, sticky="ew")

        ttk.Label(form, text="Category").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.txn_category_input = ttk.Combobox(form, state="readonly")
        self.txn_category_input.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        ttk.Button(
            form,
            text="Add Transaction",
            style="Primary.TButton",
            command=self._handle_add_transaction,
        ).grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(6, 0))

        ttk.Button(
            form,
            text="Import CSV...",
            command=self._handle_import_csv,
        ).grid(row=1, column=3, sticky="ew", padx=(12, 0), pady=(6, 0))

        self.transaction_table = Table(
            transactions_frame,
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
                "amount": {"width": 100, "anchor": "e", "stretch": False},
                "apply": {"width": 60, "anchor": "center", "stretch": False},
                "suggestion": {"width": 160},
            },
        )
        self.transaction_table.grid(row=2, column=0, sticky="nsew")
        self.transaction_table.tree.bind("<ButtonRelease-1>", self._handle_transaction_click)
        self.transaction_table.tree.bind(
            "<<TreeviewSelect>>", self._update_transaction_actions_state
        )
        transactions_frame.rowconfigure(2, weight=1)

        assign_frame = ttk.Frame(transactions_frame)
        assign_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        assign_frame.columnconfigure(1, weight=1)
        ttk.Label(assign_frame, text="Assign category to selected:").grid(row=0, column=0, sticky="w")
        self.assign_category_input = ttk.Combobox(assign_frame, state="readonly")
        self.assign_category_input.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(
            assign_frame,
            text="Assign",
            command=self._handle_assign_transaction_category,
        ).grid(row=0, column=2)

        self.ai_start_button = ttk.Button(
            assign_frame,
            text="Start AI Categorisation",
            command=self._start_ai_classification,
        )
        self.ai_start_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.ai_stop_button = ttk.Button(
            assign_frame,
            text="Stop AI Categorisation",
            command=self._stop_ai_classification,
            state="disabled",
        )
        self.ai_stop_button.grid(row=1, column=2, sticky="ew", pady=(6, 0))

        self.search_company_button = ttk.Button(
            assign_frame,
            text="Search Company Online",
            command=self._open_company_search,
            state="disabled",
        )
        self.search_company_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.ai_log_button = ttk.Button(
            assign_frame,
            text="Show AI Log",
            command=self._toggle_ai_log,
        )
        self.ai_log_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.ai_log_frame = ttk.Labelframe(
            transactions_frame,
            text="AI Classification Log",
            style="Card.TLabelframe",
        )
        self.ai_log_frame.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        self.ai_log_frame.columnconfigure(0, weight=1)
        self.ai_log_text = scrolledtext.ScrolledText(
            self.ai_log_frame,
            height=10,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.ai_log_text.grid(row=0, column=0, sticky="nsew")
        self.ai_log_frame.rowconfigure(0, weight=1)
        self.ai_log_frame.grid_remove()

        ttk.Button(
            transactions_frame,
            text="Delete Selected Transaction",
            command=self._handle_delete_transaction,
        ).grid(row=5, column=0, sticky="ew", pady=(6, 0))

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 4))
        status_bar.pack(fill="x", side="bottom")

    # ------------------------------------------------------------------ #
    # Colour helpers
    # ------------------------------------------------------------------ #
    def _assign_category_colors(self, categories: list[dict[str, str]]) -> None:
        existing = dict(self.category_colors)
        self.category_colors.clear()
        for category in categories:
            category_id = category["category_id"]
            if category_id in existing:
                self.category_colors[category_id] = existing[category_id]
            else:
                self.category_colors[category_id] = next(self._color_palette)

    @staticmethod
    def _lighten_color(hex_color: str, amount: float = 0.6) -> str:
        amount = max(0.0, min(amount, 1.0))
        color = hex_color.lstrip("#")
        if len(color) != 6:
            return hex_color
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        r = int(r + (255 - r) * amount)
        g = int(g + (255 - g) * amount)
        b = int(b + (255 - b) * amount)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _get_contrasting_text_color(hex_color: str) -> str:
        color = hex_color.lstrip("#")
        if len(color) != 6:
            return "#000000"
        r = int(color[0:2], 16) / 255.0
        g = int(color[2:4], 16) / 255.0
        b = int(color[4:6], 16) / 255.0
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return "#000000" if luminance > 0.6 else "#ffffff"

    def _apply_category_colors_to_table(self, categories: list[dict[str, str]]) -> None:
        tree = self.category_table.tree
        for category in categories:
            category_id = category["category_id"]
            color = self.category_colors.get(category_id)
            if not color:
                continue
            background = self._lighten_color(color, amount=0.7)
            foreground = self._get_contrasting_text_color(background)
            tag = f"category_{category_id}"
            tree.tag_configure(tag, background=background, foreground=foreground)
            tree.item(category_id, tags=(tag,))

    # ------------------------------------------------------------------ #
    # Chart rendering
    # ------------------------------------------------------------------ #
    def _open_chart_window(self) -> None:
        if self._chart_window and self._chart_window.winfo_exists():
            self._chart_window.lift()
            self._refresh_chart()
            return

        self._chart_window = tk.Toplevel(self)
        self._chart_window.title("Category Actuals")
        self._chart_window.geometry("900x620")
        self._chart_window.protocol("WM_DELETE_WINDOW", self._close_chart_window)

        container = ttk.Frame(self._chart_window, padding=12)
        container.pack(fill="both", expand=True)

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(0, 12))

        ttk.Label(controls, text="Chart Type:").pack(side="left")
        self._chart_type_var = tk.StringVar(value="Bar Chart")
        chart_selector = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self._chart_type_var,
            values=["Bar Chart", "Line Chart", "Pie Chart"],
            width=18,
        )
        chart_selector.pack(side="left", padx=(6, 0))
        chart_selector.bind("<<ComboboxSelected>>", lambda _event: self._render_chart())

        ttk.Button(controls, text="Refresh", command=self._render_chart).pack(
            side="left", padx=(6, 0)
        )

        self._chart_figure = Figure(figsize=(6, 4), dpi=100)
        self._chart_canvas = FigureCanvasTkAgg(self._chart_figure, master=container)
        canvas_widget = self._chart_canvas.get_tk_widget()
        canvas_widget.pack(fill="both", expand=True)

        self._chart_artist_labels = {}
        self._chart_annotation = None
        self._chart_hover_cid = None
        self._render_chart()

    def _close_chart_window(self) -> None:
        if self._chart_window and self._chart_window.winfo_exists():
            self._chart_window.destroy()
        self._chart_window = None
        self._chart_canvas = None
        self._chart_figure = None
        self._chart_type_var = None
        self._chart_artist_labels = {}
        self._chart_annotation = None
        self._chart_hover_cid = None

    def _refresh_chart(self) -> None:
        if not self._chart_window or not self._chart_window.winfo_exists():
            return
        self._render_chart()

    def _render_chart(self) -> None:
        if not self._chart_canvas or not self._chart_figure:
            return

        categories = list(self.viewmodel.categories_for_table())
        if categories:
            self._assign_category_colors(categories)

        chart_type = self._chart_type_var.get() if self._chart_type_var else "Bar Chart"
        data = self._get_category_chart_data()

        self._chart_figure.clear()
        ax = self._chart_figure.add_subplot(111)
        self._chart_artist_labels.clear()
        self._chart_annotation = None

        if chart_type == "Pie Chart":
            self._plot_pie_chart(ax, data)
        elif chart_type == "Line Chart":
            self._plot_line_chart(ax, data)
        else:
            self._plot_bar_chart(ax, data)

        self._chart_canvas.draw_idle()
        self._connect_chart_hover()

    def _get_category_chart_data(self) -> list[dict[str, object]]:
        ledger = self.viewmodel.ledger
        transactions_by_category: dict[str, list] = {}
        for transaction in ledger.transactions:
            if not transaction.category_id or transaction.category_id not in ledger.categories:
                continue
            transactions_by_category.setdefault(transaction.category_id, []).append(transaction)

        data: list[dict[str, object]] = []
        for category_id, category in ledger.categories.items():
            transactions = sorted(
                transactions_by_category.get(category_id, []),
                key=lambda txn: txn.occurred_on,
            )
            data.append(
                {
                    "id": category_id,
                    "name": category.name,
                    "actual": float(category.actual_amount),
                    "color": self.category_colors.get(category_id, "#1f77b4"),
                    "transactions": transactions,
                }
            )

        data.sort(key=lambda entry: entry["name"].lower())
        return data

    def _plot_bar_chart(self, ax, data: list[dict[str, object]]) -> None:
        if not data:
            ax.text(
                0.5,
                0.5,
                "No categories to display",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return

        names = [entry["name"] for entry in data]
        amounts = [entry["actual"] for entry in data]
        colors = [entry["color"] for entry in data]
        bars = ax.bar(names, amounts, color=colors)
        ax.set_ylabel("Actual Amount")
        ax.set_title("Actual Spending by Category")
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        ax.tick_params(axis="x", rotation=35)

        for bar, entry in zip(bars, data):
            self._chart_artist_labels[bar] = entry["name"]
            height = bar.get_height()
            ax.annotate(
                f"{height:.2f}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    def _plot_line_chart(self, ax, data: list[dict[str, object]]) -> None:
        plotted = False
        for entry in data:
            transactions = entry["transactions"]
            if not transactions:
                continue
            cumulative = Decimal("0.00")
            dates: list[datetime] = []
            totals: list[float] = []
            for txn in transactions:
                try:
                    txn_date = datetime.fromisoformat(txn.occurred_on)
                except ValueError:
                    continue
                cumulative += txn.amount
                dates.append(txn_date)
                totals.append(float(cumulative))
            if not dates:
                continue
            line, = ax.plot(
                dates,
                totals,
                marker="o",
                linewidth=2,
                color=entry["color"],
                label=entry["name"],
            )
            self._chart_artist_labels[line] = entry["name"]
            plotted = True

        if not plotted:
            ax.text(
                0.5,
                0.5,
                "No transaction history available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return

        ax.set_title("Cumulative Actuals Over Time")
        ax.set_xlabel("Date")
        ax.set_ylabel("Amount")
        ax.legend(loc="upper left")
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        self._chart_figure.autofmt_xdate()

    def _plot_pie_chart(self, ax, data: list[dict[str, object]]) -> None:
        meaningful = [entry for entry in data if abs(entry["actual"]) > 1e-9]
        if not meaningful:
            ax.text(
                0.5,
                0.5,
                "No actual amounts to display",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return

        values = [abs(entry["actual"]) for entry in meaningful]
        colors = [entry["color"] for entry in meaningful]
        wedges, texts, autotexts = ax.pie(
            values,
            colors=colors,
            startangle=90,
            autopct="%1.1f%%",
            pctdistance=0.8,
        )
        ax.set_title("Category Actual Distribution")
        ax.axis("equal")
        ax.legend(
            wedges,
            [entry["name"] for entry in meaningful],
            loc="center left",
            bbox_to_anchor=(1, 0.5),
        )

        for text in autotexts:
            text.set_color("#ffffff")
            text.set_fontsize(9)

        for wedge, entry in zip(wedges, meaningful):
            self._chart_artist_labels[wedge] = entry["name"]

    def _connect_chart_hover(self) -> None:
        if not self._chart_canvas:
            return
        if self._chart_hover_cid is not None:
            self._chart_canvas.mpl_disconnect(self._chart_hover_cid)
        self._chart_hover_cid = self._chart_canvas.mpl_connect(
            "motion_notify_event", self._on_chart_hover
        )

    def _on_chart_hover(self, event) -> None:
        if not self._chart_canvas or not self._chart_figure:
            return
        if not event.inaxes:
            self._hide_chart_annotation()
            return

        for artist, label in self._chart_artist_labels.items():
            contains, details = artist.contains(event)
            if not contains:
                continue
            x = event.xdata
            y = event.ydata
            if isinstance(artist, Line2D):
                indices = details.get("ind", []) if isinstance(details, dict) else []
                if indices:
                    index = indices[0]
                    x = artist.get_xdata()[index]
                    y = artist.get_ydata()[index]
            elif isinstance(artist, Rectangle):
                x = artist.get_x() + artist.get_width() / 2
                y = artist.get_y() + artist.get_height()
            elif isinstance(artist, Wedge):
                theta = math.radians((artist.theta1 + artist.theta2) / 2)
                radius = artist.r * 0.7
                x = artist.center[0] + radius * math.cos(theta)
                y = artist.center[1] + radius * math.sin(theta)
            self._show_chart_annotation(label, x, y)
            return

        self._hide_chart_annotation()

    def _show_chart_annotation(self, label: str, x: float | None, y: float | None) -> None:
        if not self._chart_canvas or not self._chart_figure:
            return
        ax = self._chart_figure.axes[0]
        if x is None or y is None:
            return
        if self._chart_annotation is None:
            self._chart_annotation = ax.annotate(
                label,
                xy=(x, y),
                xytext=(12, 12),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="#fdfdfd", ec="#333333", lw=0.5),
                arrowprops=dict(arrowstyle="->", color="#333333", lw=0.5),
            )
        else:
            self._chart_annotation.xy = (x, y)
            self._chart_annotation.set_text(label)
            self._chart_annotation.set_position((12, 12))
        self._chart_annotation.set_visible(True)
        self._chart_canvas.draw_idle()

    def _hide_chart_annotation(self) -> None:
        if self._chart_annotation and self._chart_annotation.get_visible():
            self._chart_annotation.set_visible(False)
            if self._chart_canvas:
                self._chart_canvas.draw_idle()

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

    def _handle_import_csv(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            self._set_status("Import cancelled.")
            return
        try:
            imported = self.viewmodel.import_transactions_from_csv(file_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import Failed", str(exc))
            self._set_status("Import failed.")
            return
        if imported == 0:
            messagebox.showinfo("Import Complete", "No new transactions were imported.")
            self._set_status("No new transactions were imported.")
        else:
            messagebox.showinfo(
                "Import Complete",
                f"Imported {imported} transactions from the CSV file.",
            )
            short_name = Path(file_path).name
            self._set_status(f"Imported {imported} transactions from {short_name}.")

    def _save_budget(self) -> None:
        self.viewmodel.save()
        messagebox.showinfo("Budget Saved", "Budget data saved successfully.")
        self._set_status("Budget saved.")

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

        self.category_table.populate(categories, key_field="category_id")
        self._assign_category_colors(categories)
        self._apply_category_colors_to_table(categories)
        self.transaction_table.populate(transactions, key_field="transaction_id")
        self._apply_ai_suggestions_to_table()

        planned_total = sum(float(row["planned"]) for row in categories)
        actual_total = sum(float(row["actual"]) for row in categories)
        self.planned_total_var.set(f"{planned_total:.2f}")
        self.actual_total_var.set(f"{actual_total:.2f}")
        self.remaining_total_var.set(f"{(planned_total - actual_total):.2f}")

        self.category_lookup = {row["name"]: row["category_id"] for row in categories}
        self.category_name_by_id = {row["category_id"]: row["name"] for row in categories}
        self.txn_category_input.configure(values=list(self.category_lookup.keys()))
        self.assign_category_input.configure(values=list(self.category_lookup.keys()))
        self._set_status("Budget data loaded.")
        self._refresh_ai_log()
        self._update_transaction_actions_state()
        self._refresh_chart()

    def _apply_ai_suggestions_to_table(self) -> None:
        """Populate the AI suggestion column for the rendered transactions."""

        if not hasattr(self, "transaction_table"):
            return

        tree = self.transaction_table.tree
        columns = set(tree["columns"])
        if "suggestion" not in columns or "apply" not in columns:
            return

        for item_id in tree.get_children(""):
            self._update_ai_row(item_id, self.ai_suggestions.get(item_id))

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
        self, transaction_id: str, suggestion: ClassificationResult | None
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
        file_menu.add_command(label="Import CSV...", command=self._handle_import_csv)
        file_menu.add_command(label="Save Budget", command=self._save_budget)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
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
                )
            except Exception as exc:  # noqa: BLE001 - surface unexpected failures
                self.viewmodel.add_ai_log_entry(f"AI classification error: {exc}")
                suggestions = {}
            finally:
                self.after(0, self._refresh_ai_log)

            if should_abort():
                self.after(0, lambda: self._on_ai_worker_finished(collected, stop_event))
                return

            final_results = suggestions or collected
            self.after(0, lambda: self._on_ai_worker_finished(final_results, stop_event))

        thread = threading.Thread(target=worker, daemon=True)
        self._ai_worker_thread = thread
        thread.start()

    def _on_ai_worker_finished(
        self, suggestions: dict[str, ClassificationResult], stop_event: threading.Event
    ) -> None:
        if self._ai_stop_event is stop_event and self.ai_active:
            filtered = {
                txn_id: result
                for txn_id, result in suggestions.items()
                if self._transaction_is_unassigned(txn_id)
            }
            self.ai_suggestions = filtered
            self._suspend_ai_refresh = True
            self._on_data_changed(self.viewmodel.ledger)

        if self._ai_stop_event is stop_event:
            self._ai_worker_thread = None
            self._ai_stop_event = None
            if self.ai_active and self._ai_refresh_pending:
                self._launch_ai_worker()

def run_app(data_file: str | None = None) -> None:
    """Convenience helper to start the Tkinter loop."""
    viewmodel = BudgetViewModel(data_file=data_file)
    app = BudgetApp(viewmodel)
    app.mainloop()
