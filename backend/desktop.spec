# Build from backend/: uv run --group desktop pyinstaller --noconfirm desktop.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [(str(root.parent / 'frontend' / 'dist'), 'web')]
binaries = []
hiddenimports = ['keyring.backends.SecretService', 'keyring.backends.macOS', 'keyring.backends.Windows']
# FastEmbed/ONNX and tokenizers load native libraries and model metadata dynamically.
for package in ('fastembed', 'onnxruntime', 'tokenizers'):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden

a = Analysis([str(root / 'src' / 'desktop.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='spoiless-backend', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='spoiless-backend')
