"""
Dedicated entry point for packaged executable (flet pack / PyInstaller).
Sets CWD correctly and forces UI mode without requiring argparse.
"""
import sys
import os
from pathlib import Path

# When frozen as .exe, set working directory to the folder containing the exe
# so that relative paths (data/, .env) resolve correctly
if getattr(sys, "frozen", False):
    exe_dir = Path(sys.executable).parent
    os.chdir(exe_dir)
    # data/ and .env should live next to the exe after packaging
    sys.path.insert(0, str(exe_dir))

# Bypass argparse — always launch the GUI
sys.argv = [sys.argv[0], "ui"]

from main import main

if __name__ == "__main__":
    main()
