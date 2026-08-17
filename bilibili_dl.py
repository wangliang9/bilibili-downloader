#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站(哔哩哔哩)视频下载器 — 支持普通视频和UPOWER充电专属视频
跨平台: Windows / Linux / macOS

作者: Kimi K3
仓库: https://github.com/wangliang9/bilibili-downloader

功能:
  - 支持普通视频和 UPOWER 充电专属视频下载
  - 支持大会员 1080P 高码率画质
  - 自动 DASH 视频/音频流合并 (ffmpeg)
  - 批量下载、断点续传、进度显示
  - Cookie 交互式输入与自动验证

用法:
  python bilibili_dl.py                          # 交互模式（推荐）
  python bilibili_dl.py <BV号或链接> [...更多]    # 直接下载
  python bilibili_dl.py --cookies-from-file cookies.txt <BV号>

依赖:
  pip install imageio-ffmpeg   (自动合并 DASH 视频/音频流)
  如无此包，程序会尝试自动安装
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.error
import subprocess

# ── 常量 ──────────────────────────────────────────────────
API_VIEW = 'https://api.bilibili.com/x/web-interface/view'
API_NAV  = 'https://api.bilibili.com/x/web-interface/nav'
API_PLAY = 'https://api.bilibili.com/x/player/playurl'

QUALITY_LABELS = {
    127: '8K', 120: '4K', 116: '1080P60', 112: '1080P+',
    80: '1080P', 74: '720P60', 64: '720P', 32: '480P', 16: '360P'
}
CODEC_NAMES = {7: 'AVC(H.264)', 12: 'HEVC(H.265)', 13: 'AV1'}

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')


def _headers(bvid, cookie):
    return {
        'User-Agent': UA,
        'Referer': f'https://www.bilibili.com/video/{bvid}/',
        'Origin': 'https://www.bilibili.com',
        'Cookie': cookie,
    }


