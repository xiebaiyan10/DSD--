"""
抖音无水印解析核心模块
=========================
本模块负责从抖音分享链接中提取无水印视频/图集的真实下载地址。

解析策略（按优先级）：
1. 【主策略】SSR页面解析：访问短链 -> 跟随重定向 -> 从页面 _ROUTER_DATA 中提取数据
   这是当前最稳定的方式，因为抖音 API 需要加密签名（a-bogus），
   但 SSR 渲染的页面中直接内嵌了完整的视频 JSON 数据。

2. 【备用策略】API 直接请求：如果 SSR 解析失败，尝试请求 iteminfo API

抖音接口解析流程：
1. 解析短链 -> 获取重定向后的完整 URL
2. 请求重定向页面 -> 从 HTML 的 _ROUTER_DATA 中提取 JSON
3. 视频：从 JSON 中提取 play_addr，将 /playwm/ 替换为 /play/
4. 图集：提取 images 列表 + dynamic_cover/live_photo_url
5. 请求替换后的 URL -> 跟随 302 重定向 -> 获取真实下载地址

【接口变动预留】如果抖音更新了 SSR 数据结构或 JSON 字段路径，
请在下方 SSR_CONFIG 和 JSON_PATH 字典中修改对应配置项。
"""

import re
import json
import time as _time
import requests
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlunparse


# ============================================================
# 全局配置区（接口变动时修改此处）
# ============================================================
SSR_CONFIG = {
    # SSR 页面中数据所在的 window 变量名
    # 当前抖音使用 window._ROUTER_DATA
    "data_var": "_ROUTER_DATA",

    # _ROUTER_DATA 中 aweme 数据的 JSON 路径
    # loaderData -> video_(id)/page -> videoInfoRes -> item_list -> [0]
    "aweme_path_in_ssr": ["loaderData", "video_(id)/page", "videoInfoRes", "item_list"],

    # 请求超时时间（秒）
    "timeout": 30,
}

# ============================================================
# HTTP 请求头配置
# ============================================================
def build_headers(referer: str = "https://www.douyin.com/") -> Dict[str, str]:
    """
    构建请求头（模拟手机端访问，这是绕过抖音反爬的关键）

    注意：经过测试，Accept-Encoding 和 Accept-Language 头会触发抖音反爬，
    导致返回简化版页面（不含 _ROUTER_DATA）。因此这里只保留最精简的头。
    """
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": referer,
    }


# ============================================================
# 链接提取模块（从抖音口令文本中提取纯链接）
# ============================================================
def extract_url_from_text(text: str) -> Optional[str]:
    """
    从抖音分享口令/任意文本中提取抖音链接。

    用户粘贴的通常是整段口令文本，例如：
    "0.00 11/15 :3pm zte:/ v@S.yt 世界最最神秘... https://v.douyin.com/r_gn1oUzQ9M/ 复制此链接..."

    需要从中提取出真正的 URL。

    返回: 纯链接字符串，或 None
    """
    # 策略1: 正则匹配 https?:// 开头的链接
    douyin_domains = [
        r"https?://v\.douyin\.com/[^\s]+",
        r"https?://www\.douyin\.com/[^\s]+",
        r"https?://www\.iesdouyin\.com/[^\s]+",
        r"https?://douyin\.com/[^\s]+",
        r"https?://iesdouyin\.com/[^\s]+",
    ]

    for pattern in douyin_domains:
        match = re.search(pattern, text)
        if match:
            url = match.group(0)
            url = url.rstrip(".,;:!?，。；：！？、】）)")
            return url

    # 策略2: 尝试从文本中查找 v.douyin.com 并补全协议
    short_match = re.search(r'v\.douyin\.com/[A-Za-z0-9_/]+', text)
    if short_match:
        url = "https://" + short_match.group(0)
        url = url.rstrip(".,;:!?，。；：！？、】）)")
        return url

    return None


# ============================================================
# SSR 页面解析模块（主策略）
# ============================================================
def _extract_ssr_data(html: str) -> Optional[Dict]:
    """
    从 SSR 渲染的 HTML 页面中提取内嵌的 JSON 数据。

    抖音的分享页面是 SSR（服务端渲染）的，HTML 中通过
    window._ROUTER_DATA = {...} 内嵌了完整的视频信息。

    返回: 解析后的 JSON 数据，或 None
    """
    var_name = SSR_CONFIG["data_var"]

    # 找到 window._ROUTER_DATA 的位置
    idx = html.find(f"window.{var_name}")
    if idx < 0:
        return None

    try:
        # 从 = 号后面开始
        eq_idx = html.index("=", idx)
        start = eq_idx + 1

        # 找到结尾的 </script>
        end = html.index("</script>", start)
        raw = html[start:end].strip()

        # 去掉末尾分号
        if raw.endswith(";"):
            raw = raw[:-1]

        data = json.loads(raw)
        return data
    except (ValueError, json.JSONDecodeError):
        return None


