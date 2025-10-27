"""Custom Tkinter widgets used by the budgeting app."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Mapping

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
        self._yview_callbacks: list[Callable[[], None]] = []
        self._columns = columns
        self._base_headings = {
            column: headings.get(column, column.replace("_", " ").title())
            for column in columns
        }
        self._sort_column: str | None = None
        self._sort_reverse = False
        column_options = column_options or {}
        for column in columns:
            anchor = "e" if column in {"planned", "actual", "difference", "amount"} else "w"
            options = dict(column_options.get(column, {}))
            anchor = options.pop("anchor", anchor)
            stretch = options.pop("stretch", True)
            self.tree.column(column, anchor=anchor, stretch=stretch, **options)
        self._update_heading_indicators()
        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._on_vertical_scroll)
        self.tree.configure(yscrollcommand=self._on_tree_yview)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self._vsb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def populate(self, rows: list[dict[str, str]], *, key_field: str) -> None:
        """Populate the tree with data dictionaries."""
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            item_id = row.get(key_field, "")
            values = [row.get(column, "") for column in self.tree["columns"]]
            self.tree.insert("", "end", iid=item_id, values=values)
        self._apply_sort()

    def bind_double_click(self, callback) -> None:
        self.tree.bind("<Double-1>", callback)

    def bind_yview(self, callback: Callable[[], None]) -> None:
        """Invoke ``callback`` whenever the vertical viewport changes."""

        self._yview_callbacks.append(callback)

    def _notify_yview_changed(self) -> None:
        for callback in list(self._yview_callbacks):
            callback()

    def _on_vertical_scroll(self, *args) -> None:
        self.tree.yview(*args)
        self._notify_yview_changed()

    def _on_tree_yview(self, *args) -> None:
        self._vsb.set(*args)
        self._notify_yview_changed()

    def _toggle_sort(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._apply_sort()

    def resort(self) -> None:
        """Reapply the current sort order, if any."""

        self._apply_sort()

    def _apply_sort(self) -> None:
        if not self._sort_column:
            self._update_heading_indicators()
            return
        self._sort_items()
        self._update_heading_indicators()

    def _sort_items(self) -> None:
        column = self._sort_column
        if not column:
            return
        children = list(self.tree.get_children(""))
        non_empty: list[tuple[tuple[int, object], int, str]] = []
        empty: list[tuple[int, str]] = []
        for index, item_id in enumerate(children):
            value = self.tree.set(item_id, column)
            if value is None or str(value).strip() == "":
                empty.append((index, item_id))
                continue
            sort_key = self._sort_key(str(value))
            non_empty.append((sort_key, index, item_id))
        non_empty.sort(key=lambda entry: entry[0], reverse=self._sort_reverse)
        ordered = [item_id for _, _, item_id in non_empty]
        ordered.extend(item_id for _, item_id in empty)
        for position, item_id in enumerate(ordered):
            self.tree.move(item_id, "", position)

    @staticmethod
    def _sort_key(value: str) -> tuple[int, object]:
        normalized = value.replace(",", "").strip()
        try:
            number = float(normalized)
        except ValueError:
            return (1, normalized.lower())
        return (0, number)

    def _update_heading_indicators(self) -> None:
        for column in self._columns:
            text = self._base_headings.get(column, column.replace("_", " ").title())
            if column == self._sort_column:
                arrow = "▼" if self._sort_reverse else "▲"
                text = f"{text} {arrow}"
            self.tree.heading(
                column,
                text=text,
                command=lambda col=column: self._toggle_sort(col),
            )


class IncomeExpenseVisual(ttk.Frame):
    """Canvas-based summary that renders income and expense bars."""

    def __init__(self, master: tk.Widget, *, height: int = 96) -> None:
        super().__init__(master)
        style = ttk.Style(self)
        background = style.lookup("TFrame", "background")
        if not background:
            try:
                background = master.cget("background")  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - ttk widgets may not expose cget
                background = "#f0f0f0"
        self._background = background
        self._text_color = style.lookup("TLabel", "foreground") or "#202020"
        self._income = 0.0
        self._expenses = 0.0

        self._canvas = tk.Canvas(
            self,
            height=height,
            highlightthickness=0,
            background=self._background,
            borderwidth=0,
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", self._redraw)

    def update_values(self, *, income: float, expenses: float) -> None:
        """Update the visual with the latest totals."""

        self._income = max(income, 0.0)
        self._expenses = max(expenses, 0.0)
        self._redraw()

    # ------------------------------------------------------------------ #
    # Rendering helpers
    # ------------------------------------------------------------------ #
    def _redraw(self, _event: object | None = None) -> None:
        canvas = self._canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")

        if self._income <= 0.0 and self._expenses <= 0.0:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No income or expenses recorded yet",
                fill="#666666",
                font=("Segoe UI", 9),
            )
            return

        margin = 16
        available_width = max(width - 2 * margin, 1)
        spacing = min(16, height * 0.2)
        bar_height = max((height - (2 * margin) - spacing) / 2, 10)

        max_value = max(self._income, self._expenses, 1.0)
        bars = (
            ("Income", self._income, "#2e7d32"),
            ("Expenses", self._expenses, "#c62828"),
        )

        y = margin
        label_font = ("Segoe UI", 9, "bold")
        value_font = ("Consolas", 10)
        for label, value, colour in bars:
            proportion = 0.0 if max_value <= 0 else value / max_value
            length = proportion * available_width
            if value <= 0:
                length = 0

            x1 = margin
            x2 = margin + length
            if length > 0:
                canvas.create_rectangle(
                    x1,
                    y,
                    x2,
                    y + bar_height,
                    fill=colour,
                    outline=colour,
                )
            else:
                canvas.create_rectangle(
                    x1,
                    y,
                    x1 + 2,
                    y + bar_height,
                    fill=colour,
                    outline=colour,
                )

            canvas.create_text(
                x1,
                y - 2,
                anchor="sw",
                text=label,
                font=label_font,
                fill=self._text_color,
            )

            formatted = f"{value:,.2f}"
            if length >= max(80, available_width * 0.3):
                text_x = x1 + 8
                anchor = "w"
                fill = "#ffffff"
            else:
                text_x = x2 + 6
                anchor = "w"
                fill = self._text_color
            canvas.create_text(
                text_x,
                y + bar_height / 2,
                anchor=anchor,
                text=formatted,
                font=value_font,
                fill=fill,
            )

            y += bar_height + spacing
