"""
抖音无水印下载模块
====================
负责将解析出的 URL 下载到本地文件。
支持视频下载和图集批量下载。
"""

import os
import re
import time
import threading
import requests
from typing import Callable, Optional


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """
    清理文件名，移除非法字符。
    Windows 文件名不能包含: \\ / : * ? \" < > |
    """
    illegal_chars = r'[\\/:*?"<>|]'
    filename = re.sub(illegal_chars, "_", filename)
    # 去除首尾空格和点
    filename = filename.strip(". ")
    # 限制长度
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length - len(ext)] + ext
    return filename if filename else "untitled"


def get_file_extension(url: str, default: str = ".mp4") -> str:
    """
    从 URL 中提取文件扩展名。
    优先从 Content-Type 推断，其次从 URL 路径解析。
    """
    # 去掉 URL 参数和查询
    url_path = url.split("?")[0]
    # 抖音图片 URL 常有 ~xxx:540:q75.jpeg 这种格式
    # 从路径中提取最后一个点后面的扩展名
    basename = url_path.rsplit("/", 1)[-1] if "/" in url_path else url_path
    # 找最后一个点
    if "." in basename:
        ext = "." + basename.rsplit(".", 1)[-1]
        # 清理非ascii
        ext_clean = "".join(c for c in ext if c.isascii() and c.isalpha() or c == ".")
        if len(ext_clean) <= 6 and ext_clean.startswith("."):
            return ext_clean.lower()
    return default


def download_file(
    url: str,
    save_path: str,
    progress_callback: Optional[Callable] = None,
    headers: Optional[dict] = None,
) -> bool:
    """
    下载单个文件，支持进度回调。

    参数:
        url: 下载地址
        save_path: 保存路径
        progress_callback: 进度回调函数 callback(downloaded_bytes, total_bytes)
        headers: 自定义请求头

    返回: 下载是否成功
    """
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            "Referer": "https://www.douyin.com/",
        }

    try:
        response = requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=60,
            allow_redirects=True,
        )
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        # 确保保存目录存在
        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)

        downloaded = 0
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

        # 如果无法获取文件大小，下载完成后回调 100%
        if progress_callback and total_size == 0:
            progress_callback(1, 1)

        return True

    except requests.RequestException as e:
        # 删除不完整的文件
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except OSError:
                pass
        raise e


class DownloadTask:
    """
    下载任务管理器，管理批量下载。
    """

    def __init__(self):
        self._cancel_flag = threading.Event()

    def cancel(self):
        """取消当前下载任务"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancel_flag.is_set()

    def reset(self):
        """重置取消标志"""
        self._cancel_flag.clear()

    def download_video(
        self,
        url: str,
        save_dir: str,
        filename: str,
        log_callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        下载视频文件。

        返回: 保存的文件路径，失败返回 None
        """
        safe_name = sanitize_filename(filename)
        ext = get_file_extension(url, ".mp4")
        save_path = os.path.join(save_dir, f"{safe_name}{ext}")

        # 避免文件名冲突
        counter = 1
        base_path = save_path
        while os.path.exists(save_path):
            name_part = os.path.splitext(base_path)[0]
            save_path = f"{name_part}_{counter}{ext}"
            counter += 1

        if log_callback:
            log_callback(f"⬇ 开始下载视频: {os.path.basename(save_path)}")

        try:
            self.reset()
            download_file(url, save_path, progress_callback)
            if log_callback:
                log_callback(f"✅ 视频下载完成: {os.path.basename(save_path)}")
            return save_path
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 视频下载失败: {str(e)}")
            return None

    def download_images(
        self,
        image_urls: list,
        save_dir: str,
        basename: str,
        log_callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ) -> list:
        """
        批量下载图集图片。

        返回: 成功下载的文件路径列表
        """
        safe_name = sanitize_filename(basename)
        # 为图集创建子目录
        img_dir = os.path.join(save_dir, f"{safe_name}_图集")
        os.makedirs(img_dir, exist_ok=True)

        downloaded_files = []
        total = len(image_urls)

        self.reset()

        for i, url in enumerate(image_urls):
            if self.is_cancelled():
                if log_callback:
                    log_callback("⚠ 下载已取消")
                break

            ext = get_file_extension(url, ".jpg")
            save_path = os.path.join(img_dir, f"{safe_name}_{i+1:03d}{ext}")

            if log_callback:
                log_callback(f"⬇ 下载图片 [{i+1}/{total}]: {os.path.basename(save_path)}")

            try:
                download_file(url, save_path)
                downloaded_files.append(save_path)
                if progress_callback:
                    progress_callback(i + 1, total)
            except Exception as e:
                if log_callback:
                    log_callback(f"❌ 图片 {i+1} 下载失败: {str(e)}")

        if log_callback:
            log_callback(f"✅ 图集下载完成: {len(downloaded_files)}/{total} 张")

        return downloaded_files

    def download_dynamic_cover(
        self,
        url: str,
        save_dir: str,
        basename: str,
        log_callback: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        下载动态封面/动图/Live Photo。

        抖音图集动图格式：
        - dynamic_cover -> WebP 动图 (.webp)
        - live_photo_url -> HEIC (.heic) 或 MOV (.mov)

        策略：先发 HEAD 请求获取真实 Content-Type，据此决定扩展名。
        """
        safe_name = sanitize_filename(basename)
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.douyin.com/",
        }

        # 先发 HEAD 获取真实 Content-Type
        content_type = ""
        try:
            head_resp = requests.head(url, headers=headers, allow_redirects=True, timeout=15)
            content_type = head_resp.headers.get("Content-Type", "").lower()
        except Exception:
            pass

        # 根据 Content-Type 决定扩展名
        ext_map = {
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "image/heic": ".heic",
            "image/heif": ".heif",
        }

        ext = None
        for mime, e in ext_map.items():
            if mime in content_type:
                ext = e
                break

        # 如果 HEAD 没拿到 Content-Type，从 URL 判断
        if not ext:
            url_lower = url.lower()
            if "live_photo" in url_lower:
                ext = ".heic"  # Live Photo 默认 heic
            elif "dynamic_cover" in url_lower:
                ext = ".webp"  # 动态封面默认 webp
            else:
                ext = get_file_extension(url, ".webp")

        label_map = {".webp": "动图WebP", ".mp4": "动图视频", ".mov": "LivePhoto", ".heic": "LivePhoto", ".heif": "LivePhoto"}
        label = label_map.get(ext, "动图")

        save_path = os.path.join(save_dir, f"{safe_name}_{label}{ext}")

        if log_callback:
            log_callback(f"  下载{label}: {os.path.basename(save_path)}")

        try:
            download_file(url, save_path, headers=headers)
            if log_callback:
                log_callback(f"  {label}下载完成: {os.path.basename(save_path)}")
            return save_path
        except Exception as e:
            if log_callback:
                log_callback(f"  {label}下载失败: {str(e)}")
            return None
