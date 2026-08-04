"""
Command-line interface.

Entry point for newsroom intelligence platform.
"""

import typer
from rich.console import Console

from newsroom_intelligence import setup_logging

app = typer.Typer(help="Newsroom Intelligence Platform - Automated news discovery")
console = Console()


@app.callback()
def main(ctx: typer.Context) -> None:
    """Initialize the newsroom intelligence platform."""
    setup_logging()


@app.command()
def fetch(source: str = typer.Option(..., help="Source plugin to fetch from")) -> None:
    """Fetch news from a specific source."""
    console.print(f"[yellow]Fetching from: {source}[/yellow]")
    console.print("[red]Not yet implemented[/red]")


@app.command()
def report(
    confidence_min: float = typer.Option(0.5, help="Minimum confidence threshold"),
    output_format: str = typer.Option("markdown", help="Output format: json, markdown, csv"),
) -> None:
    """Generate editorial report of discovered news."""
    console.print(f"[yellow]Generating report (confidence >= {confidence_min})[/yellow]")
    console.print("[red]Not yet implemented[/red]")


@app.command()
def version() -> None:
    """Show version information."""
    from newsroom_intelligence import __version__
    console.print(f"Newsroom Intelligence Platform v{__version__}")


if __name__ == "__main__":
    app()