def _find_aweme_in_ssr(data: Dict) -> Optional[Dict]:
    """
    在 SSR 数据中递归查找 aweme（视频/图集）对象。

    SSR 数据路径: loaderData -> video_(id)/page -> videoInfoRes -> item_list -> [0]

    如果预定义路径找不到，则递归搜索整个数据结构。
    """
    # 策略1: 使用预定义路径查找
    def get_nested(obj, path):
        for key in path:
            if isinstance(obj, dict):
                # 支持模糊匹配：如果 key 包含 "(id)"，则匹配任意包含该模式的 key
                if "(id)" in key:
                    found = None
                    prefix = key.split("(id)")[0]
                    for k in obj:
                        if k.startswith(prefix):
                            found = obj[k]
                            break
                    obj = found
                else:
                    obj = obj.get(key)
            elif isinstance(obj, list):
                if key.isdigit():
                    obj = obj[int(key)] if int(key) < len(obj) else None
                else:
                    return None
            else:
                return None
            if obj is None:
                return None
        return obj

    # 尝试预定义路径
    item_list = get_nested(data, SSR_CONFIG["aweme_path_in_ssr"])
    if item_list and isinstance(item_list, list) and len(item_list) > 0:
        return item_list[0]

    # 策略2: 递归搜索（兼容路径变化）
    def recursive_find(obj, depth=0, max_depth=7):
        if depth > max_depth or obj is None:
            return None
        if isinstance(obj, dict):
            # 检查是否包含 video + play_addr（视频特征）
            if "video" in obj and isinstance(obj["video"], dict):
                v = obj["video"]
                if "play_addr" in v or "download_addr" in v:
                    return obj
            # 检查是否包含 images（图集特征）
            if "images" in obj and isinstance(obj["images"], list) and len(obj["images"]) > 0:
                if "video" in obj or "desc" in obj:
                    return obj
            for v in obj.values():
                result = recursive_find(v, depth + 1, max_depth)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = recursive_find(item, depth + 1, max_depth)
                if result:
                    return result
        return None

    return recursive_find(data)


# ============================================================
# 短链解析 + SSR 数据获取（带重试和备用策略）
# ============================================================
def _fetch_html(session, url: str, headers: dict) -> str:
    """请求页面 HTML"""
    resp = session.get(url, headers=headers, timeout=SSR_CONFIG["timeout"])
    return resp.text


def _try_extract_from_html(html: str) -> Optional[Dict]:
    """尝试从 HTML 中提取 aweme 数据"""
    ssr_data = _extract_ssr_data(html)
    if not ssr_data:
        return None
    return _find_aweme_in_ssr(ssr_data)


