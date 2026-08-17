#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站视频下载器 — 图形界面 (GUI)
跨平台: Windows / macOS / Linux

作者: Kimi K3
仓库: https://github.com/wangliang9/bilibili-downloader

打包说明:
  Windows: pyinstaller --onefile --windowed --name bilibili-downloader app.py
  macOS:   pyinstaller --onefile --windowed --name bilibili-downloader app.py
"""

import os
import sys
import json
import queue
import threading
import contextlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# 导入核心下载逻辑（同目录下的 bilibili_dl.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bilibili_dl as core

APP_TITLE = 'B站视频下载器'
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.bilibili_dl_config.json')

QUALITY_CHOICES = [
    ('1080P+ 高码率', 112),
    ('1080P 高清', 80),
    ('720P', 64),
    ('480P', 32),
]


class StdoutRedirector:
    """把 print 输出重定向到队列，供 GUI 日志区消费"""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('720x560')
        self.minsize(640, 520)

        self.log_queue = queue.Queue()
        self.downloading = False

        self._build_ui()
        self._load_config()
        self.after(100, self._drain_log_queue)

    # ── UI 构建 ─────────────────────────────────────────

    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        # BV 号
        frm_top = ttk.LabelFrame(self, text='视频')
        frm_top.pack(fill='x', **pad)
        ttk.Label(frm_top, text='BV号或链接（多个用空格分隔）:').pack(anchor='w', padx=8, pady=(6, 0))
        self.var_bvid = tk.StringVar()
        ttk.Entry(frm_top, textvariable=self.var_bvid).pack(fill='x', padx=8, pady=4)

        # 输出目录 + 画质
        frm_path = ttk.Frame(frm_top)
        frm_path.pack(fill='x', padx=8, pady=4)
        ttk.Label(frm_path, text='输出目录:').pack(side='left')
        self.var_outdir = tk.StringVar(value=os.getcwd())
        ttk.Entry(frm_path, textvariable=self.var_outdir).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(frm_path, text='浏览…', width=8, command=self._browse_dir).pack(side='left')

        frm_q = ttk.Frame(frm_top)
        frm_q.pack(fill='x', padx=8, pady=(0, 6))
        ttk.Label(frm_q, text='画质:').pack(side='left')
        self.var_quality = tk.StringVar(value=QUALITY_CHOICES[0][0])
        self.cmb_quality = ttk.Combobox(
            frm_q, textvariable=self.var_quality, state='readonly', width=16,
            values=[label for label, _ in QUALITY_CHOICES])
        self.cmb_quality.pack(side='left', padx=4)

        # Cookie
        frm_ck = ttk.LabelFrame(self, text='Cookie（F12 → Application → Cookies → bilibili.com）')
        frm_ck.pack(fill='x', **pad)

        self.var_sessdata = tk.StringVar()
        self.var_jct = tk.StringVar()
        self.var_uid = tk.StringVar()

        for label, var in (('SESSDATA', self.var_sessdata),
                           ('bili_jct', self.var_jct),
                           ('DedeUserID', self.var_uid)):
            row = ttk.Frame(frm_ck)
            row.pack(fill='x', padx=8, pady=2)
            ttk.Label(row, text=f'{label}:', width=11).pack(side='left')
            ttk.Entry(row, textvariable=var, show='' if label != 'SESSDATA' else '*').pack(
                side='left', fill='x', expand=True)

        row2 = ttk.Frame(frm_ck)
        row2.pack(fill='x', padx=8, pady=4)
        self.var_remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text='记住 Cookie', variable=self.var_remember).pack(side='left')
        self.btn_verify = ttk.Button(row2, text='验证 Cookie', width=12, command=self._verify_cookie)
        self.btn_verify.pack(side='right')
        self.lbl_login = ttk.Label(row2, text='')
        self.lbl_login.pack(side='right', padx=8)

        # 操作按钮
        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill='x', **pad)
        self.btn_start = ttk.Button(frm_btn, text='开始下载', command=self._start_download)
        self.btn_start.pack(side='left')
        self.btn_clear = ttk.Button(frm_btn, text='清空日志', command=lambda: self.txt_log.delete('1.0', 'end'))
        self.btn_clear.pack(side='left', padx=6)

        # 日志
        frm_log = ttk.LabelFrame(self, text='日志')
        frm_log.pack(fill='both', expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(frm_log, wrap='word', state='normal', height=14)
        self.txt_log.pack(fill='both', expand=True, padx=6, pady=6)

    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_outdir.get() or os.getcwd())
        if d:
            self.var_outdir.set(d)

    # ── 配置持久化 ───────────────────────────────────────

    def _load_config(self):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            self.var_sessdata.set(cfg.get('sessdata', ''))
            self.var_jct.set(cfg.get('bili_jct', ''))
            self.var_uid.set(cfg.get('dedeuserid', ''))
            if cfg.get('outdir'):
                self.var_outdir.set(cfg['outdir'])
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _save_config(self):
        if not self.var_remember.get():
            try:
                os.remove(CONFIG_PATH)
            except OSError:
                pass
            return
        cfg = {
            'sessdata': self.var_sessdata.get().strip(),
            'bili_jct': self.var_jct.get().strip(),
            'dedeuserid': self.var_uid.get().strip(),
            'outdir': self.var_outdir.get().strip(),
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f)
        except OSError:
            pass

    # ── Cookie ──────────────────────────────────────────

    def _cookie_str(self):
        return (f"SESSDATA={self.var_sessdata.get().strip()}; "
                f"bili_jct={self.var_jct.get().strip()}; "
                f"DedeUserID={self.var_uid.get().strip()}")

    def _verify_cookie(self):
        self.lbl_login.config(text='验证中…')
        self.btn_verify.config(state='disabled')

        def work():
            try:
                user = core._check_login(self._cookie_str())
                if user:
                    vip = '大会员' if (user['vip_type'] == 2 and user['vip_status'] == 1) else '非大会员'
                    msg = f"✓ {user['uname']}（{vip}）"
                else:
                    msg = '✗ Cookie 无效或已过期'
            except Exception as e:
                msg = f'✗ 验证失败: {e}'
            self.log_queue.put(('login_result', msg))

        threading.Thread(target=work, daemon=True).start()

    # ── 下载 ────────────────────────────────────────────

    def _start_download(self):
        if self.downloading:
            return

        raw = self.var_bvid.get().strip()
        if not raw:
            messagebox.showwarning('提示', '请输入 BV 号或视频链接')
            return
        bvids = [core._parse_bvid(x) for x in raw.split() if x.strip()]
        bvids = [b for b in bvids if b.startswith('BV')]
        if not bvids:
            messagebox.showwarning('提示', '未识别到有效 BV 号')
            return

        for name, var in (('SESSDATA', self.var_sessdata),
                          ('bili_jct', self.var_jct),
                          ('DedeUserID', self.var_uid)):
            if not var.get().strip():
                messagebox.showwarning('提示', f'请填写 {name}')
                return

        quality = dict((label, qid) for label, qid in QUALITY_CHOICES)[self.var_quality.get()]
        outdir = self.var_outdir.get().strip() or os.getcwd()
        cookie = self._cookie_str()

        self._save_config()
        self.downloading = True
        self.btn_start.config(state='disabled', text='下载中…')

        def work():
            ok_count, fail_count = 0, 0
            try:
                redirector = StdoutRedirector(self.log_queue)
                with contextlib.redirect_stdout(redirector):
                    for i, bvid in enumerate(bvids):
                        print(f'\n[{i + 1}/{len(bvids)}] {bvid}')
                        try:
                            if core.download_video(bvid, cookie, outdir, quality=quality):
                                ok_count += 1
                            else:
                                fail_count += 1
                        except Exception as e:
                            print(f'  ✗ 失败: {e}')
                            fail_count += 1
            finally:
                self.log_queue.put(('download_done', (ok_count, fail_count, outdir)))

        threading.Thread(target=work, daemon=True).start()

    # ── 日志队列消费 ─────────────────────────────────────

    def _drain_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    tag, payload = item
                    if tag == 'login_result':
                        self.lbl_login.config(text=payload)
                        self.btn_verify.config(state='normal')
                    elif tag == 'download_done':
                        ok, fail, outdir = payload
                        self.downloading = False
                        self.btn_start.config(state='normal', text='开始下载')
                        self._log(f'\n===== 完成: 成功 {ok} 个, 失败 {fail} 个 =====\n输出目录: {outdir}\n')
                        if fail == 0:
                            messagebox.showinfo('完成', f'下载完成！共 {ok} 个视频\n目录: {outdir}')
                        else:
                            messagebox.showwarning('完成', f'成功 {ok} 个，失败 {fail} 个\n请查看日志')
                else:
                    # 普通文本（进度行用 \r 刷新最后一行）
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _log(self, text):
        self.txt_log.configure(state='normal')
        if text.startswith('\r'):
            # 进度刷新：替换最后一行
            last = self.txt_log.index('end-2c linestart')
            self.txt_log.delete(last, 'end-1c')
            self.txt_log.insert('end', text.lstrip('\r'))
        else:
            self.txt_log.insert('end', text)
        self.txt_log.see('end')
        self.txt_log.configure(state='normal')


def main():
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
