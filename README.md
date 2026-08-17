# bilibili-downloader

B站（哔哩哔哩）视频下载器，支持普通视频和 UPOWER 充电专属视频下载，支持大会员 1080P 高码率。

> 由 **Kimi K3** 编写

## 功能特性

- 支持普通视频和 **UPOWER 充电专属视频** 下载
- 支持大会员 **1080P 高码率** 画质（需 Cookie）
- 自动 DASH 视频/音频流合并（基于 ffmpeg）
- 批量下载、断点续传、实时进度显示
- Cookie 验证与本地记忆
- **图形界面（tkinter）** + 命令行双模式
- 跨平台：Windows / macOS / Linux

## 可执行文件（免安装 Python）

在 [Actions](../../actions) 页面运行 **Build Executables** 工作流，产物在 Artifacts 区下载：

| 产物 | 系统 | 架构 |
|------|------|------|
| `bilibili-downloader-Windows` | Windows 7 / 10 / 11 | x64 单文件 exe |
| `bilibili-downloader-macOS-Intel` | macOS 13+（含 15 / 26） | Intel x86_64 |
| `bilibili-downloader-macOS-AppleSilicon` | macOS 14+（含 15 / 26） | Apple Silicon arm64 |

所有产物均为单文件，内置 Python 运行时与全部依赖（含 ffmpeg），无需安装任何环境。

> Windows 版本使用 Python 3.8 + PyInstaller 5.13 构建，兼容 Win7。

## 从源码运行

### 安装依赖

```bash
pip install imageio-ffmpeg
```

### 图形界面

```bash
python app.py
```

### 命令行模式

```bash
# 交互模式
python bilibili_dl.py

# 直接下载
python bilibili_dl.py BV1xx4y1z7Ab

# 批量下载
python bilibili_dl.py BV1xx4y1z7Ab BV1yy4y1z7Cd
```

## Cookie 获取方法

在已登录 B站 的浏览器中：

1. 按 `F12` 打开开发者工具
2. 点击 **Application（应用）** → **Cookies** → `bilibili.com`
3. 复制三项：`SESSDATA`、`bili_jct`、`DedeUserID`

程序会自动验证 Cookie 有效性，并可选择记住以便下次使用。

## 本地打包

```bash
pip install pyinstaller imageio-ffmpeg

# Windows（Win7 兼容需 Python ≤3.8 + PyInstaller 5.13.x）
pyinstaller --onefile --windowed --name bilibili-downloader app.py

# macOS（生成 .app）
pyinstaller --onefile --windowed --name bilibili-downloader app.py
```

## 技术说明

- 使用 B站 `player/playurl` API（而非 wbi 端点），这是下载充电视频的关键
- 所有请求携带 `Referer` 和 `Origin` 头以通过风控
- 1080P 及以上画质使用 DASH 分离流下载，通过 ffmpeg 合并音视频

## 许可证

MIT
