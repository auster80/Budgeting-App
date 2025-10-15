# Budgeting Desktop App

This project provides a lightweight Windows-friendly budgeting application built with Python and Tkinter. It focuses on quick setup, simple data persistence, and an extensible structure for future budgeting features.

## Features

- Categorise income and expenses with planned and actual amounts.
- Track transactions and automatically roll totals into their categories.
- Persist data to a local JSON file (stored in the project directory by default).
- Responsive Tkinter UI with category and transaction tables.
- Built-in menu and status bar for quick import/save actions.
- CSV importer (Rabobank export format) with account-aware tracking and quick category assignment.

## Requirements

- Python 3.10 or later (developed against Python 3.13.6).
- [OpenAI Python SDK](https://github.com/openai/openai-python) for AI-assisted categorisation.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
python src\budgeting_app\main.py
```

The app stores its data in `budget_data.json`. You can change this path with the `--data-file` argument.

### Importing transactions

1. Make sure you have defined the categories you want to use.
2. Use **File → Import CSV...** (or the **Import CSV...** button in the Transactions pane) and pick a Rabobank export file.
3. Newly imported transactions appear with their source account and can be assigned to categories using the **Assign** control beneath the table.

## Project Structure

- `src/budgeting_app/app.py` – Tkinter application wiring and screen layout.
- `src/budgeting_app/models.py` – Data models for budget categories and transactions.
- `src/budgeting_app/storage.py` – JSON persistence helpers.
- `src/budgeting_app/viewmodels.py` – Glue between the UI and data layer.
- `src/budgeting_app/widgets.py` – Custom Tkinter widgets used by the app.
- `src/budgeting_app/main.py` – Entry point that launches the app.

## Enabling AI-powered categorisation

The AI classification features call OpenAI's ChatGPT models. To activate them:

1. Create an OpenAI API key from the [OpenAI dashboard](https://platform.openai.com/account/api-keys).
2. Set the `OPENAI_API_KEY` environment variable **before** launching the app.
   - PowerShell: `setx OPENAI_API_KEY "sk-..."` and restart your shell.
   - macOS/Linux: `export OPENAI_API_KEY="sk-..."` in the terminal session that starts the app.
3. (Optional) Persist the variable in your shell profile (e.g. `$PROFILE`, `~/.bashrc`, or `~/.zshrc`) so future sessions pick it up.

If the key is not configured, the app falls back to a local heuristic classifier and the AI log explains how classifications were produced.

## Next Steps

- Add import/export support (CSV/Excel).
- Implement visual charts for spending trends (e.g., via `matplotlib`).
- Integrate envelope-style budgeting rules or budget period comparisons.
- Wrap the app in a standalone Windows executable using `pyinstaller` or `briefcase`.
