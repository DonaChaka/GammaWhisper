import subprocess
import sys
import os

"""
Builds GammaWhisper executable using PyInstaller.

- Output goes to /dist
- Intermediate files and .spec go to /build
- Templates, static, and transcripts folders are bundled
"""

# --- Config ---
script_name = "run.py"
executable_name = "GammaWhisper"
upx_dir = None  # optional

# --- Paths ---
current_dir = os.path.dirname(os.path.abspath(__file__))
build_dir = os.path.join(current_dir, "build")
dist_dir = os.path.join(current_dir, "dist")
spec_path = build_dir
icon_path = os.path.join(current_dir, "icons", "gamma.ico")

flask_gui_path = os.path.join(current_dir, "flask_gui")

# --- Ensure folders exist ---
os.makedirs(build_dir, exist_ok=True)
os.makedirs(dist_dir, exist_ok=True)

# --- PyInstaller Command ---
command = [
    "pyinstaller",
    "--distpath", dist_dir,
    "--workpath", build_dir,
    "--specpath", spec_path,
    "--name", executable_name,
    # "--windowed",
    "--strip",
    "--icon", icon_path,
    "--paths", flask_gui_path,

    # Include template folder
    f"--add-data={os.path.join(flask_gui_path, 'templates')}{os.pathsep}templates",

    # Include static folder
    f"--add-data={os.path.join(flask_gui_path, 'static')}{os.pathsep}static",

    # Include transcripts folder (critical fix!)
    f"--add-data={os.path.join(flask_gui_path, 'transcripts')}{os.pathsep}transcripts",

    script_name
]

if upx_dir:
    command.append(f"--upx-dir={upx_dir}")

# --- Run build ---
try:
    subprocess.run(command, check=True)
    print(f"\n✅ Executable successfully created inside '{dist_dir}'")
except subprocess.CalledProcessError as e:
    print(f"\n❌ PyInstaller failed: {e}")
    sys.exit(1)
