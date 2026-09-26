# PyInstaller build of the desktop app (one folder: fast start, no unpacking at launch).
#
#     python -m PyInstaller packaging/AccidentAI.spec --noconfirm
#
# Output: dist/AccidentAI/AccidentAI.exe. Only the desktop app and its resources are bundled:
# no server code, no training data, and no .env (the installed app talks to the online API).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # the project folder (this file is in packaging/)


def resources():
    files = [
        ("assets/images/app_icon.ico", "assets/images"),
        ("assets/images/app_logo.png", "assets/images"),
        ("assets/images/selftest_frame.jpg", "assets/images"),
        ("assets/yolo/yolov3.cfg", "assets/yolo"),
        ("assets/yolo/coco.names", "assets/yolo"),
        ("assets/yolo/yolov3.weights", "assets/yolo"),
        ("assets/model/model.json", "assets/model"),
        ("assets/model/model_weights.h5", "assets/model"),
    ]
    if os.path.exists(os.path.join(ROOT, "assets/model/accident_model.keras")):  # retrained model, if installed
        files.append(("assets/model/accident_model.keras", "assets/model"))
    missing = [src for src, _ in files if not os.path.exists(os.path.join(ROOT, src))]
    if missing:
        raise SystemExit(f"Missing resources (see README, Installation): {missing}")
    return [(os.path.join(ROOT, src), dest) for src, dest in files]


a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=resources() + collect_data_files("customtkinter"),
    hiddenimports=collect_submodules("desktop") + collect_submodules("pygrabber") + ["comtypes.stream"],
    # Optional dependencies of TensorFlow / Keras the app never uses (PyTorch alone is ~300 MB)
    excludes=["server", "training", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "uvicorn", "fastapi",
              "torch", "torchvision", "torchaudio", "transformers", "tokenizers", "pyarrow", "pandas", "sklearn",
              "pygame", "botocore", "boto3", "imageio", "imageio_ffmpeg", "pydantic", "pythonwin", "win32ui"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AccidentAI",
    icon=os.path.join(ROOT, "assets/images/app_icon.ico"),
    console=False,  # windowed app; `AccidentAI.exe --self-test` writes its report to %TEMP%
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AccidentAI", upx=False)
