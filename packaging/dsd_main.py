"""Entry point for the frozen dsd binary (PyInstaller)."""
from dsd.cli import app

if __name__ == "__main__":
    app(prog_name="dsd")
