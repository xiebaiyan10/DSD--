# DSD - 抖音无水印下载器

<p align="center">
  <b>Douyin Sniffer & Downloader</b><br>
  纯 HTTP 请求实现 · 最高清无水印 · 桌面GUI应用
</p>

## ✨ 功能特性

- 🎯 **智能解析**：粘贴抖音口令/链接，自动提取纯URL并解析
- 🎬 **最高清无水印**：1080p 原画质，去除所有水印标记（/play/ + ratio=1080p + 去logo_name）
- 🖼 **图集支持**：批量下载图集图片 + 自动检测动态封面/动图
- 📊 **实时进度**：下载进度条 + 深色终端风格日志面板
- 🖥 **纯桌面应用**：PySide6 GUI，无需浏览器，纯 HTTP 请求
- 🔄 **重试机制**：SSR 页面解析 + 自动重试 + douyin.com 备用策略

## 📸 界面预览

```
┌─────────────────────────────────────┐
│     🎵 DSD - 抖音无水印下载器        │
│  粘贴抖音分享链接 → 解析 → 下载      │
├─────────────────────────────────────┤
│ 🔗 输入抖音链接                     │
│ [粘贴链接...              ] [🔍解析] │
├─────────────────────────────────────┤
│ 📋 作品信息                         │
│ 作者: xxx  类型: 视频  描述: xxx     │
├─────────────────────────────────────┤
│ [📥 下载无水印] [⏹取消] [📂打开目录] │
│ ████████████░░░░░░ 75%              │
├─────────────────────────────────────┤
│ 📜 运行日志 (深色终端风格)           │
│ [16:41:08] 🔍 开始解析...           │
│ [16:41:09] ✅ 解析成功!             │
│ [16:41:10] 📥 开始下载...           │
└─────────────────────────────────────┘
```

## 🚀 快速开始

### 方式一：直接运行（需要 Python 3.10+）

```bash
# 1. 克隆仓库
git clone https://github.com/yourname/DSD.git
cd DSD

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 GUI
python dsd.py

# 命令行模式
python dsd.py --cli "https://v.douyin.com/xxxxx/"
```

### 方式二：下载打包好的 exe

从 [Releases](https://github.com/yourname/DSD/releases) 下载 `DSD_抖音无水印下载器.exe`，双击运行即可，无需安装 Python。

### 方式三：自行打包

```bash
python setup.py build        # 发布版（无控制台）
python setup.py debug        # 调试版（带控制台）
python setup.py clean        # 清理构建文件
```

## 🔧 技术原理

### 解析流程

```
粘贴口令文本
  ↓ extract_url_from_text()  自动提取纯链接
短链 https://v.douyin.com/xxx/
  ↓ 302 重定向
分享页 https://www.iesdouyin.com/share/video/{id}
  ↓ SSR 页面解析
window._ROUTER_DATA 内嵌 JSON
  ↓ 递归查找 aweme 对象
提取 play_addr.url_list[0]
  ↓ 三步优化
① /playwm/ → /play/        (去水印)
② ratio=720p → ratio=1080p (最高清)
③ 删除 logo_name 参数       (去搜索引导水印)
  ↓ 302 重定向
CDN 真实无水印地址 → 下载
```

### 核心技术点

| 模块 | 说明 |
|------|------|
| **SSR 解析** | 从 `window._ROUTER_DATA` 中提取内嵌 JSON，绕过 API 签名限制 |
| **Headers 优化** | 精简到仅 User-Agent + Referer，避免触发反爬 |
| **重试机制** | 最多3次重试，失败后切换 `douyin.com/video/{id}` 备用策略 |
| **无损下载** | 1080p 原画质，文件体积比默认 720p 提升 30%~50% |

## 📁 项目结构

```
DSD/
├── dsd.py              # 主程序 GUI（PySide6）
├── douyin_parser.py    # 抖音解析核心（SSR + 无损提取）
├── downloader.py       # 下载模块（视频/图集/动图）
├── setup.py            # PyInstaller 打包脚本
├── requirements.txt    # Python 依赖
├── .gitignore
└── README.md
```

## ⚠️ 免责声明

本工具仅供学习交流使用，请尊重创作者版权，勿用于商业用途或侵犯他人权益。

## 📄 License

MIT License