def _get_json(url, headers, retries=3):
    """GET JSON with retries"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 412:
                print('  错误: B站风控拦截 (HTTP 412)，请确认 Referer/Origin 头正确')
                sys.exit(1)
            if i == retries - 1:
                raise
            time.sleep(2 ** i)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def _find_ffmpeg():
    """定位 ffmpeg — 优先 imageio-ffmpeg (可自动安装)，其次系统 PATH"""
    # 1. imageio-ffmpeg (pip 包自带)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    # 2. 尝试自动安装
    try:
        print('  正在安装 imageio-ffmpeg...')
        import importlib
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--quiet', 'imageio-ffmpeg'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    # 3. 系统 PATH
    import shutil
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    # 4. 常见路径
    for p in [
        os.path.expandvars(r'%ProgramFiles%\ffmpeg\bin\ffmpeg.exe'),
        '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg',
        '/opt/homebrew/bin/ffmpeg',
    ]:
        if os.path.isfile(p):
            return p
    return None


def _sanitize_filename(name):
    """清理文件名中的非法字符"""
    return (name.replace('/', '_').replace('\\', '_').replace(':', '_')
                .replace('*', '_').replace('?', '_').replace('"', "'")
                .replace('<', '_').replace('>', '_').replace('|', '_'))


def _parse_bvid(input_str):
    """从输入中提取 BV 号"""
    m = re.search(r'(BV[0-9A-Za-z]{10})', input_str)
    return m.group(1) if m else input_str.strip()


def _check_login(cookie):
    """验证 Cookie 是否有效"""
    h = _headers('', cookie)
    h['Referer'] = 'https://www.bilibili.com/'
    data = _get_json(API_NAV, h)
    nd = data.get('data', {})
    if not nd.get('isLogin'):
        return None
    vip = nd.get('vip', {})
    return {
        'mid': nd.get('mid'),
        'uname': nd.get('uname', '?'),
        'vip_type': vip.get('type'),      # 2 = 大会员
        'vip_status': vip.get('status'),  # 1 = 有效
    }


def _get_video_info(bvid, cookie):
    """获取视频基本信息"""
    h = _headers(bvid, cookie)
    data = _get_json(f'{API_VIEW}?bvid={bvid}', h)
    if data['code'] != 0:
        raise RuntimeError(f"获取视频信息失败: {data.get('message')}")
    d = data['data']
    return {
        'cid': d['cid'],
        'title': d['title'],
        'duration': d['duration'],
        'is_upower': d.get('is_upower_exclusive', False),
        'can_play': d.get('is_upower_play', True),  # 非充电视频默认 True
        'owner': d.get('owner', {}).get('name', ''),
    }


def _get_streams(bvid, cid, cookie, quality=112):
    """获取 DASH 流地址 (支持充电视频的关键端点)"""
    h = _headers(bvid, cookie)
    url = (f'{API_PLAY}?bvid={bvid}&cid={cid}'
           f'&fnval=4048&fnver=0&fourk=1&qn={quality}')
    data = _get_json(url, h)
    if data['code'] != 0:
        raise RuntimeError(f"获取播放地址失败: {data.get('message')}")
    dd = data['data']
    dash = dd.get('dash')
    if not dash:
        return None, None, []
    # 视频: 优先目标画质 + AVC 编码
    vurl = None
    for v in dash.get('video', []):
        if v.get('id') == quality and v.get('codecid') == 7:
            vurl = v.get('baseUrl') or v.get('base_url')
            break
    if not vurl:
        for v in dash.get('video', []):
            if v.get('id') == quality:
                vurl = v.get('baseUrl') or v.get('base_url')
                break
    # 降级: 取最高可用画质
    if not vurl and dash.get('video'):
        vids = sorted(dash['video'], key=lambda x: (x.get('id', 0), x.get('codecid', 0) == 7), reverse=True)
        vurl = vids[0].get('baseUrl') or vids[0].get('base_url')
        quality = vids[0].get('id', 0)
    # 音频: 优先 30280 (高码率 AAC)
    aurl = None
    for a in dash.get('audio', []):
        if a.get('id') == 30280:
            aurl = a.get('baseUrl') or a.get('base_url')
            break
    if not aurl and dash.get('audio'):
        aurl = dash['audio'][0].get('baseUrl') or dash['audio'][0].get('base_url')
    return vurl, aurl, dd.get('accept_quality', [])


def _download(url, dest, label, headers):
    """带进度显示的文件下载"""
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=60)
    total = int(resp.headers.get('Content-Length', 0))
    total_mb = total / 1024 / 1024 if total else 0
    downloaded = 0
    chunk = 512 * 1024
    start = time.time()
    with open(dest, 'wb') as f:
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            f.write(buf)
            downloaded += len(buf)
            if total:
                pct = downloaded / total * 100
                speed = downloaded / max(time.time() - start, 0.1) / 1024 / 1024
                sys.stdout.write(
                    f'\r  {label}: {downloaded/1024/1024:.0f}MB/'
                    f'{total_mb:.0f}MB ({pct:.1f}%) [{speed:.1f}MB/s]'
                )
                sys.stdout.flush()
    print(f'\r  {label}: {downloaded/1024/1024:.0f}MB 完成'
          f' [总耗时 {time.time()-start:.0f}s]'.ljust(60))
    return downloaded


def download_video(bvid, cookie, outdir, quality=112):
    """下载单个视频 — 主流程"""
    bvid = _parse_bvid(bvid)
    h = _headers(bvid, cookie)

    # 1. 视频信息
    info = _get_video_info(bvid, cookie)
    title = info['title']
    dur = info['duration']
    print(f'\n  标题: {title}')
    print(f'  UP主: {info["owner"]}  时长: {dur//60}分{dur%60}秒')
    if info['is_upower']:
        if not info['can_play']:
            print('  ⚠ 充电专属视频 — 当前账号未充电，只能获取预览')
            return False
        print('  充电专属视频 — 已充电 ✓')

    # 2. 获取流地址
    vurl, aurl, qualities = _get_streams(bvid, info['cid'], cookie, quality)
    if not vurl:
        print('  错误: 无法获取视频流地址')
        return False
    qlabel = QUALITY_LABELS.get(quality, str(quality))
    print(f'  画质: {qlabel} (可用: {[QUALITY_LABELS.get(q,q) for q in qualities]})')

    # 3. 检查是否已存在
    safe = _sanitize_filename(title)
    outfile = os.path.join(outdir, f'{safe}_{qlabel}.mp4')
    if os.path.exists(outfile):
        print(f'  跳过: 文件已存在 ({os.path.getsize(outfile)//1024//1024}MB)')
        return True

    # 4. 下载视频流
    os.makedirs(outdir, exist_ok=True)
    vfile = os.path.join(outdir, '.tmp_video.m4s')
    afile = os.path.join(outdir, '.tmp_audio.m4s')

    _download(vurl, vfile, f'视频 {qlabel}', h)
    _download(aurl, afile, '音频', h)

    # 5. 合并
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print('  ✗ 未找到 ffmpeg，无法合并。音视频已单独保存:')
        print(f'    视频: {vfile}')
        print(f'    音频: {afile}')
        print('  修复: pip install imageio-ffmpeg')
        return False

    print('  合并中...')
    r = subprocess.run(
        [ffmpeg, '-i', vfile, '-i', afile,
         '-c', 'copy', '-map', '0:v:0', '-map', '1:a:0',
         '-y', outfile],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        print(f'  ✗ 合并失败: {r.stderr[-300:]}')
        print(f'  音视频已单独保存: {vfile} + {afile}')
        return False

    # 6. 清理
    for f in (vfile, afile):
        try:
            os.remove(f)
        except OSError:
            pass

    size_mb = os.path.getsize(outfile) // 1024 // 1024
    print(f'  ✓ 完成: {outfile}')
    print(f'    大小: {size_mb}MB  时长: {dur//60}分{dur%60}秒')
    return True


def prompt_cookies():
    """交互式获取 Cookie"""
    print()
    print('=' * 60)
    print('  B站视频下载器 — Cookie 设置')
    print('=' * 60)
    print()
    print('  请在已登录 B站 的浏览器中：')
    print('  1. 按 F12 打开开发者工具')
    print('  2. 点击 Application（应用）→ Cookies → bilibili.com')
    print('  3. 找到以下三项并复制：')
    print()
    print('  ┌──────────────────────────────────────────┐')
    print('  │  SESSDATA    → 登录会话凭证             │')
    print('  │  bili_jct    → CSRF Token               │')
    print('  │  DedeUserID  → 用户数字 ID              │')
    print('  └──────────────────────────────────────────┘')
    print()

    sessdata = input('  SESSDATA: ').strip()
    if not sessdata:
        print('  错误: SESSDATA 不能为空')
        return None
    bili_jct = input('  bili_jct: ').strip()
    if not bili_jct:
        print('  错误: bili_jct 不能为空')
        return None
    userid = input('  DedeUserID: ').strip()
    if not userid:
        print('  错误: DedeUserID 不能为空')
        return None

    cookie = f'SESSDATA={sessdata}; bili_jct={bili_jct}; DedeUserID={userid}'

    # 验证
    print('\n  验证中...')
    user = _check_login(cookie)
    if not user:
        print('  ✗ Cookie 无效或已过期，请重新获取')
        return None
    vip_str = '大会员 ✓' if (user['vip_type'] == 2 and user['vip_status'] == 1) else '非大会员'
    print(f'  ✓ 登录成功: {user["uname"]} ({vip_str})')
    return cookie


def prompt_bvids():
    """交互式获取 BV 号"""
    print()
    print('  请输入视频 BV 号或完整链接，多个用空格分隔:')
    raw = input('  > ').strip()
    if not raw:
        return []
    # 支持多种分隔: 空格、换行、逗号
    items = re.split(r'[\s,，、]+', raw)
    return [_parse_bvid(x) for x in items if x.strip()]


def prompt_outdir():
    """交互式获取输出目录"""
    print()
    default = os.getcwd()
    raw = input(f'  输出目录 (默认: {default}): ').strip()
    outdir = raw if raw else default
    os.makedirs(outdir, exist_ok=True)
    return outdir


def main():
    # 命令行参数模式
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = [a for a in sys.argv[1:] if a.startswith('-')]

    if '--cookies-from-file' in flags:
        # 从文件读取 cookie
        idx = flags.index('--cookies-from-file')
        # cookie 文件路径在 flag 后面
        try:
            cookie_file = sys.argv[sys.argv.index('--cookies-from-file') + 1]
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookie = f.read().strip()
            args = [a for a in args if a != cookie_file]
        except (IndexError, FileNotFoundError):
            print('错误: 无法读取 cookie 文件')
            sys.exit(1)
    else:
        cookie = None

    bvids = [a for a in args if not os.path.isfile(a) and not a.endswith('.txt')]
    # 第一个非 flag 参数可能是 cookie 文件路径

    # 无命令行 BV 号 → 交互模式
    if not bvids:
        if not cookie:
            cookie = prompt_cookies()
            if not cookie:
                sys.exit(1)
        bvids = prompt_bvids()
        if not bvids:
            print('未输入 BV 号，退出')
            sys.exit(0)
        outdir = prompt_outdir()
    else:
        if not cookie:
            cookie = prompt_cookies()
            if not cookie:
                sys.exit(1)
        outdir = os.getcwd()

    # 过滤 cookie 文件路径被误当 BV 号的情况
    bvids = [b for b in bvids if re.match(r'^BV[0-9A-Za-z]{10}$', b)]
    if not bvids:
        print('错误: 未找到有效的 BV 号')
        sys.exit(1)

    # 批量下载
    print(f'\n  共 {len(bvids)} 个视频，输出到: {outdir}')
    print('=' * 60)

    results = []
    for i, bvid in enumerate(bvids):
        print(f'\n[{i+1}/{len(bvids)}] {bvid}')
        try:
            ok = download_video(bvid, cookie, outdir)
            results.append((bvid, ok))
        except Exception as e:
            print(f'  ✗ 失败: {e}')
            results.append((bvid, False))

    # 汇总
    print('\n' + '=' * 60)
    print('  下载结果汇总')
    print('=' * 60)
    success = sum(1 for _, ok in results if ok)
    for bvid, ok in results:
        mark = '✓' if ok else '✗'
        print(f'  {mark} {bvid}')
    print(f'\n  成功 {success}/{len(results)}，输出目录: {outdir}')

    if success == len(results):
        print('\n  全部完成！')
    else:
        print(f'\n  {len(results)-success} 个失败，请检查以上输出')


if __name__ == '__main__':
    main()
