"""Entry point for running the budgeting application."""

from __future__ import annotations

import argparse

from .app import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Budgeting desktop application")
    parser.add_argument(
        "--data-file",
        dest="data_file",
        help="Path to the JSON file used to persist budget data (defaults to budget_data.json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_app(args.data_file)


if __name__ == "__main__":
    main()
