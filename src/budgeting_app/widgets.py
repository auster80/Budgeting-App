"""Custom Tkinter widgets used by the budgeting app."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Mapping

from tkinter import ttk


class LabeledEntry(ttk.Frame):
    """A simple label + entry composite widget."""

    def __init__(self, master: tk.Widget, *, label: str, width: int = 20, **kwargs) -> None:
        super().__init__(master, padding=(0, 2))
        self.columnconfigure(1, weight=1)
        self._label = ttk.Label(self, text=label)
        self._label.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.var = tk.StringVar()
        validate_cmd = kwargs.pop("validatecommand", None)
        self._entry = ttk.Entry(self, textvariable=self.var, width=width, **kwargs)
        if validate_cmd:
            self._entry.configure(validate="focusout", validatecommand=validate_cmd)
        self._entry.grid(row=0, column=1, sticky="ew")

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def bind(self, sequence: str | None = None, func=None, add=None):  # type: ignore[override]
        return self._entry.bind(sequence, func, add)

    def focus_set(self) -> None:
        self._entry.focus_set()


class CurrencyEntry(LabeledEntry):
    """Entry widget that enforces a currency pattern."""

    def __init__(self, master: tk.Widget, *, label: str) -> None:
        super().__init__(master, label=label, width=16)
        vcmd = (self.register(self._validate), "%P")
        self._entry.configure(validate="focusout", validatecommand=vcmd)

    @staticmethod
    def _validate(value: str) -> bool:
        if not value:
            return True
        try:
            float(value)
        except ValueError:
            return False
        return True


class Table(ttk.Frame):
    """A styled Treeview with scrollbars."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        columns: tuple[str, ...],
        headings: dict[str, str],
        selectmode: str = "browse",
        column_options: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(master)
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode=selectmode,
        )
        column_options = column_options or {}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            anchor = "e" if column in {"planned", "actual", "difference", "amount"} else "w"
            options = dict(column_options.get(column, {}))
            anchor = options.pop("anchor", anchor)
            stretch = options.pop("stretch", True)
            self.tree.column(column, anchor=anchor, stretch=stretch, **options)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def populate(self, rows: list[dict[str, str]], *, key_field: str) -> None:
        """Populate the tree with data dictionaries."""
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            item_id = row.get(key_field, "")
            values = [row.get(column, "") for column in self.tree["columns"]]
            self.tree.insert("", "end", iid=item_id, values=values)

    def bind_double_click(self, callback) -> None:
        self.tree.bind("<Double-1>", callback)
