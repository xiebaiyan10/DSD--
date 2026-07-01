"""
DSD - 抖音无水印下载器 (Douyin Sniffer & Downloader)
=====================================================
基于 PySide6 + Requests，纯 HTTP 请求实现。

用法:
    python dsd.py          启动 GUI
    python dsd.py --cli    命令行模式
"""

import sys
import os
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap

from douyin_parser import parse_douyin_url, extract_url_from_text
from downloader import DownloadTask


def resource_path(relative_path: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


class DSDFonts:
    TITLE = QFont("Microsoft YaHei", 18, QFont.Bold)
    SUBTITLE = QFont("Microsoft YaHei", 10)
    LOG = QFont("Consolas", 10)
    BUTTON = QFont("Microsoft YaHei", 11)


class DSDMainWindow(QMainWindow):
    _sig_download_done = Signal(bool)
    _sig_log = Signal(str)
    _sig_progress = Signal(int, int)
    _sig_parse_done = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DSD - 抖音无水印下载器")
        self.setMinimumSize(680, 640)
        self.resize(700, 680)

        icon_path = resource_path("i.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.parse_result = None
        self.download_task = DownloadTask()
        self.default_download_dir = os.path.join(os.path.expanduser("~"), "Downloads", "DSD_Downloads")

        self._sig_download_done.connect(self._on_download_finished)
        self._sig_log.connect(self._do_log)
        self._sig_progress.connect(self._do_progress)
        self._sig_parse_done.connect(self._on_parse_finished)

        self._init_ui()
        self._apply_styles()

    # ============================================================
    # UI
    # ============================================================
    def _init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        lay = QVBoxLayout(cw)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 16, 20, 16)

        icon_path = resource_path("i.png")
        app_icon = QPixmap(icon_path) if os.path.exists(icon_path) else None

        # 标题
        tl = QHBoxLayout()
        tl.setAlignment(Qt.AlignCenter)
        if app_icon:
            il = QLabel()
            il.setPixmap(app_icon.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            il.setFixedSize(44, 44)
            tl.addWidget(il)
        tt = QLabel("DSD - 抖音无水印下载器")
        tt.setFont(DSDFonts.TITLE)
        tt.setAlignment(Qt.AlignCenter)
        tl.addWidget(tt)
        lay.addLayout(tl)

        sub = QLabel("粘贴抖音分享链接 -> 解析 -> 选择下载方式 -> 下载")
        sub.setFont(DSDFonts.SUBTITLE)
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color: #888;")
        lay.addWidget(sub)

        # 输入区域
        ig = QGroupBox("输入抖音链接")
        il = QHBoxLayout(ig)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("在此粘贴抖音分享链接或口令，如 https://v.douyin.com/xxxxx/")
        self.url_input.setMinimumHeight(36)
        self.url_input.setFont(QFont("Microsoft YaHei", 10))
        self.url_input.returnPressed.connect(self.on_parse_clicked)
        il.addWidget(self.url_input)
        self.parse_btn = QPushButton("解析")
        self.parse_btn.setMinimumHeight(36)
        self.parse_btn.setMinimumWidth(80)
        self.parse_btn.setFont(DSDFonts.BUTTON)
        self.parse_btn.clicked.connect(self.on_parse_clicked)
        il.addWidget(self.parse_btn)
        lay.addWidget(ig)

        # 信息区域
        ig2 = QGroupBox("作品信息")
        il2 = QVBoxLayout(ig2)
        self.info_label = QLabel("等待解析...")
        self.info_label.setFont(QFont("Microsoft YaHei", 10))
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.RichText)
        il2.addWidget(self.info_label)
        lay.addWidget(ig2)

        # 下载方式选择
        ig3 = QGroupBox("下载方式（可多选）")
        il3 = QHBoxLayout(ig3)
        self.chk_video = QCheckBox("视频 (1080p无水印)")
        self.chk_video.setChecked(True)
        self.chk_video.setFont(QFont("Microsoft YaHei", 10))
        il3.addWidget(self.chk_video)

        self.chk_images = QCheckBox("图片 (静态图)")
        self.chk_images.setChecked(True)
        self.chk_images.setFont(QFont("Microsoft YaHei", 10))
        il3.addWidget(self.chk_images)

        self.chk_dynamic = QCheckBox("实况/动图 (WebP/HEIC)")
        self.chk_dynamic.setChecked(True)
        self.chk_dynamic.setFont(QFont("Microsoft YaHei", 10))
        il3.addWidget(self.chk_dynamic)
        lay.addWidget(ig3)

        # 下载按钮区
        ig4 = QGroupBox("下载操作")
        il4 = QHBoxLayout(ig4)
        self.download_btn = QPushButton("开始下载")
        self.download_btn.setMinimumHeight(40)
        self.download_btn.setFont(DSDFonts.BUTTON)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.on_download_clicked)
        il4.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.setFont(DSDFonts.BUTTON)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        il4.addWidget(self.cancel_btn)

        self.open_dir_btn = QPushButton("打开目录")
        self.open_dir_btn.setMinimumHeight(40)
        self.open_dir_btn.setMinimumWidth(100)
        self.open_dir_btn.setFont(DSDFonts.BUTTON)
        self.open_dir_btn.clicked.connect(self.on_open_dir_clicked)
        il4.addWidget(self.open_dir_btn)
        lay.addWidget(ig4)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        lay.addWidget(self.progress_bar)

        # 日志
        lg = QGroupBox("运行日志")
        ll = QVBoxLayout(lg)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(DSDFonts.LOG)
        self.log_text.setMinimumHeight(150)
        self.log_text.setPlaceholderText("日志将显示在这里...")
        ll.addWidget(self.log_text)
        lay.addWidget(lg)

        bottom = QLabel("DSD v1.1 | 仅供学习交流使用 | 请尊重创作者版权")
        bottom.setAlignment(Qt.AlignCenter)
        bottom.setStyleSheet("color: #999; font-size: 11px;")
        lay.addWidget(bottom)

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f6fa; }
            QGroupBox {
                font-size: 13px; font-weight: bold; color: #2d3436;
                border: 1px solid #dfe6e9; border-radius: 8px;
                margin-top: 8px; padding-top: 16px; background-color: #ffffff;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QLineEdit {
                border: 2px solid #dfe6e9; border-radius: 6px;
                padding: 4px 10px; background-color: #ffffff;
            }
            QLineEdit:focus { border-color: #0984e3; }
            QPushButton { border: none; border-radius: 6px; padding: 6px 16px; color: white; }
            QPushButton#parseBtn { background-color: #0984e3; }
            QPushButton#parseBtn:hover { background-color: #0773c5; }
            QPushButton#downloadBtn { background-color: #00b894; }
            QPushButton#downloadBtn:hover { background-color: #00a381; }
            QPushButton#cancelBtn { background-color: #d63031; }
            QPushButton#cancelBtn:hover { background-color: #c0262c; }
            QPushButton#openDirBtn { background-color: #636e72; }
            QPushButton#openDirBtn:hover { background-color: #555e60; }
            QPushButton:disabled { background-color: #b2bec3 !important; }
            QProgressBar {
                border: 1px solid #dfe6e9; border-radius: 4px;
                text-align: center; background-color: #ffffff;
            }
            QProgressBar::chunk { background-color: #00b894; border-radius: 3px; }
            QTextEdit {
                border: 1px solid #dfe6e9; border-radius: 6px;
                padding: 6px; background-color: #2d3436; color: #dfe6e9;
            }
            QCheckBox { spacing: 6px; }
        """)
        self.parse_btn.setObjectName("parseBtn")
        self.download_btn.setObjectName("downloadBtn")
        self.cancel_btn.setObjectName("cancelBtn")
        self.open_dir_btn.setObjectName("openDirBtn")

    # ============================================================
    # 日志 / 状态
    # ============================================================
    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def set_busy(self, busy: bool):
        self.parse_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy and self.parse_result is not None)
        self.cancel_btn.setEnabled(busy)
        self.url_input.setEnabled(not busy)

    # ============================================================
    # 解析
    # ============================================================
    def on_parse_clicked(self):
        raw = self.url_input.text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请先粘贴抖音分享链接！")
            return
        url = extract_url_from_text(raw)
        if not url:
            QMessageBox.warning(self, "提示", "未能从输入中识别出抖音链接，请检查后重试！")
            return

        self.log(f"开始解析: {url}")
        self.set_busy(True)
        self.parse_result = None
        self.info_label.setText("正在解析中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        def worker():
            result = parse_douyin_url(url)
            self._sig_parse_done.emit(result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_parse_finished(self, result: dict):
        self.progress_bar.setVisible(False)
        self.set_busy(False)
        self.parse_result = result

        if result["success"]:
            type_names = {"video": "视频", "image": "图集", "mixed": "视频+图集"}
            self.log(f"解析成功! 类型: {type_names.get(result['type'], result['type'])}")

            parts = [
                f"<b>作者:</b> {result.get('author', '未知')}",
                f"<b>类型:</b> {type_names.get(result['type'], result['type'])}",
                f"<b>描述:</b> {result.get('desc', '无')[:80]}",
            ]
            if result.get("video_url"):
                parts.append("<b>视频:</b> 已解析 1080p 无水印地址")
            if result.get("images"):
                parts.append(f"<b>图片:</b> {len(result['images'])} 张")
            if result.get("dynamic_url"):
                parts.append("<b>实况/动图:</b> 已检测到")

            self.info_label.setText("<br>".join(parts))

            # 根据解析结果自动调整复选框
            has_vid = bool(result.get("video_url"))
            has_img = bool(result.get("images"))
            has_dyn = bool(result.get("dynamic_url"))

            self.chk_video.setEnabled(has_vid)
            self.chk_images.setEnabled(has_img)
            self.chk_dynamic.setEnabled(has_dyn)

            if not has_vid: self.chk_video.setChecked(False)
            if not has_img: self.chk_images.setChecked(False)
            if not has_dyn: self.chk_dynamic.setChecked(False)

            self.download_btn.setEnabled(True)
        else:
            self.log(f"解析失败: {result.get('error', '未知错误')}")
            self.info_label.setText(f"<span style='color:red;'>解析失败: {result.get('error', '')}</span>")
            self.download_btn.setEnabled(False)

    # ============================================================
    # 下载
    # ============================================================
    def on_download_clicked(self):
        if not self.parse_result or not self.parse_result.get("success"):
            QMessageBox.warning(self, "提示", "请先成功解析链接后再下载！")
            return

        # 检查是否至少选择了一项
        if not any([self.chk_video.isChecked(), self.chk_images.isChecked(), self.chk_dynamic.isChecked()]):
            QMessageBox.warning(self, "提示", "请至少选择一种下载方式！")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", self.default_download_dir)
        if not save_dir:
            return

        os.makedirs(save_dir, exist_ok=True)
        self.default_download_dir = save_dir

        basename = self.parse_result.get("desc", "douyin").strip() or self.parse_result.get("item_id", "douyin")

        # 读取用户选择
        want_video = self.chk_video.isChecked() and self.chk_video.isEnabled()
        want_images = self.chk_images.isChecked() and self.chk_images.isEnabled()
        want_dynamic = self.chk_dynamic.isChecked() and self.chk_dynamic.isEnabled()

        self.log(f"开始下载到: {save_dir}")
        self.set_busy(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        def worker():
            result = self.parse_result
            task = self.download_task
            downloaded = []

            try:
                if want_video and result.get("video_url"):
                    path = task.download_video(
                        url=result["video_url"], save_dir=save_dir, filename=basename,
                        log_callback=lambda m: self._safe_log(m),
                    )
                    if path: downloaded.append(path)

                if want_images and result.get("images"):
                    paths = task.download_images(
                        image_urls=result["images"], save_dir=save_dir, basename=basename,
                        log_callback=lambda m: self._safe_log(m),
                        progress_callback=lambda c, t: self._safe_progress(c, t),
                    )
                    downloaded.extend(paths)

                if want_dynamic and result.get("dynamic_url"):
                    path = task.download_dynamic_cover(
                        url=result["dynamic_url"], save_dir=save_dir, basename=basename,
                        log_callback=lambda m: self._safe_log(m),
                    )
                    if path: downloaded.append(path)

                self._safe_log(f"全部完成! 共下载 {len(downloaded)} 个文件")
                self._safe_log(f"保存位置: {save_dir}")
                self._sig_download_done.emit(True)

            except Exception as e:
                self._safe_log(f"下载出错: {str(e)}")
                self._sig_download_done.emit(False)

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # 线程安全回调
    # ============================================================
    def _safe_log(self, msg: str):
        self._sig_log.emit(msg)

    def _do_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _safe_progress(self, cur: int, tot: int):
        self._sig_progress.emit(cur, tot)

    def _do_progress(self, cur: int, tot: int):
        if tot > 0:
            self.progress_bar.setValue(int(cur / tot * 100))

    def _on_download_finished(self, success: bool):
        self.progress_bar.setVisible(False)
        self.set_busy(False)
        self.download_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "完成", "下载完成！\n点击「打开目录」查看文件。")
        else:
            QMessageBox.warning(self, "提示", "下载过程中出现错误，请查看日志。")

    def on_cancel_clicked(self):
        self.download_task.cancel()
        self.log("正在取消下载...")
        self.set_busy(False)
        self.progress_bar.setVisible(False)

    def on_open_dir_clicked(self):
        os.makedirs(self.default_download_dir, exist_ok=True)
        os.startfile(self.default_download_dir)


# ============================================================
# 命令行模式
# ============================================================
def run_cli(url: str):
    from downloader import DownloadTask
    print("DSD CLI")
    print(f"解析: {url}")
    result = parse_douyin_url(url)
    if not result["success"]:
        print(f"失败: {result['error']}")
        return
    print(f"成功! 作者: {result['author']}  类型: {result['type']}")
    save_dir = os.path.join(os.path.expanduser("~"), "Downloads", "DSD_Downloads")
    os.makedirs(save_dir, exist_ok=True)
    basename = result.get("desc", "douyin").strip() or "douyin"
    task = DownloadTask()
    if result.get("video_url"):
        print("下载视频...")
        task.download_video(result["video_url"], save_dir, basename)
    if result.get("images"):
        print(f"下载图集 ({len(result['images'])} 张)...")
        task.download_images(result["images"], save_dir, basename)
    if result.get("dynamic_url"):
        print("下载动图...")
        task.download_dynamic_cover(result["dynamic_url"], save_dir, basename)
    print(f"完成! {save_dir}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        url = sys.argv[2] if len(sys.argv) > 2 else input("请输入抖音分享链接: ").strip()
        run_cli(url)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("DSD")
    window = DSDMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
