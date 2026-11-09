# PyInstaller spec: freezes the dsd CLI + server + UI into a self-contained one-folder build.
#   uv run --group packaging pyinstaller packaging/dsd.spec --noconfirm --distpath build/pyinstaller
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("mcp")
    + collect_submodules("dsd")
)
datas = collect_data_files("dsd")  # templates/, web/dist/ (the built UI)
for pkg in ("mcp", "fastapi", "starlette", "uvicorn", "typer", "rich", "pydantic", "pydantic_core", "websockets"):
    datas += copy_metadata(pkg)

a = Analysis(
    ["dsd_main.py"],
    pathex=["../src"],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="dsd", console=True,
          target_arch="arm64", codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="dsd")
