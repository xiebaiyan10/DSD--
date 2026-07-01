"""
DSD - 打包脚本
打包 exe 输出到桌面。
"""
import os, sys, shutil, subprocess

SRC_DIR = "src"
OUTPUT_NAME = "DSD_抖音无水印下载器.exe"
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")

def clean():
    for d in ["build", "dist"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)

def build():
    print("=" * 50)
    print("DSD 打包工具")
    print("=" * 50)
    clean()

    # 资源文件路径（在 src/ 里）
    ico = os.path.abspath(os.path.join(SRC_DIR, "i.ico"))
    png = os.path.abspath(os.path.join(SRC_DIR, "i.png"))
    entry = os.path.join(SRC_DIR, "dsd.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", "DSD_抖音无水印下载器",
        "--clean", "--noconfirm",
        # 图标
        "--icon", ico,
        # 资源
        "--add-data", f"{png};.",
        # 排除不用的 Qt 模块
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtNetwork",
        "--exclude-module", "PySide6.QtSql",
        "--exclude-module", "PySide6.QtTest",
        "--exclude-module", "PySide6.QtXml",
        "--exclude-module", "PySide6.QtSvg",
        "--exclude-module", "PySide6.QtSvgWidgets",
        "--exclude-module", "PySide6.QtOpenGL",
        "--exclude-module", "PySide6.QtOpenGLWidgets",
        "--exclude-module", "PySide6.QtPrintSupport",
        "--exclude-module", "PySide6.QtDesigner",
        "--exclude-module", "PySide6.QtHelp",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtMultimediaWidgets",
        "--exclude-module", "PySide6.QtSensors",
        "--exclude-module", "PySide6.QtWebChannel",
        "--exclude-module", "PySide6.QtWebEngine",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebSockets",
        "--exclude-module", "PySide6.QtBluetooth",
        "--exclude-module", "PySide6.QtNfc",
        "--exclude-module", "PySide6.QtSerialPort",
        "--exclude-module", "PySide6.QtPositioning",
        "--exclude-module", "PySide6.QtLocation",
        "--exclude-module", "PySide6.QtTextToSpeech",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtDataVisualization",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "requests",
        "--hidden-import", "urllib3",
        "--hidden-import", "certifi",
        "--hidden-import", "charset_normalizer",
        "--hidden-import", "idna",
        entry,
    ]

    print(f"\n入口: {entry}")
    print(f"图标: {ico}")
    print("打包中...\n")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        src = os.path.join("dist", "DSD_抖音无水印下载器.exe")
        dst = os.path.join(DESKTOP, OUTPUT_NAME)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            size = os.path.getsize(dst) / (1024*1024)
            print(f"\n[OK] 打包完成!")
            print(f"    桌面: {dst}")
            print(f"    大小: {size:.1f} MB")
        else:
            print("\n[WARN] exe 未找到")
    else:
        print(f"\n[ERROR] 打包失败，返回码: {result.returncode}")


if __name__ == "__main__":
    build()