def resolve_and_fetch(share_url: str) -> Tuple[Optional[Dict], Optional[str]]:
    """
    解析短链并获取视频/图集数据（带重试机制）。

    策略:
    1. 如果是短链，跟随重定向获取最终页面 URL
    2. 请求最终页面 HTML，提取 _ROUTER_DATA
    3. 如果失败，等待1秒后用新 Session 重试（最多3次）
    4. 如果还失败，尝试从 URL 提取 item_id，构造 douyin.com 页面 URL 再试

    返回: (aweme数据字典, 错误信息)
    """
    headers = build_headers()
    MAX_RETRIES = 3
    last_error = None

    # 步骤1: 处理短链重定向（只做一次，短链重定向结果不变）
    final_url = share_url
    item_id = None

    # 如果已经是完整链接（非短链），直接提取 item_id
    id_patterns = [
        r"/video/(\d+)", r"/note/(\d+)",
        r"/share/video/(\d+)", r"/share/note/(\d+)",
    ]
    for p in id_patterns:
        m = re.search(p, share_url)
        if m:
            item_id = m.group(1)
            final_url = share_url
            break

    # 短链：先获取重定向目标
    if "v.douyin.com" in share_url:
        try:
            s = requests.Session()
            resp = s.get(share_url, headers=headers, allow_redirects=True, timeout=SSR_CONFIG["timeout"])
            final_url = resp.url
            # 从重定向 URL 中提取 item_id
            for p in id_patterns:
                m = re.search(p, final_url)
                if m:
                    item_id = m.group(1)
                    break
            # 如果还没提取到，尝试用数字匹配
            if not item_id:
                m = re.search(r'(\d{15,25})', final_url)
                if m:
                    item_id = m.group(1)
        except requests.RequestException as e:
            return None, f"短链解析失败: {str(e)}"

    # 步骤2: 多次尝试从 SSR 页面提取数据
    for attempt in range(MAX_RETRIES):
        try:
            session = requests.Session()
            html = _fetch_html(session, final_url, headers)
            aweme = _try_extract_from_html(html)

            if aweme:
                return aweme, None

            # 如果 HTML 太短（反爬页面），记录并重试
            if len(html) < 15000:
                last_error = f"页面异常（仅{len(html)}字节），疑似触发反爬"
            else:
                last_error = f"HTML正常但未找到视频数据（{len(html)}字节）"

        except requests.RequestException as e:
            last_error = f"网络请求失败: {str(e)}"

        # 重试前等待，并换新 Session
        if attempt < MAX_RETRIES - 1:
            _time.sleep(1.0)

    # 步骤3: 备用策略 - 如果有 item_id，尝试直接访问 douyin.com 页面
    if item_id:
        try:
            douyin_page_url = f"https://www.douyin.com/video/{item_id}"
            session = requests.Session()
            html = _fetch_html(session, douyin_page_url, headers)
            aweme = _try_extract_from_html(html)

            if aweme:
                return aweme, None

            if len(html) < 15000:
                last_error = f"备用douyin.com页面也异常（{len(html)}字节）"
        except requests.RequestException as e:
            last_error = f"备用策略网络失败: {str(e)}"

    return None, f"解析失败（已重试{MAX_RETRIES}次）: {last_error}"


