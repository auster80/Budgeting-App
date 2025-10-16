"""Tkinter application wiring for the budgeting desktop app."""

from __future__ import annotations

import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

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
        self._current_categories: list[dict[str, str]] = []
        self._color_palette = [
            "#fde68a",
            "#fca5a5",
            "#a5f3fc",
            "#bbf7d0",
            "#c4b5fd",
            "#f9a8d4",
            "#fdba74",
            "#bef264",
        ]
        self._next_color_index = 0
        self.status_var = tk.StringVar(value="Ready")
        self.ai_active = False
        self.ai_suggestions: dict[str, ClassificationResult] = {}
        self.ai_log_visible = False
        self._ai_worker_thread: threading.Thread | None = None
        self._ai_stop_event: threading.Event | None = None
        self._ai_refresh_pending = False
        self._suspend_ai_refresh = False
        self._chart_shape_to_category: dict[int, str] = {}
        self._chart_resize_after_id: str | None = None
        self._current_tooltip_category: str | None = None
        self._chart_visible = False

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

        actions = ttk.Frame(categories_frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        ttk.Button(
            actions,
            text="Delete Selected Category",
            command=self._handle_delete_category,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.show_chart_button = ttk.Button(
            actions,
            text="Show Actuals Chart",
            command=self._toggle_category_chart,
        )
        self.show_chart_button.grid(row=0, column=1, sticky="ew")

        self.category_chart_frame = ttk.Labelframe(
            categories_frame,
            text="Category Actuals",
            style="Card.TLabelframe",
        )
        self.category_chart_frame.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.category_chart_frame.columnconfigure(0, weight=1)
        self.category_chart_frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.category_chart_frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Chart Type:").grid(row=0, column=0, sticky="w")
        self.chart_type_var = tk.StringVar(value="bar")
        ttk.Radiobutton(
            controls,
            text="Bar",
            value="bar",
            variable=self.chart_type_var,
            command=self._update_category_chart,
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Radiobutton(
            controls,
            text="Pie",
            value="pie",
            variable=self.chart_type_var,
            command=self._update_category_chart,
        ).grid(row=0, column=2, sticky="w", padx=(6, 0))

        self.chart_canvas = tk.Canvas(
            self.category_chart_frame,
            height=260,
            background="white",
            highlightthickness=1,
            highlightbackground="#d9d9d9",
        )
        self.chart_canvas.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.chart_canvas.bind("<Motion>", self._handle_chart_motion)
        self.chart_canvas.bind("<Leave>", lambda _event: self._hide_chart_tooltip())
        self.chart_canvas.bind("<Configure>", self._handle_chart_resize)

        self.category_chart_frame.grid_remove()

        self.chart_tooltip = tk.Toplevel(self)
        self.chart_tooltip.withdraw()
        self.chart_tooltip.overrideredirect(True)
        self.chart_tooltip.transient(self)
        self.chart_tooltip.configure(background="#ffffe0")
        try:
            self.chart_tooltip.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.chart_tooltip_label = tk.Label(
            self.chart_tooltip,
            text="",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=2,
            font=("Segoe UI", 9),
        )
        self.chart_tooltip_label.pack(fill="both", expand=True)

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
                "apply": "",
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

        self.ai_log_button = ttk.Button(
            assign_frame,
            text="Show AI Log",
            command=self._toggle_ai_log,
        )
        self.ai_log_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

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
        self._current_categories = categories
        transactions = list(self.viewmodel.transactions_for_table())

        self._prune_ai_suggestions()

        if self.ai_active and not self._suspend_ai_refresh:
            self._request_ai_refresh()
        self._suspend_ai_refresh = False

        self.category_table.populate(categories, key_field="category_id")
        self.transaction_table.populate(transactions, key_field="transaction_id")
        self._apply_ai_suggestions_to_table()
        self._update_category_colors(categories)

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
        self._update_category_chart()

    # ------------------------------------------------------------------ #
    # Category colour and chart helpers
    # ------------------------------------------------------------------ #
    def _next_category_color(self) -> str:
        if not self._color_palette:
            return "#d9d9d9"
        color = self._color_palette[self._next_color_index % len(self._color_palette)]
        self._next_color_index += 1
        return color

    def _update_category_colors(self, categories: list[dict[str, str]]) -> None:
        if not hasattr(self, "category_table"):
            return

        active_ids = {row.get("category_id", "") for row in categories if row.get("category_id")}
        for stale_id in set(self.category_colors) - active_ids:
            self.category_colors.pop(stale_id, None)

        for row in categories:
            category_id = row.get("category_id")
            if not category_id:
                continue
            if category_id not in self.category_colors:
                self.category_colors[category_id] = self._next_category_color()

        tree = self.category_table.tree
        for category_id in active_ids:
            if not tree.exists(category_id):
                continue
            color = self.category_colors.get(category_id, "#d9d9d9")
            tag = f"category_{category_id}"
            tree.item(category_id, tags=(tag,))
            tree.tag_configure(tag, background=color, foreground="#202020")

    def _toggle_category_chart(self) -> None:
        self._chart_visible = not self._chart_visible
        if self._chart_visible:
            self.category_chart_frame.grid()
            self.show_chart_button.configure(text="Hide Actuals Chart")
            self._update_category_chart()
        else:
            self.category_chart_frame.grid_remove()
            self.show_chart_button.configure(text="Show Actuals Chart")
            self._hide_chart_tooltip()

    def _update_category_chart(self) -> None:
        if not getattr(self, "chart_canvas", None) or not self._chart_visible:
            return

        canvas = self.chart_canvas
        if self._chart_resize_after_id:
            self.after_cancel(self._chart_resize_after_id)
            self._chart_resize_after_id = None
        canvas.delete("all")
        self._chart_shape_to_category.clear()

        categories = getattr(self, "_current_categories", [])
        if not categories:
            self._draw_chart_message("Add categories to visualise actual amounts.")
            return

        chart_data: list[tuple[str, str, float]] = []
        for row in categories:
            category_id = row.get("category_id")
            if not category_id:
                continue
            try:
                actual_value = float(row.get("actual", "0") or 0)
            except ValueError:
                actual_value = 0.0
            chart_data.append((category_id, row.get("name", ""), actual_value))

        if not chart_data:
            self._draw_chart_message("Add categories to visualise actual amounts.")
            return

        chart_type = self.chart_type_var.get() if hasattr(self, "chart_type_var") else "bar"
        if chart_type == "pie":
            self._draw_pie_chart(chart_data)
        else:
            self._draw_bar_chart(chart_data)

    def _draw_chart_message(self, message: str) -> None:
        if not getattr(self, "chart_canvas", None):
            return
        width = int(self.chart_canvas.winfo_width() or self.chart_canvas["width"])
        height = int(self.chart_canvas.winfo_height() or self.chart_canvas["height"])
        self.chart_canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill="#555555",
            font=("Segoe UI", 11),
        )

    def _draw_bar_chart(self, data: list[tuple[str, str, float]]) -> None:
        if not data:
            return
        canvas = self.chart_canvas
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding_x = 32
        padding_y = 28
        available_width = max(width - 2 * padding_x, 1)
        available_height = max(height - 2 * padding_y, 1)

        values = [value for _, _, value in data]
        max_value = max(values + [0])
        min_value = min(values + [0])
        value_range = max_value - min_value
        if value_range == 0:
            value_range = max_value if max_value != 0 else 1
        scale = available_height / value_range
        zero_y = height - padding_y - (-min_value * scale)

        bar_spacing = 12
        bar_count = len(data)
        bar_width = max((available_width - bar_spacing * (bar_count - 1)) / bar_count, 12)

        for index, (category_id, name, value) in enumerate(data):
            color = self.category_colors.get(category_id, "#d9d9d9")
            x0 = padding_x + index * (bar_width + bar_spacing)
            x1 = x0 + bar_width
            if value >= 0:
                y0 = zero_y - value * scale
                y1 = zero_y
            else:
                y0 = zero_y
                y1 = zero_y - value * scale
            if abs(y1 - y0) < 1:
                if value >= 0:
                    y0 = y1 - 1
                else:
                    y1 = y0 + 1
            rect = canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill=color,
                outline="",
                tags=(f"category_{category_id}", "category_shape"),
            )
            self._chart_shape_to_category[rect] = category_id

            canvas.create_text(
                (x0 + x1) / 2,
                y0 - 6 if value >= 0 else y1 + 14,
                text=f"{value:.2f}",
                fill="#333333",
                font=("Segoe UI", 9),
                anchor="s" if value >= 0 else "n",
            )
            canvas.create_text(
                (x0 + x1) / 2,
                height - padding_y + 6,
                text=name,
                fill="#333333",
                font=("Segoe UI", 9),
                anchor="n",
                width=bar_width,
            )

        axis_color = "#999999"
        canvas.create_line(
            padding_x - 8,
            zero_y,
            width - padding_x + 8,
            zero_y,
            fill=axis_color,
        )

    def _draw_pie_chart(self, data: list[tuple[str, str, float]]) -> None:
        positive = [(cid, name, value) for cid, name, value in data if value > 0]
        if not positive:
            self._draw_chart_message("Pie chart requires positive actual amounts.")
            return

        canvas = self.chart_canvas
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        diameter = max(min(width, height) - 40, 60)
        radius = diameter / 2
        center_x = width / 2
        center_y = height / 2
        bbox = (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
        total = sum(value for _, _, value in positive)
        start_angle = 0.0

        for category_id, name, value in positive:
            extent = (value / total) * 360
            color = self.category_colors.get(category_id, "#d9d9d9")
            arc = canvas.create_arc(
                *bbox,
                start=start_angle,
                extent=extent,
                fill=color,
                outline="white",
                width=2,
                tags=(f"category_{category_id}", "category_shape"),
            )
            self._chart_shape_to_category[arc] = category_id

            mid_angle = math.radians(start_angle + extent / 2)
            label_x = center_x + (radius * 0.6) * math.cos(mid_angle)
            label_y = center_y - (radius * 0.6) * math.sin(mid_angle)
            canvas.create_text(
                label_x,
                label_y,
                text=f"{value:.2f}",
                fill="#333333",
                font=("Segoe UI", 9, "bold"),
            )

            start_angle += extent

    def _handle_chart_motion(self, event) -> None:
        if not self._chart_visible:
            return
        canvas = event.widget
        item = canvas.find_withtag("current")
        if not item:
            self._hide_chart_tooltip()
            return
        item_id = item[0]
        tags = canvas.gettags(item_id)
        if "category_shape" not in tags:
            self._hide_chart_tooltip()
            return
        category_id = self._chart_shape_to_category.get(item_id)
        if not category_id:
            self._hide_chart_tooltip()
            return
        if category_id == self._current_tooltip_category:
            self._move_chart_tooltip(event.x_root, event.y_root)
            return
        name = self.category_name_by_id.get(category_id)
        if not name:
            self._hide_chart_tooltip()
            return
        self._current_tooltip_category = category_id
        self.chart_tooltip_label.configure(text=name)
        self._move_chart_tooltip(event.x_root, event.y_root)
        self.chart_tooltip.deiconify()

    def _move_chart_tooltip(self, x_root: int, y_root: int) -> None:
        self.chart_tooltip.geometry(f"+{x_root + 12}+{y_root + 12}")

    def _hide_chart_tooltip(self) -> None:
        self._current_tooltip_category = None
        if hasattr(self, "chart_tooltip"):
            self.chart_tooltip.withdraw()

    def _handle_chart_resize(self, _event) -> None:
        if not self._chart_visible:
            return
        if self._chart_resize_after_id:
            self.after_cancel(self._chart_resize_after_id)
        self._chart_resize_after_id = self.after(120, self._redraw_chart_after_resize)

    def _redraw_chart_after_resize(self) -> None:
        self._chart_resize_after_id = None
        self._update_category_chart()

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
