"""Tkinter application wiring for the budgeting desktop app."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
        self.status_var = tk.StringVar(value="Ready")

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

        ttk.Button(
            categories_frame,
            text="Delete Selected Category",
            command=self._handle_delete_category,
        ).grid(row=2, column=0, sticky="ew", pady=(6, 0))

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
            columns=("occurred_on", "description", "account", "category", "amount"),
            headings={
                "occurred_on": "Date",
                "description": "Description",
                "account": "Account",
                "category": "Category",
                "amount": "Amount",
            },
            selectmode="extended",
        )
        self.transaction_table.grid(row=2, column=0, sticky="nsew")
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

        ttk.Button(
            transactions_frame,
            text="Delete Selected Transaction",
            command=self._handle_delete_transaction,
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))

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

        self.category_table.populate(categories, key_field="category_id")
        self.transaction_table.populate(transactions, key_field="transaction_id")

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

    def _handle_category_selection(self, _event) -> None:
        selected = self.category_table.tree.selection()
        if not selected:
            return
        category_id = selected[0]
        category_name = self.category_name_by_id.get(category_id)
        if not category_name:
            return
        self.assign_category_input.set(category_name)

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

def run_app(data_file: str | None = None) -> None:
    """Convenience helper to start the Tkinter loop."""
    viewmodel = BudgetViewModel(data_file=data_file)
    app = BudgetApp(viewmodel)
    app.mainloop()