# ============================================================
# 视频解析模块
# ============================================================
def extract_video_url(item_data: Dict) -> Tuple[Optional[str], Optional[str]]:
    """
    从 item JSON 数据中提取【最高清无水印】视频真实下载地址。

    策略（按优先级）：
    1. 提取 play_addr.url_list[0] 的原始 URL
    2. /playwm/ 替换为 /play/（去水印）
    3. ratio 参数强制设为 1080p（最高清）
    4. 去掉 logo_name 参数（去水印标记）
    5. 跟随 302 重定向获取 CDN 真实地址

    JSON 路径（可在下面修改以适配接口变化）：
    - video -> play_addr -> url_list -> [0]
    - video -> play_addr_h264 -> url_list -> [0]
    """
    # ============================================================
    # JSON 路径配置区（接口字段变动时修改此处）
    # ============================================================
    JSON_PATH = {
        "video_play_addr": ["video", "play_addr", "url_list"],
        "video_play_addr_h264": ["video", "play_addr_h264", "url_list"],
    }

    def get_nested(data: Dict, path: List[str]):
        for key in path:
            if isinstance(data, dict):
                data = data.get(key)
            elif isinstance(data, list) and key.isdigit():
                data = data[int(key)]
            else:
                return None
        return data

    # 尝试多个播放地址路径
    raw_url = None
    for path_name, path in JSON_PATH.items():
        url_list = get_nested(item_data, path)
        if url_list and isinstance(url_list, list) and len(url_list) > 0:
            raw_url = url_list[0]
            break

    if not raw_url:
        return None, "无法提取视频播放地址"

    # ============================================================
    # 构建最优无水印高清地址
    # ============================================================
    # 步骤1: /playwm/ -> /play/（去水印核心操作）
    clean_url = raw_url.replace("/playwm/", "/play/")

    # 步骤2: 替换 ratio 为最高清 1080p
    # 原始URL可能包含 ratio=720p 或 ratio=540p 等
    clean_url = re.sub(r'ratio=[^&]+', 'ratio=1080p', clean_url)

    # 步骤3: 去掉 logo_name 参数（水印标记）
    # logo_name=aweme_diversion_search 会在视频中叠加搜索引导水印
    parsed = urlparse(clean_url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    if "logo_name" in params:
        del params["logo_name"]
    new_query = "&".join(f"{k}={v}" for k, v in params.items())
    clean_url = urlunparse(parsed._replace(query=new_query))

    # 步骤4: 请求优化后的 URL，跟随 302 重定向获取 CDN 真实地址
    try:
        session = requests.Session()
        headers = build_headers()
        response = session.get(
            clean_url,
            headers=headers,
            allow_redirects=True,
            timeout=SSR_CONFIG["timeout"],
        )
        real_url = response.url
        return real_url, None

    except requests.RequestException as e:
        # 降级：如果 1080p 失败，尝试原始 ratio
        try:
            fallback_url = raw_url.replace("/playwm/", "/play/")
            resp = session.get(fallback_url, headers=headers, allow_redirects=True, timeout=SSR_CONFIG["timeout"])
            return resp.url, None
        except requests.RequestException:
            return None, f"获取视频地址失败: {str(e)}"


# ============================================================
# 图集解析模块
# ============================================================
def extract_images(item_data: Dict) -> Tuple[List[str], str, Optional[str]]:
    """
    从图集 JSON 数据中提取所有图片/动图下载地址。

    抖音图集结构：
    - images[].url_list[] = 静态图片（.jpeg/.webp 缩略图）
    - video.dynamic_cover.url_list[] = 动态 WebP 动图（.webp）
    - video.live_photo_url = Live Photo（.heic/.mov 苹果格式）

    注意：url_list[0] 可能是带水印的低清版本，取 url_list 中
    看起来最长的 URL（通常是最后一个或分辨率最高的）。
    """
    JSON_PATH = {
        "images": ["images"],
        "dynamic_cover": ["video", "dynamic_cover", "url_list"],
        "live_photo": ["video", "live_photo_url"],
        "origin_cover": ["video", "origin_cover", "url_list"],
        "cover": ["video", "cover", "url_list"],
    }

    def get_nested(data: Dict, path: List[str]):
        for key in path:
            if isinstance(data, dict):
                data = data.get(key)
            elif isinstance(data, list) and key.isdigit():
                data = data[int(key)]
            else:
                return None
        return data

    def pick_best_static(url_list: list) -> Optional[str]:
        """从 url_list 中选最优静态图片：优先 jpeg/jpg，其次 png，最后其他"""
        if not url_list or not isinstance(url_list, list):
            return None
        valid = [u for u in url_list if isinstance(u, str) and u.startswith("http")]
        if not valid:
            return None
        # 优先选 jpeg/jpg 格式
        for ext in (".jpeg", ".jpg", ".png"):
            for u in valid:
                if ext in u.lower().split("?")[0]:
                    return u
        # 兜底取最长
        valid.sort(key=len, reverse=True)
        return valid[0]

    def pick_best_dynamic(url_list: list) -> Optional[str]:
        """从 url_list 中选最优动图 URL"""
        if not url_list or not isinstance(url_list, list):
            return None
        valid = [u for u in url_list if isinstance(u, str) and u.startswith("http")]
        if not valid:
            return None
        valid.sort(key=len, reverse=True)
        return valid[0]

    image_urls = []
    media_type = "static"
    dynamic_url = None

    # 1. 提取图集静态图片列表（只取 jpeg/jpg/png 格式）
    images = get_nested(item_data, JSON_PATH["images"])
    if images and isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                url_list = img.get("url_list", [])
                img_url = pick_best_static(url_list)
                if img_url:
                    # 去掉 watermask 参数
                    img_url = re.sub(r'watermask=[^&]*&?', '', img_url)
                    img_url = img_url.rstrip('&')
                    image_urls.append(img_url)

    # 2. 提取动态封面（WebP 动图）— 仅用于"实况/动图"选项
    dynamic_cover_list = get_nested(item_data, JSON_PATH["dynamic_cover"])
    if dynamic_cover_list and isinstance(dynamic_cover_list, list) and len(dynamic_cover_list) > 0:
        best = pick_best_dynamic(dynamic_cover_list)
        if best:
            dynamic_url = best
            media_type = "dynamic_webp"

    # 3. 提取 Live Photo URL
    live_photo_data = get_nested(item_data, JSON_PATH["live_photo"])
    if live_photo_data:
        if isinstance(live_photo_data, list) and len(live_photo_data) > 0:
            best = pick_best_dynamic(live_photo_data)
            if best and not dynamic_url:
                dynamic_url = best
                media_type = "live_photo"
        elif isinstance(live_photo_data, str) and live_photo_data.startswith("http"):
            if not dynamic_url:
                dynamic_url = live_photo_data
                media_type = "live_photo"

    # 4. 兜底：如果没有图片，尝试用封面（同样优先 jpeg）
    if not image_urls:
        for cover_key in ["origin_cover", "cover"]:
            cover = get_nested(item_data, JSON_PATH[cover_key])
            if cover and isinstance(cover, list):
                best = pick_best_static(cover)
                if best:
                    image_urls.append(best)
                    break

    return image_urls, media_type, dynamic_url


# ============================================================
# 主解析入口
# ============================================================
def parse_douyin_url(share_url: str) -> Dict:
    """
    主解析函数：输入抖音分享链接，返回解析结果。

    内部调用 resolve_and_fetch，自带重试和备用策略。

    返回格式:
    {
        "success": True/False,
        "type": "video" | "image" | "mixed",
        "item_id": "xxx",
        "desc": "作品描述",
        "author": "作者昵称",
        "video_url": "无水印视频地址" (仅视频),
        "images": ["图片地址列表"] (仅图集),
        "dynamic_url": "动图地址" (图集可能有),
        "error": "错误信息" (仅失败时)
    }
    """
    result = {
        "success": False,
        "type": None,
        "item_id": None,
        "desc": "",
        "author": "",
        "video_url": None,
        "images": [],
        "dynamic_url": None,
        "error": None,
    }

    # 步骤1: 解析获取数据（带重试）
    item_data, error = resolve_and_fetch(share_url)
    if error:
        result["error"] = error
        return result

    # 提取基本信息
    result["desc"] = item_data.get("desc", "")
    author_info = item_data.get("author", {})
    result["author"] = author_info.get("nickname", "")
    result["item_id"] = item_data.get("aweme_id", "")

    # 判断作品类型
    # aweme_type: 0=普通视频, 2=图片(单图), 4=视频(可能是带图集), 68=图集, 51=广告视频
    aweme_type = item_data.get("aweme_type", 0) or 0
    images = item_data.get("images") or []
    video = item_data.get("video") or {}

    # 精确判断：有 images 列表且非空 = 图集内容
    has_images = isinstance(images, list) and len(images) > 0
    # 有 video.play_addr = 视频内容
    has_video = isinstance(video, dict) and "play_addr" in video

    # aweme_type=2 或 68 = 图集类型
    is_image_type = aweme_type in (2, 68)
    # aweme_type=0 或 4 或 51 = 视频类型
    is_video_type = aweme_type in (0, 4, 51)

    # 步骤3: 根据类型提取下载地址
    if has_images and not has_video:
        # 纯图集
        image_urls, img_type, dynamic_url = extract_images(item_data)
        result["type"] = "image"
        result["images"] = image_urls
        result["dynamic_url"] = dynamic_url
        result["success"] = True

    elif has_video:
        # 视频（可能同时有图集）
        video_url, err = extract_video_url(item_data)
        if err:
            result["error"] = err
            return result

        if has_images:
            # 视频 + 图集混合
            image_urls, img_type, dynamic_url = extract_images(item_data)
            result["type"] = "mixed"
            result["video_url"] = video_url
            result["images"] = image_urls
            result["dynamic_url"] = dynamic_url
        else:
            result["type"] = "video"
            result["video_url"] = video_url

        result["success"] = True

    elif has_images and has_video:
        # 两者都有（混合内容）
        video_url, err = extract_video_url(item_data)
        image_urls, img_type, dynamic_url = extract_images(item_data)
        result["type"] = "mixed"
        result["video_url"] = video_url if not err else None
        result["images"] = image_urls
        result["dynamic_url"] = dynamic_url
        result["success"] = True

    else:
        result["error"] = f"未知的作品类型 (aweme_type={aweme_type}, has_images={has_images}, has_video={has_video})"

    return result


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("请输入抖音分享链接: ").strip()

    print(f"\n正在解析: {url}")
    result = parse_douyin_url(url)

    if result["success"]:
        print(f"\n✅ 解析成功!")
        print(f"   类型: {result['type']}")
        print(f"   作者: {result['author']}")
        print(f"   描述: {result['desc'][:50]}...")
        if result.get("video_url"):
            print(f"   视频地址: {result['video_url'][:80]}...")
        if result.get("images"):
            print(f"   图片数量: {len(result['images'])}")
        if result.get("dynamic_url"):
            print(f"   动图地址: {result['dynamic_url'][:80]}...")
    else:
        print(f"\n❌ 解析失败: {result['error']}")
