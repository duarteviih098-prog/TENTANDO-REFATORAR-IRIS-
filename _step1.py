from pathlib import Path
ROOT = Path('.')
legacy = (ROOT/'app'/'legacy.py').read_text(encoding='utf-8')
if 'Shim temporário' not in legacy:
    import subprocess
    subprocess.run(['python', 'tools/apply_phase2.py'], check=True)
else:
    print('legacy already shim, patching consumers only')
    import subprocess
    subprocess.run(['python', 'tools/apply_phase2.py'], check=True)
