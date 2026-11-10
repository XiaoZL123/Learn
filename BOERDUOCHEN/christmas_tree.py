#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手搓粒子 · 圣诞树 · 单文件版  (Particle Christmas Tree, single file)
=========================================================================
Python + pygame 复刻抖音同款「手搓粒子代码」圣诞动画，并且**可以用手隔着摄像头控制**：

    ✦ 金色粒子聚合成一棵会慢慢自转的 3D 圣诞树（顶部钻石星）
    ✦ 粒子炸开 → 中心升起发光金框，里面浮现一张照片
    ✦ 再炸成「礼物星球」，随后重新聚合成树，循环往复

    ✦ 手势：捏合=抓走粒子   五指张开=推开/炸开   手掌倾斜=整棵树跟着转
            1 指=圣诞树  2 指=相框  3~5 指=星球（手势停 0.8 秒生效）

运行：pip install pygame numpy opencv-python mediapipe
PyCharm：右键 Run 'christmas_tree'。
没摄像头也能跑（自动演出 + 鼠标也能撩粒子）。

键盘：空格 下一个形态 │ T/F/C 树/相框/星球 │ A 自动 │ R 重排 │ P 截图
      V 摄像头预览开关 │ G 手势控制开关 │ H 提示 │ F11 全屏 │ ESC 退出

命令行：
    python christmas_tree.py                      # 摄像头手势 + 自动演出
    python christmas_tree.py --no-hand            # 关掉手势，纯动画
    python christmas_tree.py --photo me.jpg       # 相框里放自己的照片
    python christmas_tree.py -n 2600              # 更多粒子
    python christmas_tree.py --hand-video hand.mp4  # 用视频当"摄像头"调试手势
    python christmas_tree.py --record-dir out --seconds 12 --fps 30   # 离线渲染
"""
from __future__ import annotations



import argparse
import math
import os
import random
import sys
import time

import pygame

# =========================================================================
#  一、全局参数
# =========================================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))   # 程序所在目录（日志/截图写这里）
VW, VH = 1280, 800                   # 渲染分辨率（窗口可拉伸，画面自适应）
FPS = 60
GS = 2                               # 发光层降采样倍数（2 = 半分辨率，快 4 倍）

CENTER = (VW * 0.5, VH * 0.5 + 34)   # 世界中心
FOCAL = 1150.0                       # 透视焦距：越小透视越夸张

TREE_TOP, TREE_BOT = -210.0, 240.0   # 树顶 / 树底（相对 CENTER 的 y）
TREE_R = 162.0                       # 树底半径
FRAME_HW, FRAME_HH = 176.0, 206.0    # 相框半宽 / 半高
FRAME_ROUND = 24.0                   # 相框圆角
CLOUD_R = 330.0                      # 星球半径

# ---- 配色（视频里那颗树：暖金 + 琥珀 + 少量浆果红，白很少）-------------
PALETTE = [
    ((255, 188, 74), 30),    # 主金
    ((255, 148, 40), 22),    # 琥珀
    ((255, 226, 164), 14),   # 奶油
    ((255, 252, 240), 5),    # 暖白
    ((226, 62, 44), 10),     # 浆果红
    ((150, 26, 36), 6),      # 深红
    ((190, 214, 255), 3),    # 冷白（雪点）
    ((255, 206, 104), 10),   # 亮金
]
GOLD = (255, 196, 84)
WARM_WHITE = (255, 244, 220)
RIBBON_BLUE = (96, 146, 255)

# ---- 自动演出表：形态 / 停留秒数 / 变形秒数 / 是否爆开 -------------------
SEQUENCE = [
    dict(shape="tree",  hold=4.4, morph=1.8, burst=False),
    dict(shape="frame", hold=2.9, morph=1.9, burst=True, burst_power=0.62),
    dict(shape="cloud", hold=2.6, morph=0.9, burst=True),
    dict(shape="tree",  hold=4.4, morph=2.0, burst=False),
]

ROT_SPEED = 0.42                                            # 自转角速度
ROT_WEIGHT = {"tree": 1.0, "frame": 0.0, "cloud": 1.0}       # 各形态自转权重
BRIGHT_FACTOR = (0.42, 0.66, 0.88, 1.08)                     # 光晕亮度分档
GAIN_BY_SHAPE = {"tree": 1.0, "frame": 0.76, "cloud": 1.02}   # 各形态整体亮度

# ---- 手势 → 形态 --------------------------------------------------------
# 只有这三个"造型"会切形态，且要求是明确的手势（伸哪几根手指）
GESTURE_SHAPE = {"ONE": "tree", "TWO": "frame", "PALM": "cloud"}
GESTURE_HOLD = 0.40                                          # 手势保持多久才切形态
GESTURE_CD = 0.90                                            # 切完形态后的冷却，防止连切
HAND_GAIN = 1.35                                             # 手心位置的随动放大倍数

# ---- 手怎么带动粒子（不再用"力场"，直接搬目标点，距离可预期）------------
HAND_R_MIN, HAND_R_K = 420.0, 240.0    # 手的"势力范围"半径 = R_MIN + R_K * 推开力
PUSH_REACH = 560.0                     # 推开时，粒子目标被推到离手多远（想更远就改这个）
GRAB_STIFF = 260.0                     # 捏合时额外弹簧刚度（越大粘得越死、越跟手）
PUSH_STIFF = 130.0                     # 推开时额外刚度（越大越"弹"出去）
RECOVER_YIELD = 0.55                   # 推开后弹簧软化的比例（让粒子慢慢飘回）
HAND_PUSH_KICK = 2200.0                # 张开瞬间的冲刺速度（"砰"一下）


# =========================================================================
#  二、小工具
# =========================================================================
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    """smoothstep：两端缓入缓出"""
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


class OneEuro:
    """One Euro Filter：慢速压抖、快速几乎不迟滞

    普通低通滤波的通病是"要么抖、要么慢"。这个滤波器让截止频率跟着速度走：
    手不动 → 强滤波（不抖）；手快速移动 → 弱滤波（跟得上，几乎没延迟）。
    """

    __slots__ = ("mincutoff", "beta", "dcutoff", "x_prev", "dx_prev")

    def __init__(self, mincutoff=2.4, beta=0.020, dcutoff=1.2):
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self.x_prev = None
        self.dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(1e-5, dt))

    def __call__(self, x, dt):
        if self.x_prev is None:
            self.x_prev = x
            return x
        dt = max(1e-4, dt)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.dcutoff, dt)
        dx_hat = self.dx_prev + a_d * (dx - self.dx_prev)
        cutoff = self.mincutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = self.x_prev + a * (x - self.x_prev)
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        return x_hat

    def reset(self):
        self.x_prev = None
        self.dx_prev = 0.0


def pick_color_idx():
    total = sum(w for _, w in PALETTE)
    r = random.uniform(0, total)
    for i, (_, w) in enumerate(PALETTE):
        r -= w
        if r <= 0:
            return i
    return 0


# =========================================================================
#  三、贴图工厂
# =========================================================================
def make_halo(color, radius, power=2.5, core=0.20, gain=1.0):
    """单颗粒子的光晕：黑底径向渐变 + 一点高亮核心（配合 BLEND_RGB_ADD 用）"""
    radius = max(1, int(round(radius)))
    ss = 2
    d = radius * 2 * ss
    surf = pygame.Surface((d, d))
    surf.fill((0, 0, 0))
    c = radius * ss
    rmax = float(radius * ss)
    r, g, b = color
    for i in range(int(rmax), 0, -1):
        u = i / rmax
        a = (1.0 - u) ** power * gain
        cb = max(0.0, (core - u) / core) if core > 0 else 0.0
        col = (int(min(255, r * a + 255 * cb * 0.9)),
               int(min(255, g * a + 250 * cb * 0.9)),
               int(min(255, b * a + 235 * cb * 0.9)))
        pygame.draw.circle(surf, col, (c, c), i)
    return pygame.transform.smoothscale(surf, (radius * 2, radius * 2))


def make_aura(color, radius, power=2.0, dim=1.0):
    """大范围柔光（树的暖雾 / 天空反光）"""
    radius = max(4, int(radius))
    surf = pygame.Surface((radius * 2, radius * 2))
    surf.fill((0, 0, 0))
    r, g, b = color
    for i in range(radius, 0, -1):
        a = (1.0 - i / radius) ** power * dim
        pygame.draw.circle(surf, (int(r * a), int(g * a), int(b * a)), (radius, radius), i)
    return surf


def make_flare(radius, color, spikes=4, sharp=2.4):
    """星芒：中心光球 + 四道尖刺（顶部的钻石星）"""
    radius = max(4, int(radius))
    ss = 2
    d = radius * 2 * ss
    surf = pygame.Surface((d, d))
    surf.fill((0, 0, 0))
    c = (d / 2.0, d / 2.0)
    R = radius * ss
    r, g, b = color
    for i in range(int(R), 0, -1):
        a = (1.0 - i / R) ** sharp
        pygame.draw.circle(surf, (int(r * a), int(g * a), int(b * a)), c, i)
    for k in range(spikes):
        ang = k * math.tau / spikes
        w0 = max(1.0, R * 0.085)
        tip = (c[0] + math.cos(ang) * R, c[1] + math.sin(ang) * R)
        p1 = (c[0] + math.cos(ang + math.pi / 2) * w0, c[1] + math.sin(ang + math.pi / 2) * w0)
        p2 = (c[0] + math.cos(ang - math.pi / 2) * w0, c[1] + math.sin(ang - math.pi / 2) * w0)
        pygame.draw.polygon(surf, (r // 2, g // 2, b // 2), (tip, p1, p2))
    return pygame.transform.smoothscale(surf, (radius * 2, radius * 2))


def render_tracked(font, text, tracking, color):
    """带散字距的文字（视频里 MERRY CHRISTMAS 字距拉得很开）"""
    glyphs = [font.render(ch, True, color) for ch in text]
    w = sum(g.get_width() for g in glyphs) + tracking * max(0, len(glyphs) - 1)
    h = max(g.get_height() for g in glyphs) + 8
    surf = pygame.Surface((w + 8, h), pygame.SRCALPHA)
    x = 4
    for g in glyphs:
        surf.blit(g, (x, (h - g.get_height()) // 2))
        x += g.get_width() + tracking
    return surf


def fit_font(size, names, bold=False):
    """按顺序找系统字体，找不到退回 pygame 默认字体"""
    fdir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in names:
        p = os.path.join(fdir, name)
        if os.path.isfile(p):
            try:
                f = pygame.font.Font(p, size)
                f.set_bold(bold)
                return f
            except Exception:
                pass
    try:
        return pygame.font.SysFont(",".join(n.split(".")[0] for n in names), size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


def soft_glow(surface, passes=3, factor=2.6):
    """多次"缩小-放大"得到柔和辉光（比一次性大倍数缩放更平滑，不会出现横条）"""
    w, h = surface.get_size()
    out = surface
    for _ in range(passes):
        out = pygame.transform.smoothscale(out, (max(1, int(w / factor)), max(1, int(h / factor))))
        out = pygame.transform.smoothscale(out, (w, h))
    return out


# =========================================================================
#  四、三种形态的粒子坐标（世界坐标，相对 CENTER）
# =========================================================================
def gen_tree(n):
    """圆锥形圣诞树：底部更密，大部分粒子贴锥面"""
    pts, sizes = [], []
    for _ in range(n):
        u = random.random() ** 0.92
        y = TREE_TOP + (TREE_BOT - TREE_TOP) * u
        rmax = TREE_R * (u ** 1.22)
        if random.random() < 0.86:
            r = rmax * (0.70 + 0.34 * random.random() ** 0.5)
        else:
            r = rmax * random.random() * 0.70
        a = random.random() * math.tau
        x, z = r * math.cos(a), r * math.sin(a)
        if u > 0.90 and random.random() < 0.28:            # 底部垂落的火星
            y += random.uniform(4, 66)
            k = random.uniform(0.55, 1.0)
            x, z = x * k, z * k
        pts.append((x, y, z))
        q = random.random()
        if q < 0.60:
            s = random.uniform(1.1, 2.1)
        elif q < 0.89:
            s = random.uniform(2.1, 3.5)
        else:
            s = random.uniform(3.5, 6.0)                   # 少量大 bokeh
        sizes.append(s)
    return pts, sizes


def rounded_rect_path(hw, hh, r, step=4.0):
    """沿圆角矩形周长采样"""
    pts = []
    for (x0, y0), (x1, y1) in [((-hw + r, -hh), (hw - r, -hh)),
                               ((hw, -hh + r), (hw, hh - r)),
                               ((hw - r, hh), (-hw + r, hh)),
                               ((-hw, hh - r), (-hw, -hh + r))]:
        L = math.hypot(x1 - x0, y1 - y0)
        k = max(2, int(L / step))
        for i in range(k):
            t = i / k
            pts.append((lerp(x0, x1, t), lerp(y0, y1, t)))
    for cx, cy, a0 in [(hw - r, -hh + r, -math.pi / 2), (hw - r, hh - r, 0.0),
                       (-hw + r, hh - r, math.pi / 2), (-hw + r, -hh + r, math.pi)]:
        k = max(4, int(r * math.pi / 2 / step))
        for i in range(k):
            a = a0 + (i / k) * (math.pi / 2)
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def gen_frame(n):
    """相框：粒子聚在圆角矩形边框上"""
    path = rounded_rect_path(FRAME_HW, FRAME_HH, FRAME_ROUND, 3.5)
    m = len(path)
    pts, sizes = [], []
    for _ in range(n):
        bx, by = path[random.randrange(m)]
        d = math.hypot(bx, by) or 1.0
        off = -6.0 + 17.0 * (random.random() ** 1.6)       # 边框厚度
        pts.append((bx + bx / d * off * 0.85 + random.uniform(-3, 3),
                    by + by / d * off * 0.85 + random.uniform(-3, 3),
                    random.uniform(-9, 9)))
        q = random.random()
        sizes.append(random.uniform(0.9, 1.7) if q < 0.78 else random.uniform(1.8, 3.0))
    return pts, sizes


def gen_cloud(n):
    """礼物星球：偏扁的球壳"""
    pts, sizes = [], []
    for _ in range(n):
        r = CLOUD_R * (random.uniform(0.70, 1.0) if random.random() < 0.82
                       else random.uniform(0.12, 0.72))
        u = random.uniform(-1.0, 1.0)
        th = random.random() * math.tau
        s = math.sqrt(max(0.0, 1.0 - u * u))
        pts.append((r * s * math.cos(th), r * u * 0.88 + 16, r * s * math.sin(th)))
        q = random.random()
        if q < 0.58:
            s2 = random.uniform(1.0, 2.0)
        elif q < 0.90:
            s2 = random.uniform(2.0, 3.4)
        else:
            s2 = random.uniform(3.4, 5.8)
        sizes.append(s2)
    return pts, sizes


# =========================================================================
#  五、粒子 / 礼物盒 / 雪花
# =========================================================================
class Particle:
    __slots__ = ("x", "y", "z", "vx", "vy", "vz", "ph", "tw")

    def __init__(self, p):
        self.x, self.y, self.z = p
        self.vx = self.vy = self.vz = 0.0
        self.ph = random.uniform(0, math.tau)
        self.tw = random.uniform(1.2, 3.0)


class Gift:
    """树上的小礼盒（画成三面体 + 丝带）"""

    def __init__(self):
        self.s = random.uniform(10.0, 15.0)
        self.rot = random.uniform(0, math.tau)
        self.spin = random.uniform(-1.6, 1.6)
        self.body = random.choice([(236, 178, 74), (222, 74, 58), (246, 226, 186), (212, 122, 62)])
        self.ribbon = random.choice([RIBBON_BLUE, (255, 240, 200), (255, 182, 72)])
        self.bob = random.uniform(0, math.tau)
        self.tree_pt = (0.0, 0.0, 0.0)
        self.cloud_pt = (0.0, 0.0, 0.0)


class Snow:
    __slots__ = ("x", "y", "r", "vx", "vy", "ph", "spd")

    def __init__(self, w, h):
        self.x = random.uniform(0, w)
        self.y = random.uniform(0, h)
        self.r = random.choice((1, 1, 1, 2, 2, 3))
        self.vy = random.uniform(9, 34) * (0.6 + self.r * 0.25)
        self.vx = random.uniform(-8, 8)
        self.ph = random.uniform(0, math.tau)
        self.spd = random.uniform(1.4, 3.6)

# ---- 以下为手势模块内联所需的导入（合并自 hand_control.py）----
import shutil
import subprocess
import threading
import urllib.request
from collections import deque
from dataclasses import dataclass

import numpy as np

try:
    import cv2
    CV2_OK = True
except Exception:                                    # pragma: no cover
    CV2_OK = False

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    MP_OK = True
except Exception:                                    # pragma: no cover
    MP_OK = False

PYGAME_OK = True          # pygame 在本文件里是硬依赖

HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                  "hand_landmarker/float16/1/hand_landmarker.task")
HAND_MODEL_MIN_SIZE = 1_000_000


def _model_candidates():
    """手势模型可能出现的位置"""
    cache = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                         "christmas_particles")
    return [os.path.join(APP_DIR, "assets", "hand_landmarker.task"),
            os.path.join(APP_DIR, "hand_landmarker.task"),
            os.path.join(cache, "hand_landmarker.task")]


def ensure_hand_model(quiet=False):
    """找手势模型；找不到就自动下载（约 8MB）。返回路径或 None。"""
    for p in _model_candidates():
        try:
            if os.path.isfile(p) and os.path.getsize(p) >= HAND_MODEL_MIN_SIZE:
                return p
        except OSError:
            pass
    if not quiet:
        print("[手势] 找不到手势模型，正在自动下载（约 8MB，只需一次）…", flush=True)
    for dest in _model_candidates():
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            req = urllib.request.Request(HAND_MODEL_URL, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    if not quiet and total:
                        print(f"\r[手势] 下载中 {got * 100 // total:3d}%", end="", flush=True)
            if not quiet:
                print()
            if os.path.getsize(dest) >= HAND_MODEL_MIN_SIZE:
                if not quiet:
                    print(f"[手势] 模型已保存：{dest}", flush=True)
                return dest
        except Exception as exc:
            if not quiet:
                print(f"[手势] 下载失败（{dest}）：{exc}", flush=True)
            continue
    if not quiet:
        print("[手势] 没有手势模型，手势控制关闭（动画和鼠标照常）", flush=True)
    return None


# =========================================================================
#  六、手势模块（内联自 hand_control.py）
# =========================================================================
# ---- ffmpeg 取流兜底 ----------------------------------------------------
# 有些机器上 OpenCV 的 videoio 打不开相机（DirectShow 明明能枚举、ffmpeg 也能抓帧），
# 这时直接用 ffmpeg 走 dshow 抓原始帧，从管道读进来，完全绕开 OpenCV 的采集模块。
def find_ffmpeg():
    """找 ffmpeg 可执行文件：imageio-ffmpeg 自带 > PATH > 常见目录"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe",
              os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")):
        if os.path.isfile(p):
            return p
    return None


class FfmpegCamera:
    """用 ffmpeg 抓相机画面，接口模仿 cv2.VideoCapture（isOpened/read/release）"""

    def __init__(self, device=None, size=(640, 480), fps=30, ffmpeg_exe=None):
        self.w, self.h = size
        self.fps = fps
        self.ffmpeg = ffmpeg_exe or find_ffmpeg()
        self.device = device or self._find_device()
        self.proc = None
        self._pipe = None

    def _run(self, args, timeout=8):
        flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW
        return subprocess.run([self.ffmpeg] + args, capture_output=True,
                              timeout=timeout, creationflags=flags)

    def _find_device(self):
        """从 ffmpeg 的设备列表里找出视频设备名

        注意：ffmpeg 有时把相机标成 (video)，有时标成 (none)（设备忙/刚唤醒时），
        所以这里不能只认 (video) —— 只要不是 (audio) 就当作候选。
        """
        if not self.ffmpeg:
            return None
        try:
            r = self._run(["-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
        except Exception:
            return None
        text = ((r.stderr or b"") + (r.stdout or b"")).decode("utf-8", "replace")
        cands = []
        for line in text.splitlines():
            if '"' not in line or "(audio)" in line:
                continue
            parts = line.split('"')
            if len(parts) < 2 or not parts[1].strip():
                continue
            name = parts[1].strip()
            tag = line.split('"')[-1].strip()
            cands.append((name, tag))
        for name, tag in cands:
            if any(k in name.lower() for k in ("cam", "webcam", "摄像头", "usb video")):
                return name
        for name, tag in cands:
            if "(video)" in tag or "(none)" in tag:
                return name
        return cands[0][0] if cands else None

    def _variants(self):
        """不同相机接受的参数不一样（有的不接受 -framerate/-video_size），逐个试"""
        dev = f"video={self.device}"
        base = ["-f", "dshow", "-rtbufsize", "16M"]
        out = ["-vf", f"scale={self.w}:{self.h}", "-r", str(self.fps),
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return [
            base + ["-framerate", str(self.fps), "-video_size", f"{self.w}x{self.h}", "-i", dev] + out,
            base + ["-framerate", str(self.fps), "-i", dev] + out,
            base + ["-video_size", f"{self.w}x{self.h}", "-i", dev] + out,
            ["-f", "dshow", "-rtbufsize", "8M", "-i", dev] + out,
        ]

    @staticmethod
    def _read_exact(proc, n, timeout):
        """从管道读 n 字节，带超时（否则相机一卡住，read 会永久阻塞）"""
        box = {}

        def _rd():
            try:
                box["data"] = proc.stdout.read(n)
            except Exception:
                box["data"] = None

        th = threading.Thread(target=_rd, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            return None
        return box.get("data")

    def open(self):
        if not (self.ffmpeg and self.device):
            return False
        flags = 0x08000000 if os.name == "nt" else 0
        need = self.w * self.h * 3
        for k, args in enumerate(self._variants()):
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + args
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=need,
                                        creationflags=flags)
            except Exception:
                continue
            # 真读一帧才算成功；最多等 6 秒，超时就杀掉换下一组参数
            first = self._read_exact(proc, need, 6.0)
            if first and len(first) >= need:
                self.proc = proc
                self._first_frame = np.frombuffer(first, dtype=np.uint8).reshape(
                    self.h, self.w, 3)
                self.variant = k
                return True
            try:
                proc.kill()
            except Exception:
                pass
        self.proc = None
        return False

    def isOpened(self):
        return self.proc is not None and self.proc.poll() is None

    def read(self):
        # open() 已经读到第一帧，先把它交出去
        first = getattr(self, "_first_frame", None)
        if first is not None:
            self._first_frame = None
            return True, first.copy()
        if not self.isOpened():
            return False, None
        need = self.w * self.h * 3
        # 2 秒还读不到 → 认为这条流废了，交给上层重连（避免永久阻塞）
        buf = self._read_exact(self.proc, need, 2.0)
        if not buf or len(buf) < need:
            return False, None
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(self.h, self.w, 3)
        return True, frame.copy()

    def release(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None

    # cv2 的 set/get 在本类里是空操作，让上层代码不用特判
    def set(self, *a, **k):
        return False

    def get(self, *a, **k):
        return 0.0


# ---- 21 个手部关键点索引 ------------------------------------------------
WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),                 # 拇指
    (0, 5), (5, 6), (6, 7), (7, 8),                 # 食指
    (5, 9), (9, 10), (10, 11), (11, 12),            # 中指
    (9, 13), (13, 14), (14, 15), (15, 16),          # 无名指
    (13, 17), (17, 18), (18, 19), (19, 20),         # 小指
    (0, 17),
]




@dataclass
class HandState:
    """一帧手势快照（都是归一化后的数值，方便直接映射到画面）"""
    present: bool = False
    x: float = 0.5              # 掌心 x（0..1，镜像后）
    y: float = 0.5              # 掌心 y（0..1）
    pinch: float = 0.0          # 1 = 拇指食指完全捏合
    spread: float = 0.0         # 1 = 手指完全张开
    fingers: int = 0            # 伸出的手指数（0~5）
    index_up: bool = False      # 食指伸直
    middle_up: bool = False     # 中指伸直
    ring_up: bool = False       # 无名指伸直
    pinky_up: bool = False      # 小指伸直
    victory: bool = False       # ✌ 剪刀手：食指+中指伸直且分开、无名指小指收起
    index_only: bool = False    # ☝ 只有食指伸直
    finger_gap: float = 0.0     # 食指-中指指尖分开度（归一化）
    roll: float = 0.0           # 手掌倾角（弧度，upright=0）
    size: float = 0.0           # 手的屏幕占比（越大离镜头越近）
    label: str = ""             # 中文手势名
    preview: object = None      # pygame.Surface，摄像头预览（镜像）
    landmarks: object = None    # list[(x, y)] 0..1，用于画骨架
    fps: float = 0.0
    frame_id: int = 0           # 摄像头帧号
    detect_ratio: float = 0.0   # 最近 60 帧里检出到手的比例（0~1），用来判断"是手势不对还是根本没看到手"


class HandTracker:
    """后台线程抓摄像头 + 识别，主线程零阻塞地读最新结果"""

    def __init__(self, model_path: str, source=0, cam_size=(640, 480), preview_size=(210, 158)):
        if not (CV2_OK and MP_OK):
            raise RuntimeError("需要 opencv-python 和 mediapipe：pip install opencv-python mediapipe")
        if not os.path.isfile(model_path):
            raise RuntimeError(f"找不到手势模型：{model_path}")

        self.model_path = model_path
        self.source = source
        self.cam_w, self.cam_h = cam_size
        self.pw, self.ph = preview_size

        self._lock = threading.Lock()
        self._state = HandState()
        self._running = False
        self._thread = None
        self.error = None
        self._last_frame = None            # 最近一帧原始画面（BGR），用于截图诊断
        self._attempt = 0                  # 取流重试次数（写进日志用）

    def snapshot(self, path: str) -> bool:
        """把最近一帧摄像头画面存成图片（诊断构图用，不占摄像头）"""
        f = self._last_frame
        if f is None or not CV2_OK:
            return False
        try:
            cv2.imwrite(path, f)
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    # ---- 生命周期 ----
    def start(self):
        if self._running:
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="hand-tracker", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def latest(self) -> HandState:
        with self._lock:
            return self._state

    # ---- 打开视频源（摄像头可能会被别的程序短暂占用，所以做成可重连）----
    def _configure(self, cap):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_h)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        try:
            cap.set(cv2.CAP_PROP_FPS, 30)
        except Exception:
            pass

    @staticmethod
    def _warm_up(cap, tries=6):
        """真的读几帧再说成功：MSMF 常常能"打开"但一帧都不给你"""
        for _ in range(tries):
            ok, f = cap.read()
            if ok and f is not None:
                return True
            time.sleep(0.02)
        return False

    def _open_capture(self, verbose=False):
        if isinstance(self.source, str):                  # 视频文件（调试/演示）
            return cv2.VideoCapture(self.source), True
        # MSMF 延迟低，优先；但它在没有 COM 初始化的线程里会"能开不出帧"，
        # 所以打开后必须真读一帧验证，不行就换 DSHOW（DSHOW 不依赖 COM）。
        for backend in (cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY):
            t0 = time.perf_counter()
            cap = cv2.VideoCapture(int(self.source), backend)
            t1 = time.perf_counter()
            if not cap.isOpened():
                cap.release()
                if verbose:
                    print(f"[手势] backend {backend} 打不开（{t1 - t0:.2f}s）", flush=True)
                continue
            self._configure(cap)
            ok = self._warm_up(cap)
            if verbose:
                print(f"[手势] backend {backend} open={t1 - t0:.2f}s"
                      f" warm={time.perf_counter() - t1:.2f}s ok={ok}", flush=True)
            if ok:
                self.backend = backend
                return cap, False
            cap.release()
        # 兜底 1：cv2 用默认后端再试一次
        cap = cv2.VideoCapture(int(self.source))
        self._configure(cap)
        if self._warm_up(cap):
            self.backend = "cv2-default"
            return cap, False
        cap.release()

        # 兜底 2：ffmpeg 取流（OpenCV 的 videoio 坏掉时的救命通道）
        cam = FfmpegCamera(size=(self.cam_w, self.cam_h))
        if cam.open():
            self.backend = "ffmpeg"
            print(f"[手势] OpenCV 打不开相机 → 改用 ffmpeg 取流：{cam.device}", flush=True)
            return cam, False
        return cam, False

    # ---- 后台线程 ----
    def _loop(self):
        cap = None
        try:
            # Media Foundation(MSMF) 需要线程先做 COM 初始化，否则在子线程里取不到帧
            try:
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # APARTMENTTHREADED
            except Exception:
                pass

            cap, loop_video = self._open_capture(verbose=True)
            # 摄像头是独占设备：可能被另一个实例 / 会议软件占着 → 一直重试，直到拿到画面
            attempt = 0
            while self._running and not cap.isOpened():
                attempt += 1
                self._attempt = attempt
                if attempt == 1:
                    print("[手势] 摄像头打不开（被别的程序占用，或相机驱动卡住），正在自动重试。"
                          "若是驱动卡住，双击目录下的 修复相机.bat 重置一次即可", flush=True)
                elif attempt % 10 == 0:
                    print(f"[手势] 仍在重试摄像头（第 {attempt} 次）", flush=True)
                time.sleep(1.0)
                try:
                    cap.release()
                except Exception:
                    pass
                cap, loop_video = self._open_capture()
            if not self._running:
                return
            print(f"[手势] 摄像头已连接 backend={getattr(self, 'backend', '?')}"
                  f"（{self.cam_w}x{self.cam_h}）", flush=True)

            base = mp_python.BaseOptions(model_asset_path=self.model_path)
            opts = mp_vision.HandLandmarkerOptions(
                base_options=base,
                running_mode=mp_vision.RunningMode.VIDEO,
                num_hands=1,
                # 阈值压低一点：宁可偶尔误判，也不要"手在画面里却抓不到"
                min_hand_detection_confidence=0.35,
                min_hand_presence_confidence=0.35,
                min_tracking_confidence=0.30,
            )
            landmarker = mp_vision.HandLandmarker.create_from_options(opts)

            t0 = time.perf_counter()
            fps = 0.0
            last_t = t0
            last_ts = -1
            recent = deque(maxlen=60)          # 最近 60 帧的检出情况，用于算检出率
            frame_id = 0
            fail = 0
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    if loop_video:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    # 摄像头被别的程序抢了 / 掉线 → 隔一会儿重开，别一直空转
                    fail += 1
                    if fail >= 25:
                        fail = 0
                        try:
                            cap.release()
                        except Exception:
                            pass
                        time.sleep(0.4)
                        cap, _ = self._open_capture()
                        print(f"[手势] 摄像头重连 backend={getattr(self, 'backend', '?')}"
                              f" opened={cap.isOpened()}", flush=True)
                    time.sleep(0.03)
                    with self._lock:
                        self._state = HandState(present=False, preview=self._state.preview)
                    continue
                fail = 0

                frame = cv2.flip(frame, 1)                      # 镜像，符合直觉
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # detect_for_video 要求时间戳严格递增
                ts = max(int((time.perf_counter() - t0) * 1000), last_ts + 1)
                last_ts = ts

                st = HandState()
                try:
                    res = landmarker.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                    if res.hand_landmarks:
                        st = self._features(res.hand_landmarks[0], rgb.shape)
                except Exception as exc:                        # 单帧失败不影响整体
                    self.error = str(exc)

                # 预览小图（给 pygame 用）
                if PYGAME_OK:
                    small = cv2.resize(rgb, (self.pw, self.ph), interpolation=cv2.INTER_AREA)
                    small = np.ascontiguousarray(small)
                    st.preview = pygame.image.frombuffer(
                        small.tobytes(), (self.pw, self.ph), "RGB").copy()
                self._last_frame = frame                      # 留一份原图给截图用

                now = time.perf_counter()
                fps = 0.9 * fps + 0.1 / max(1e-3, now - last_t)
                last_t = now
                st.fps = fps
                frame_id += 1
                st.frame_id = frame_id
                recent.append(1 if st.present else 0)
                st.detect_ratio = sum(recent) / len(recent)
                with self._lock:
                    self._state = st

            landmarker.close()
        except Exception as exc:
            self.error = str(exc)
            with self._lock:
                self._state = HandState(present=False)
        finally:
            if cap is not None:
                cap.release()

    # ---- 关键点 → 手势特征 ----
    @staticmethod
    def _features(landmarks, shape):
        h, w = shape[0], shape[1]
        px = np.array([[p.x * w, p.y * h] for p in landmarks], dtype=np.float32)
        norm = np.array([[p.x, p.y] for p in landmarks], dtype=np.float32)

        wrist = px[WRIST]
        mid_mcp = px[MIDDLE_MCP]
        ref = float(np.linalg.norm(mid_mcp - wrist)) or 1.0     # 手掌参考长度
        palm = (wrist + mid_mcp) * 0.5

        def dist(a, b):
            return float(np.linalg.norm(px[a] - px[b]))

        # 捏合：拇指尖 ↔ 食指尖
        pinch = clamp(1.0 - (dist(THUMB_TIP, INDEX_TIP) / (ref * 0.85)))

        # 张开度：四个指尖到掌心的平均距离
        tips = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)
        d = np.mean([float(np.linalg.norm(px[t] - palm)) for t in tips]) / (ref * 1.55)
        spread = clamp(float(d))

        # 每根手指是否伸直（指尖离手腕比第二关节更远 = 伸直）
        def up(tip, pip):
            return (float(np.linalg.norm(px[tip] - wrist))
                    > float(np.linalg.norm(px[pip] - wrist)) * 1.10)

        index_up, middle_up = up(INDEX_TIP, INDEX_PIP), up(MIDDLE_TIP, MIDDLE_PIP)
        ring_up, pinky_up = up(RING_TIP, RING_PIP), up(PINKY_TIP, PINKY_PIP)
        thumb_up = dist(THUMB_TIP, PINKY_MCP) > ref * 0.92
        fingers = int(index_up) + int(middle_up) + int(ring_up) + int(pinky_up) + int(thumb_up)

        # ✌ 的判定要"食指中指分开 + 无名指小指收起"，普通张手不会被误认成 2 指
        finger_gap = dist(INDEX_TIP, MIDDLE_TIP) / (ref * 0.85)
        victory = bool(index_up and middle_up and not ring_up and not pinky_up
                       and finger_gap > 0.55)
        index_only = bool(index_up and not middle_up and not ring_up and not pinky_up)

        # 手掌倾角（竖直向上 = 0）
        roll = math.atan2(mid_mcp[1] - wrist[1], mid_mcp[0] - wrist[0]) + math.pi / 2
        while roll > math.pi:
            roll -= math.tau
        while roll < -math.pi:
            roll += math.tau

        st = HandState(
            present=True,
            x=float(np.clip(palm[0] / w, 0, 1)),
            y=float(np.clip(palm[1] / h, 0, 1)),
            pinch=pinch,
            spread=spread,
            fingers=fingers,
            index_up=bool(index_up), middle_up=bool(middle_up),
            ring_up=bool(ring_up), pinky_up=bool(pinky_up),
            victory=victory, index_only=index_only, finger_gap=float(finger_gap),
            roll=roll,
            size=float(np.clip(ref / h, 0, 1)),
            landmarks=[(float(a), float(b)) for a, b in norm],
        )
        st.label = _label_of(st)
        return st


def _label_of(st):
    """预览图上的人话手势名（判定逻辑和 christmas_tree._gesture_name 保持一致）"""
    if st.pinch > 0.62 and st.fingers <= 2:
        return "捏合 · 抓取"
    if st.index_only:
        return "1 指 · 圣诞树"
    if st.victory:
        return "剪刀手 · 相框"
    if st.fingers >= 5:
        return "五指张开 · 推开"
    if st.fingers <= 0:
        return "握拳 · 收拢"
    return "识别中…"


def draw_skeleton(surface, landmarks, color=(255, 200, 110), joint=(255, 245, 220), width=2):
    """在预览图上画手部骨架"""
    if not landmarks:
        return
    w, h = surface.get_size()
    pts = [(int(x * w), int(y * h)) for x, y in landmarks]
    for a, b in CONNECTIONS:
        pygame.draw.line(surface, color, pts[a], pts[b], width)
    for i, p in enumerate(pts):
        r = 3 if i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP) else 2
        pygame.draw.circle(surface, joint, p, r)


# =========================================================================
#  六、主程序
# =========================================================================
class App:
    def __init__(self, args):
        pygame.init()
        pygame.display.set_caption("MERRY CHRISTMAS · 手搓粒子圣诞树")

        flags = pygame.RESIZABLE if args.headless else (pygame.RESIZABLE | pygame.SCALED)
        try:
            self.screen = pygame.display.set_mode((VW, VH), flags)
        except pygame.error:
            self.screen = pygame.display.set_mode((VW, VH))
        self.frame = pygame.Surface((VW, VH))
        self.gw, self.gh = VW // GS, VH // GS
        self.glow = pygame.Surface((self.gw, self.gh))
        self.comp = pygame.Surface((self.gw, self.gh))

        # ---- 字体 / 文字 ----
        self.font_title = fit_font(30, ["georgia.ttf", "times.ttf", "constan.ttf", "pala.ttf"])
        title_alpha = render_tracked(self.font_title, "MERRY CHRISTMAS", 11, WARM_WHITE)
        # 压到黑底上 → RGB 变成预乘 alpha，加法叠加时笔锋才干净
        self.title = pygame.Surface(title_alpha.get_size())
        self.title.fill((0, 0, 0))
        self.title.blit(title_alpha, (0, 0))
        self.title_glow = soft_glow(self.title, passes=3, factor=2.6)
        self.title_glow.fill((150, 140, 120), special_flags=pygame.BLEND_RGB_MULT)
        self.font_hint = fit_font(15, ["msyh.ttc", "simhei.ttf", "simsun.ttc"])
        self.font_small = fit_font(13, ["msyh.ttc", "simhei.ttf", "simsun.ttc"])
        self.hint = self.font_hint.render(
            "捏合 抓粒子 │ 五指张开 推开 │ 食指 树 │ 剪刀手 相框 │ 五指 星球 │ A 自动演出 │ V 预览 │ D 数值 │ H 隐藏",
            True, (146, 158, 186))

        self.t = 0.0
        self.rot = 0.0
        self.mouse = (-9999.0, -9999.0)
        self.show_hint = True
        self.show_pip = True
        self.show_debug = True
        self.auto = False        # 默认不自动播放：只有识别到手势（或按键）才切形态
        self.shot = 0

        # ---- 粒子 ----
        self.n = max(200, args.particles)
        self.SHAPE_POS = {}
        self.SHAPE_SZ = {}
        self._roll_shapes()
        self.cidx = [pick_color_idx() for _ in range(self.n)]
        self.particles = [Particle(self.SHAPE_POS["tree"][i]) for i in range(self.n)]

        self.halo_cache = {}
        self.gifts = [Gift() for _ in range(16)]
        self._place_gifts()
        self.snow = [Snow(VW, VH) for _ in range(190)]
        self.bokeh = [Snow(VW, VH) for _ in range(10)]

        # ---- 状态机 ----
        self.seg_i = 0
        self.seg_t = 0.0
        self.prev_shape = "tree"
        self.cur_shape = "tree"
        self.morph_e = 0.0
        self.photo_alpha = 0.0
        self.gift_alpha = 1.0
        self.gift_spread = 0.0
        self.star = [0.0, TREE_TOP - 34.0, 0.0]
        self.star_size = 17.0
        self.hand_rot = 0.0

        # ---- 预渲染 ----
        self.bg = self._make_bg()
        self.vignette = self._make_vignette()
        self.vignette_glow = pygame.transform.smoothscale(self.vignette, (self.gw, self.gh))
        self.aura_warm = make_aura((112, 62, 20), 300, power=2.3, dim=0.55)
        self.aura_cool = make_aura((18, 26, 48), 400, power=2.6, dim=0.6)

        # ---- 相框照片 ----
        pw, ph = int(FRAME_HW * 2 - 34), int(FRAME_HH * 2 - 34)
        self.photo = load_photo(args.photo, (pw, ph))
        self.photo_rect = self.photo.get_rect(center=(int(CENTER[0]), int(CENTER[1])))

        self.flare = make_flare(34, (255, 250, 226), spikes=4, sharp=2.4)
        self.clock = pygame.time.Clock()

        # ---- 手势 ----
        self.hand = None                 # 最近一帧手势
        self.hand_on = False
        self.hand_lost = 0.0
        self.hand_xy = None              # 平滑后的手心屏幕坐标
        self.hand_pos = None
        self.hand_grab = 0.0
        self.hand_push = 0.0
        self.hand_drive_t = 99.0         # 距离上次"真的在操作"过了多久
        self.fx = OneEuro(mincutoff=9.0, beta=0.012)              # 手心 x / y 的 One Euro 滤波（低延迟跟手）
        self.fy = OneEuro(mincutoff=9.0, beta=0.012)
        self.push_prev = 0.0
        self.push_kick = 0.0             # 张开瞬间的冲量，几帧内衰减
        self.recover = 0.0               # 推开后的"松散期"，让粒子慢慢飘回
        self.label_keep = ""
        self._label_ttl = 0.0
        self._warned_no_hand = False
        self._snapped = False
        self._hand_seen = False
        self._stat_t = 0.0
        self.gesture = None
        self.gesture_t = 0.0
        self.gesture_cd = 0.0
        self.tracker = None
        if args.hand:
            self._init_hand(args)

    # ---------------- 手势初始化 ----------------
    def _init_hand(self, args):
        if not (CV2_OK and MP_OK):
            print("[手势] 缺少 opencv-python / mediapipe，跳过手势控制"
                  "（pip install opencv-python mediapipe）")
            return
        model = args.hand_model or ensure_hand_model()
        if not model:
            return
        src = args.hand_video if args.hand_video else args.cam
        try:
            self.tracker = HandTracker(model, source=src).start()
            self.hand_on = True
            print(f"[手势] 已启动：{src}")
        except Exception as exc:
            print(f"[手势] 启动失败：{exc}")
            self.tracker = None

    # ---------------- 生成 / 重排 ----------------
    def _roll_shapes(self):
        self.SHAPE_POS["tree"], self.SHAPE_SZ["tree"] = gen_tree(self.n)
        self.SHAPE_POS["frame"], self.SHAPE_SZ["frame"] = gen_frame(self.n)
        self.SHAPE_POS["cloud"], self.SHAPE_SZ["cloud"] = gen_cloud(self.n)

    def _place_gifts(self):
        for g in self.gifts:
            u = random.random() ** 0.9
            y = TREE_TOP + (TREE_BOT - TREE_TOP) * 0.86 * u + 12
            r = TREE_R * (u ** 1.22) * random.uniform(0.95, 1.10)
            a = random.uniform(0, math.tau)
            g.tree_pt = (r * math.cos(a), y, r * math.sin(a))
            rr = CLOUD_R * random.uniform(0.75, 1.0)
            b = random.uniform(0, math.tau)
            g.cloud_pt = (rr * math.cos(b), rr * random.uniform(-0.7, 0.7) + 16, rr * math.sin(b))

    # ---------------- 背景 / 暗角 ----------------
    def _make_bg(self):
        """低分辨率画好再放大，又快又平滑"""
        sw, sh = 64, 40
        small = pygame.Surface((sw, sh))
        cx, cy = CENTER[0] / VW * sw, CENTER[1] / VH * sh
        maxd = math.hypot(max(cx, sw - cx), max(cy, sh - cy))
        for y in range(sh):
            for x in range(sw):
                k = clamp(math.hypot(x - cx, (y - cy) * 1.15) / maxd) ** 1.45
                small.set_at((x, y), (int(lerp(15, 4, k)), int(lerp(19, 6, k)), int(lerp(33, 11, k))))
        return pygame.transform.smoothscale(small, (VW, VH))

    def _make_vignette(self):
        """四角压暗"""
        sw, sh = 80, 50
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        for y in range(sh):
            for x in range(sw):
                dx = (x - sw / 2) / (sw / 2)
                dy = (y - sh / 2) / (sh / 2)
                d = clamp(math.hypot(dx, dy) / 1.45)
                small.set_at((x, y), (0, 0, 0, int(clamp((d - 0.42) / 0.58) ** 1.5 * 205)))
        return pygame.transform.smoothscale(small, (VW, VH))

    def _halo(self, ci, radius, gain):
        """按 (颜色, 亮度档, 半径) 缓存光晕贴图；radius 已在发光层坐标系里"""
        b = 0 if gain < 0.50 else (1 if gain < 0.72 else (2 if gain < 0.94 else 3))
        rad = max(1, int(round(radius)))
        key = (ci, b, rad)
        s = self.halo_cache.get(key)
        if s is None:
            c = PALETTE[ci][0]
            f = BRIGHT_FACTOR[b]
            s = make_halo((min(255, int(c[0] * f)), min(255, int(c[1] * f)), min(255, int(c[2] * f))),
                          rad, power=2.5, core=0.33)
            self.halo_cache[key] = s
        return s

    # ---------------- 演出控制 ----------------
    def burst(self, strength=1.0):
        """给所有粒子一个向外的冲量 —— 视频里"炸开"的那一下"""
        for p in self.particles:
            d = math.sqrt(p.x * p.x + p.y * p.y + p.z * p.z) or 1.0
            k = strength * random.uniform(120, 330)
            p.vx += p.x / d * k
            p.vy += p.y / d * k * 0.9
            p.vz += p.z / d * k

    def next_segment(self, force_shape=None):
        self.prev_shape = self.cur_shape
        if force_shape:
            for i, seg in enumerate(SEQUENCE):
                if seg["shape"] == force_shape:
                    self.seg_i = i
                    break
        else:
            self.seg_i = (self.seg_i + 1) % len(SEQUENCE)
        self.cur_shape = SEQUENCE[self.seg_i]["shape"]
        self.seg_t = 0.0
        if SEQUENCE[self.seg_i]["burst"]:
            self.burst(SEQUENCE[self.seg_i].get("burst_power", 1.0))

    # ---------------- 手势 ----------------
    def _read_hand(self, dt):
        """读手势 → 更新抓取/推开/旋转参数，并处理"手势切形态"

        真摄像头的数据是抖的（还有 20% 左右漏检），所以这里做了：
          · 手心位置 / 抓取力 / 推开力 都做指数平滑，光流不抖
          · 漏检时不立刻归零，衰减过去（手短暂丢失不会让整棵树弹一下）
          · 只有"真的在操作"（有捏合/推开）才暂停自动演出，光是手在画面里不算
        """
        if not (self.hand_on and self.tracker):
            self.hand_grab = self.hand_push = 0.0
            self.hand_pos = None
            self.hand_drive_t += dt
            return

        st = self.tracker.latest()
        self.hand = st

        if not st.present:
            self.hand_lost += dt
            self.gesture, self.gesture_t = None, 0.0
            k = clamp(dt * 6.0)                       # 没手了：力慢慢退掉
            self.hand_grab = lerp(self.hand_grab, 0.0, k)
            self.hand_push = lerp(self.hand_push, 0.0, k)
            self.hand_rot = lerp(self.hand_rot, 0.0, clamp(dt * 2.5))
            self.hand_drive_t += dt
            if self.hand_lost > 0.8:
                self.hand_pos = None
                self.fx.reset()
                self.fy.reset()
                self.push_kick = 0.0
            self._label_ttl = max(0.0, self._label_ttl - dt)
            return

        self.hand_lost = 0.0

        # ---- 先判定"姿态"，姿态决定要不要出力（避免松开五指去比剪刀手时误推一把）----
        g = self._gesture_name(st)
        pose_mode = g in ("ONE", "TWO")            # 比造型的时候不推

        # ---- 手心位置：随动放大 + One Euro 滤波（低延迟，不抖）----
        gx = clamp(0.5 + (st.x - 0.5) * HAND_GAIN)
        gy = clamp(0.5 + (st.y - 0.5) * HAND_GAIN)
        raw_x, raw_y = gx * VW, gy * VH
        fx, fy = self.fx(raw_x, dt), self.fy(raw_y, dt)
        if self.hand_xy is None:
            self.hand_xy = [fx, fy]
        else:
            self.hand_xy[0], self.hand_xy[1] = fx, fy
        self.hand_pos = (self.hand_xy[0], self.hand_xy[1])

        # ---- 力度：先把"原始张合度"重映射到 0~1，再快速平滑 ----
        # 实测：手放松时 spread≈0.5、完全张开≈0.95；捏合时 pinch≈0.9。
        # 直接用原值当力度，放松状态就几乎没有力 → 手感发木。
        # 死区：手"放着不动"时几乎不出力（否则树一直被推歪），真要捏/张开才给满力
        grab_raw = clamp((st.pinch - 0.28) / 0.55)
        push_raw = clamp((st.spread - 0.44) / 0.36) * (1.0 - grab_raw)
        if pose_mode:
            push_raw = 0.0
        kf = clamp(dt * 60.0)                      # 力要跟得紧，别拖
        self.hand_grab = lerp(self.hand_grab, grab_raw, kf)
        self.hand_push = lerp(self.hand_push, push_raw, kf)
        self.hand_rot = lerp(self.hand_rot, clamp(st.roll * 1.4, -1.1, 1.1), clamp(dt * 6.0))

        # 张开的那一下给个额外冲量（"砰"地把粒子吹散，而不是慢慢挤开）
        if self.hand_push > 0.55 and self.push_prev < 0.35:
            self.push_kick = 1.0
        self.push_prev = self.hand_push
        self.push_kick = max(0.0, self.push_kick - dt * 2.2)
        # 推开后留一段"松散期"：粒子慢慢飘回来，而不是啪一下弹回原位
        if self.hand_push > 0.45:
            self.recover = 1.0
        self.recover = max(0.0, self.recover - dt * 0.6)

        # 真的在操作吗？（决定要不要暂停自动演出）
        if self.hand_grab > 0.12 or self.hand_push > 0.10:
            self.hand_drive_t = 0.0

        # ---- 手势停留 → 切形态 ----
        self.gesture_cd = max(0.0, self.gesture_cd - dt)
        if g != self.gesture:
            self.gesture, self.gesture_t = g, 0.0
        else:
            self.gesture_t += dt
        target = GESTURE_SHAPE.get(g)
        if (target and self.gesture_t > GESTURE_HOLD and self.gesture_cd <= 0.01
                and target != self.cur_shape):
            self.next_segment(target)
            self.gesture_cd = GESTURE_CD

        # 标签保持 0.5 秒，避免漏检一帧就闪成"未检测到手"
        self.label_keep = st.label
        self._label_ttl = 0.5

    @staticmethod
    def _gesture_name(st):
        """姿态判定：每个能切形态的姿势都必须"长得足够不一样"，避免互相误触发

        PINCH  捏合           → 抓粒子（不切形态）
        FIST   握拳           → 收拢（不切形态）
        ONE    只有食指伸直   → 圣诞树
        TWO    ✌ 食指中指分开、无名指小指收起 → 相框
        PALM   五指全张开     → 推开 + 星球
        OTHER  3~4 指等中间态 → 什么都不做
        """
        if st.pinch > 0.55 and st.fingers <= 2:
            return "PINCH"
        if st.fingers <= 0:
            return "FIST"
        if st.index_only:
            return "ONE"
        if st.victory:
            return "TWO"
        if st.fingers >= 5:
            return "PALM"
        return "OTHER"

    # ---------------- 每帧更新 ----------------
    def step(self, dt):
        """一帧拆成小步跑，低帧率录制时时间线也按真实时间走"""
        dt = min(dt, 0.25)
        while dt > 1e-6:
            sub = min(dt, 1.0 / 50.0)
            self._tick(sub)
            dt -= sub

    def _tick(self, dt):
        self.t += dt

        self._read_hand(dt)
        # 长时间看不到手 → 控制台提醒 + 自动存一张相机截图（方便排查构图）
        if self.hand_on:
            if self.hand_lost > 5.0 and not self._warned_no_hand:
                print("[手势] 摄像头看不到手：把手抬到镜头上方取景框里（40~70cm）", flush=True)
                self._warned_no_hand = True
            elif self.hand_lost < 0.5:
                self._warned_no_hand = False
            st_now = self.hand
            if (st_now is not None and st_now.frame_id > 0
                    and self.hand_lost > 8.0 and not self._snapped):
                self.save_cam_snapshot()
            # 只在"手进/出画面"时报一句，别刷屏
            if (st_now is not None and st_now.frame_id > 0 and st_now.present
                    and not self._hand_seen):
                self._hand_seen = True
                print(f"[手势] 识别到手（相机 {st_now.fps:.0f}fps，检出 "
                      f"{st_now.detect_ratio * 100:.0f}%）—— 捏合抓、张开推", flush=True)
            elif (self._hand_seen and self.hand_lost > 1.0):
                self._hand_seen = False
                print("[手势] 手离开画面", flush=True)
            # 每 10 秒往日志里记一行状态（只落盘，不刷控制台）
            self._stat_t += dt
            if self._stat_t >= 10.0:
                self._stat_t = 0.0
                if st_now is None or st_now.frame_id == 0:
                    log(f"[状态] 无相机画面（backend={getattr(self.tracker, 'backend', '?')}）"
                        f" 已重试 {getattr(self.tracker, '_attempt', '?')} 次")
                else:
                    log(f"[状态] backend={getattr(self.tracker, 'backend', '?')}"
                        f" frames={st_now.frame_id} fps={st_now.fps:.1f}"
                        f" detect={st_now.detect_ratio * 100:.0f}%"
                        f" present={st_now.present} retry={getattr(self.tracker, '_attempt', 0)}")
        # 只有你"真的在操作"（捏合/推开）时才暂停自动演出；
        # 手只是放在画面里不会打断动画，停手 3 秒后演出自动继续。
        hand_directing = (self.hand_on and self.hand_drive_t < 3.0
                          and not getattr(self, "keep_auto", False))

        if self.auto and not hand_directing:
            self.seg_t += dt
            if self.seg_t > SEQUENCE[self.seg_i]["morph"] + SEQUENCE[self.seg_i]["hold"]:
                self.next_segment()
        else:
            self.seg_t += dt
        self.morph_e = ease(self.seg_t / max(1e-3, SEQUENCE[self.seg_i]["morph"]))
        e = self.morph_e

        # 自转（相框权重为 0，所以会正对镜头）
        self.rot += ROT_SPEED * dt * lerp(ROT_WEIGHT[self.prev_shape],
                                          ROT_WEIGHT[self.cur_shape], e)

        # 透明度过渡
        tgt_photo = (ease(clamp((self.morph_e - 0.52) / 0.44))
                     if self.cur_shape == "frame" else 0.0)
        self.photo_alpha += (tgt_photo - self.photo_alpha) * clamp(dt * 7.0)
        self.gift_alpha += ((0.18 if self.cur_shape == "frame" else 1.0)
                            - self.gift_alpha) * clamp(dt * 5.0)
        self.gift_spread += ((1.0 if self.cur_shape == "cloud" else 0.0)
                             - self.gift_spread) * clamp(dt * 4.0)

        # 星芒目标
        if self.cur_shape == "tree":
            st, ss = (0.0, TREE_TOP - 40.0, 0.0), 27.0
        elif self.cur_shape == "frame":
            st, ss = (0.0, -FRAME_HH - 28.0, 0.0), 17.0
        else:
            st, ss = (0.0, -CLOUD_R * 0.58, 0.0), 27.0
        for k in range(3):
            self.star[k] = lerp(self.star[k], st[k], clamp(dt * 4.0))
        self.star_size = lerp(self.star_size, ss, clamp(dt * 4.0))

        # ---- 粒子物理 ----
        # 关键改动：手不再用"力场"推拉，而是直接把粒子的**目标点**搬过去。
        #   · 捏合 → 目标点 = 手心（粒子被粘在手上，手一动立刻跟）
        #   · 张开 → 目标点 = 以手为圆心、半径 PUSH_REACH 的圆环（距离可预期，不会被弹簧拽回）
        mx, my = self.mouse
        has_hand = self.hand_pos is not None
        hx, hy = self.hand_pos if has_hand else (-9999.0, -9999.0)
        grab, push = self.hand_grab, self.hand_push
        kick = HAND_PUSH_KICK * self.push_kick
        rot = self.rot + self.hand_rot * lerp(ROT_WEIGHT[self.prev_shape],
                                              ROT_WEIGHT[self.cur_shape], e)
        ca, sa = math.cos(rot), math.sin(rot)
        cx, cy = CENTER
        swirl = 1.0 if self.cur_shape == "cloud" else 0.0
        PA = self.SHAPE_POS[self.prev_shape]
        PB = self.SHAPE_POS[self.cur_shape]
        # 推开之后弹簧变软 → 粒子慢慢飘回，而不是啪一下弹回去
        base_k = 52.0 * (1.0 - RECOVER_YIELD * clamp(self.recover))
        hand_active = has_hand and (grab > 0.02 or push > 0.02)
        R_hand = HAND_R_MIN + HAND_R_K * push

        for i, p in enumerate(self.particles):
            a = PA[i]
            b = PB[i]
            tx = lerp(a[0], b[0], e) + math.sin(self.t * 1.7 + p.ph) * 1.6
            ty = lerp(a[1], b[1], e) + math.cos(self.t * 1.3 + p.ph * 1.7) * 1.6
            tz = lerp(a[2], b[2], e) + math.sin(self.t * 1.1 + p.ph * 0.6) * 1.6

            # 粒子当前的屏幕位置（手/鼠标都在屏幕空间交互）
            rx = p.x * ca - p.z * sa
            rz = p.x * sa + p.z * ca
            persp = FOCAL / max(140.0, FOCAL + rz)
            sx = cx + rx * persp
            sy = cy + p.y * persp

            k = base_k
            # —— 手：搬目标点 ——
            if hand_active:
                dxh = hx - sx
                dyh = hy - sy
                dh = math.hypot(dxh, dyh)
                if dh < R_hand:
                    w = (1.0 - dh / R_hand) ** 1.0
                    gw = min(1.0, grab * w)
                    pw = min(1.0, push * w * 1.2)
                    # 注意：拖动必须在"旋转后坐标系"里做。
                    # 直接改世界坐标 p.x 时，屏幕上的位移会被 cos(rot) 打折，
                    # 树转到侧面时 x 方向几乎不动 —— 这就是之前"推不动"的元凶。
                    nrx = rx
                    ny = p.y
                    if gw > 0.01:                        # 捏合：朝手心拖（越近吸得越快）
                        f = min(0.85, gw * 15.0 * dt)
                        nrx += max(-70.0, min(70.0, dxh * f)) / persp
                        ny += max(-70.0, min(70.0, dyh * f)) / persp
                        k *= (1.0 - 0.90 * gw)           # 被抓住时松开弹簧，别跟手抢
                    if pw > 0.01 and dh > 2.0:           # 张开：拖到以手为心的圆环上
                        ox, oy = -dxh / dh, -dyh / dh     # 从手指向粒子（向外）
                        f = min(0.85, pw * 11.0 * dt)
                        nrx += max(-80.0, min(80.0, (hx + ox * PUSH_REACH - sx) * f)) / persp
                        ny += max(-80.0, min(80.0, (hy + oy * PUSH_REACH - sy) * f)) / persp
                        k *= (1.0 - 0.85 * pw)
                        if kick > 1.0:                   # 张手那一下的冲刺感
                            p.vx += ox * kick * pw * dt
                            p.vy += oy * kick * pw * dt
                    if nrx != rx or ny != p.y:
                        p.x = nrx * ca + rz * sa
                        p.z = -nrx * sa + rz * ca
                        p.y = ny

            # —— 鼠标撩粒子 ——
            if mx > -9000:
                dx, dy = sx - mx, sy - my
                d2 = dx * dx + dy * dy
                R = 128.0
                if d2 < R * R:
                    d = math.sqrt(d2) or 1.0
                    f = (1.0 - d / R) ** 2 * 9000.0
                    p.vx += dx / d * f * dt
                    p.vy += dy / d * f * dt

            # —— 积分 ——
            damp = 9.6
            p.vx += ((tx - p.x) * k - p.vx * damp) * dt
            p.vy += ((ty - p.y) * k - p.vy * damp) * dt
            p.vz += ((tz - p.z) * k - p.vz * damp) * dt
            if swirl:
                p.vx += (-p.z) * 0.30 * dt
                p.vz += (p.x) * 0.30 * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.z += p.vz * dt

        # 雪
        for s in self.snow:
            s.y += s.vy * dt
            s.x += (s.vx + math.sin(self.t * s.spd + s.ph) * 7.0) * dt
            if s.y > VH + 6:
                s.y, s.x = -6.0, random.uniform(0, VW)
            if s.x < -8:
                s.x = VW + 8
            elif s.x > VW + 8:
                s.x = -8
        for s in self.bokeh:
            s.y += s.vy * 0.30 * dt
            if s.y > VH + 40:
                s.y, s.x = -40.0, random.uniform(0, VW)

    # ---------------- 渲染 ----------------
    def render(self):
        fr = self.frame
        fr.blit(self.bg, (0, 0))
        fr.blit(self.aura_cool, (int(CENTER[0] - 400), int(CENTER[1] - 400)),
                special_flags=pygame.BLEND_RGB_ADD)
        fr.blit(self.aura_warm, (int(CENTER[0] - 300), int(CENTER[1] - 280)),
                special_flags=pygame.BLEND_RGB_ADD)

        # 相框里的照片（在发光层下面，被金边压住）
        if self.photo_alpha > 0.01:
            ph = self.photo.copy()
            ph.set_alpha(int(clamp(self.photo_alpha) * 255))
            fr.blit(ph, self.photo_rect)

        # ============ 发光层（半分辨率 + 黑底加法）============
        gl = self.glow
        gl.fill((0, 0, 0))
        rot = self.rot + self.hand_rot * lerp(ROT_WEIGHT[self.prev_shape],
                                              ROT_WEIGHT[self.cur_shape], self.morph_e)
        ca, sa = math.cos(rot), math.sin(rot)
        cx, cy = CENTER[0] * 0.5, CENTER[1] * 0.5
        get_halo = self._halo
        SA = self.SHAPE_SZ[self.prev_shape]
        SB = self.SHAPE_SZ[self.cur_shape]
        e = self.morph_e
        gmul = lerp(GAIN_BY_SHAPE[self.prev_shape], GAIN_BY_SHAPE[self.cur_shape], e)
        gw, gh = self.gw, self.gh

        for i, p in enumerate(self.particles):
            rx = p.x * ca - p.z * sa
            rz = p.x * sa + p.z * ca
            persp = FOCAL / max(140.0, FOCAL + rz)
            sx = cx + rx * persp * 0.5
            sy = cy + p.y * persp * 0.5
            if sx < -40 or sx > gw + 40 or sy < -40 or sy > gh + 40:
                continue
            base = lerp(SA[i], SB[i], e)
            tw = 0.80 + 0.32 * math.sin(self.t * p.tw + p.ph)
            gain = (0.30 + 0.46 * persp) * tw * gmul
            rad = (base * (0.55 + 0.55 * persp) * 1.75 + 2.0) * 0.5
            spr = get_halo(self.cidx[i], rad, gain)
            gl.blit(spr, (int(sx - spr.get_width() * 0.5), int(sy - spr.get_height() * 0.5)),
                    special_flags=pygame.BLEND_RGB_ADD)

        if self.gift_alpha > 0.03:
            self._draw_gifts(gl, ca, sa)
        if self.photo_alpha > 0.02:
            self._draw_frame_edge(gl)

        # 雪（放进发光层，自带 bloom）
        for s in self.snow:
            tw = 0.40 + 0.60 * abs(math.sin(self.t * s.spd + s.ph))
            spr = get_halo(2, s.r * 1.15 + 1.0, 0.20 + 0.50 * tw)
            gl.blit(spr, (int(s.x * 0.5 - spr.get_width() * 0.5), int(s.y * 0.5 - spr.get_height() * 0.5)),
                    special_flags=pygame.BLEND_RGB_ADD)
        for s in self.bokeh:
            spr = get_halo(6, s.r * 3.0, 0.09)
            gl.blit(spr, (int(s.x * 0.5 - spr.get_width() * 0.5), int(s.y * 0.5 - spr.get_height() * 0.5)),
                    special_flags=pygame.BLEND_RGB_ADD)

        # 手的位置画几个光圈（反馈：捏合变亮收紧，张开变暗放大）
        if self.hand_pos:
            hx, hy = self.hand_pos[0] * 0.5, self.hand_pos[1] * 0.5
            r = int(52 + 46 * self.hand_push - 20 * self.hand_grab)
            warm = int(45 + 150 * self.hand_grab)
            pygame.draw.circle(gl, (warm, int(warm * 0.76), int(warm * 0.34)),
                               (int(hx), int(hy)), max(6, r), 1)
            pygame.draw.circle(gl, (warm // 3, max(4, warm // 3), 8),
                               (int(hx), int(hy)), max(3, r - 13), 1)

        # ============ 合成：小图里做 glow + bloom，最后一次放大 ============
        comp = self.comp
        comp.fill((0, 0, 0))
        comp.blit(gl, (0, 0))
        # bloom：先缩小，再乘一个系数控制强度（fill + BLEND_RGB_MULT 就是整图乘）
        b4 = pygame.transform.smoothscale(gl, (max(1, self.gw // 4), max(1, self.gh // 4)))
        b4.fill((188, 188, 188), special_flags=pygame.BLEND_RGB_MULT)
        comp.blit(pygame.transform.smoothscale(b4, (self.gw, self.gh)), (0, 0),
                  special_flags=pygame.BLEND_RGB_ADD)
        b8 = pygame.transform.smoothscale(b4, (max(1, self.gw // 8), max(1, self.gh // 8)))
        b8.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_MULT)
        comp.blit(pygame.transform.smoothscale(b8, (self.gw, self.gh)), (0, 0),
                  special_flags=pygame.BLEND_RGB_ADD)
        comp.blit(self.vignette_glow, (0, 0))          # 四周压暗（在发光层做，省一次全屏混合）
        fr.blit(pygame.transform.smoothscale(comp, (VW, VH)), (0, 0),
                special_flags=pygame.BLEND_RGB_ADD)

        # 星芒（全分辨率，保证干脆）
        self._draw_star(fr)

        # 标题：柔光 + 清晰字
        tw_, th_ = self.title.get_size()
        tx = int(VW * 0.5 - tw_ * 0.5)
        ty = int(VH * 0.072)
        fr.blit(self.title_glow, (tx, ty), special_flags=pygame.BLEND_RGB_ADD)
        fr.blit(self.title, (tx, ty), special_flags=pygame.BLEND_RGB_ADD)

        # 提示 / 摄像头预览
        if self.show_hint:
            fr.blit(self.hint, (18, VH - 32))
        if self.show_pip and self.hand_on and self.hand is not None:
            self._draw_pip(fr)

    def _draw_pip(self, fr):
        """右下角摄像头预览 + 手骨架 + 手势名"""
        st = self.hand
        if st is None:
            return
        if st.preview is None:
            # 一帧画面都没有：也要明确说一句，别让人以为程序坏了
            msg = "摄像头未就绪 · 自动重试中（被占用或驱动卡住 → 可双击 修复相机.bat）"
            surf = self.font_hint.render(msg, True, (255, 186, 120))
            fr.blit(surf, (VW - surf.get_width() - 18, VH - 46))
            return
        pw, ph = st.preview.get_size()
        pip = st.preview.copy()
        if st.present and st.landmarks:
            try:
                draw_skeleton(pip, st.landmarks)
            except Exception:
                pass
        rect = pygame.Rect(VW - pw - 18, VH - ph - 52, pw, ph)
        fr.blit(pip, rect)
        # 取景角标：告诉用户"手掌应该出现在这个框里"
        ccol = (255, 196, 96) if st.present else (92, 108, 138)
        for ax, ay, dx, dy in ((rect.x + 13, rect.y + 11, 1, 1), (rect.right - 13, rect.y + 11, -1, 1),
                               (rect.x + 13, rect.bottom - 11, 1, -1),
                               (rect.right - 13, rect.bottom - 11, -1, -1)):
            pygame.draw.line(fr, ccol, (ax, ay), (ax + dx * 15, ay), 2)
            pygame.draw.line(fr, ccol, (ax, ay), (ax, ay + dy * 15), 2)
        pygame.draw.rect(fr, GOLD if st.present else (66, 78, 104), rect.inflate(6, 6), 1, border_radius=9)
        # 漏检一帧时用上一个标签撑 0.5 秒，不然会一直闪
        if st.present:
            txt, col = st.label, (255, 222, 168)
        elif self._label_ttl > 0 and self.label_keep:
            txt, col = self.label_keep, (200, 186, 150)
        else:
            txt, col = "未检测到手", (120, 132, 156)
        # 造型保持进度：摆对了会看到百分比往上走，摆满就切形态（不然会以为"没反应"）
        if st.present and GESTURE_SHAPE.get(self.gesture) and self.gesture_t > 0.05:
            prog = int(clamp(self.gesture_t / GESTURE_HOLD) * 100)
            txt = f"{txt}  {prog}%"
        surf = self.font_hint.render(txt, True, col)
        fr.blit(surf, (rect.centerx - surf.get_width() // 2, rect.bottom + 7))
        # 数值回显：直接看到摄像头眼里的"张开度 / 捏合度"，方便判断是不是手不够开
        if self.show_debug and st.present:
            dbg = self.font_small.render(
                f"张开 {st.spread:.2f}   捏合 {st.pinch:.2f}   {st.fingers} 指", True, (150, 168, 200))
            fr.blit(dbg, (rect.centerx - dbg.get_width() // 2, rect.bottom + 25))
        # 相机状态 + 检出率：区分"手没摆对"和"镜头根本没看到手"
        status = self.font_small.render(
            f"相机 {st.fps:.0f}fps · 检出 {st.detect_ratio * 100:.0f}%", True, (120, 134, 158))
        fr.blit(status, (rect.centerx - status.get_width() // 2, rect.top - 20))
        # 长时间看不到手 → 直接把原因和改法写在屏幕上
        if st.detect_ratio < 0.06 and self.hand_lost > 2.0:
            lines = ("镜头里看不到手：把手抬进上面那个取景框",
                     "脸被切掉/只看到天花板 → 笔记本往后挪 30~50cm，屏幕再掀起来一点")
            for k, line in enumerate(lines):
                warn = self.font_small.render(line, True, (255, 186, 120))
                fr.blit(warn, (rect.centerx - warn.get_width() // 2, rect.top - 44 - k * 19))

    def _draw_gifts(self, gl, ca, sa):
        cx, cy = CENTER[0] * 0.5, CENTER[1] * 0.5
        alpha = clamp(self.gift_alpha)
        sp = ease(clamp(self.gift_spread))
        for g in self.gifts:
            x = lerp(g.tree_pt[0], g.cloud_pt[0], sp)
            y = lerp(g.tree_pt[1], g.cloud_pt[1], sp) + math.sin(self.t * 1.1 + g.bob) * 6.0
            z = lerp(g.tree_pt[2], g.cloud_pt[2], sp)
            rx = x * ca - z * sa
            rz = x * sa + z * ca
            persp = FOCAL / max(140.0, FOCAL + rz)
            self._draw_cube(gl, cx + rx * persp * 0.5, cy + y * persp * 0.5,
                            g.s * persp * 0.5,
                            g.rot + self.rot * 1.3 + self.t * g.spin * 0.35,
                            g.body, g.ribbon, alpha)

    @staticmethod
    def _draw_cube(surf, cx, cy, size, ang, body, ribbon, alpha=1.0):
        """2D 假 3D 小礼盒"""
        if size < 1.2 or alpha <= 0.01:
            return
        h = size * 0.5
        ca, sa = math.cos(ang), math.sin(ang)
        off = size * 0.55

        def P(x, y):
            return (cx + x * ca - y * sa, cy + x * sa + y * ca)

        def C(c, k):
            return (int(clamp(c[0] * k * alpha, 0, 255)),
                    int(clamp(c[1] * k * alpha, 0, 255)),
                    int(clamp(c[2] * k * alpha, 0, 255)))

        fy0 = -h + off * 0.40
        fy1 = h + off * 0.40
        pygame.draw.polygon(surf, C(body, 0.95), [P(-h, fy0), P(h, fy0), P(h, fy1), P(-h, fy1)])
        pygame.draw.polygon(surf, C(body, 1.35), [P(-h, fy0), P(h, fy0),
                                                  P(h - size * 0.22, fy0 - off * 0.9),
                                                  P(-h - size * 0.22, fy0 - off * 0.9)])
        pygame.draw.polygon(surf, C(body, 0.58), [P(h, fy0), P(h - size * 0.22, fy0 - off * 0.9),
                                                  P(h - size * 0.22, fy1 - off * 0.9), P(h, fy1)])
        rw = max(1, int(size * 0.16))
        pygame.draw.line(surf, C(ribbon, 1.15), P(0, fy0), P(0, fy1), rw)
        pygame.draw.line(surf, C(ribbon, 0.9), P(-h, fy0 + size * 0.10), P(h, fy0 + size * 0.10),
                         max(1, int(size * 0.10)))

    def _draw_frame_edge(self, gl):
        """相框金边（发光层里画，bloom 会把它晕开）"""
        a = clamp(self.photo_alpha)
        rect = pygame.Rect(0, 0, int(FRAME_HW), int(FRAME_HH))
        rect.center = (int(CENTER[0] * 0.5), int(CENTER[1] * 0.5))
        pygame.draw.rect(gl, (int(255 * a), int(196 * a), int(92 * a)), rect, width=1,
                         border_radius=int(FRAME_ROUND * 0.5))
        pygame.draw.rect(gl, (int(255 * a * 0.35), int(180 * a * 0.35), int(84 * a * 0.35)),
                         rect.inflate(-8, -8), width=1, border_radius=max(2, int(FRAME_ROUND * 0.5) - 3))

    def _draw_star(self, fr):
        px = CENTER[0] + self.star[0]
        py = CENTER[1] + self.star[1]
        persp = FOCAL / max(140.0, FOCAL + self.star[2])
        pulse = 0.86 + 0.14 * math.sin(self.t * 2.4)
        size = max(6.0, self.star_size * persp * pulse)
        d = max(8, int(size * 2.3))
        f = pygame.transform.smoothscale(self.flare, (d, d))
        f = pygame.transform.rotate(f, math.degrees(self.t * 0.5))
        fr.blit(f, (int(px - f.get_width() * 0.5), int(py - f.get_height() * 0.5)),
                special_flags=pygame.BLEND_RGB_ADD)
        # 中间的菱形宝石（上亮下暖，做出立体感）
        g = size * 0.78
        pygame.draw.polygon(fr, (255, 246, 206),
                            [(px, py - g * 1.35), (px + g * 0.8, py),
                             (px, py + g * 1.35), (px - g * 0.8, py)])
        pygame.draw.polygon(fr, (255, 224, 130),
                            [(px - g * 0.8, py), (px, py), (px, py + g * 1.35)])
        pygame.draw.polygon(fr, (255, 255, 252),
                            [(px, py - g * 0.60), (px + g * 0.34, py),
                             (px, py + g * 0.60), (px - g * 0.34, py)])

    # ---------------- 显示 ----------------
    def present(self):
        if self.frame is self.screen:              # 直接画在显示表面上，省一次全屏拷贝
            pygame.display.flip()
            return
        sw, sh = self.screen.get_size()
        if (sw, sh) == (VW, VH):
            self.screen.blit(self.frame, (0, 0))
        else:
            self.screen.blit(pygame.transform.smoothscale(self.frame, (sw, sh)), (0, 0))
        pygame.display.flip()

    def run(self):
        running = True
        if self.screen.get_size() == (VW, VH):
            self.frame = self.screen
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        running = False
                    elif ev.key == pygame.K_SPACE:
                        self.next_segment()
                    elif ev.key == pygame.K_t:
                        self.next_segment("tree")
                    elif ev.key == pygame.K_f:
                        self.next_segment("frame")
                    elif ev.key == pygame.K_c:
                        self.next_segment("cloud")
                    elif ev.key == pygame.K_a:
                        self.auto = not self.auto
                    elif ev.key == pygame.K_h:
                        self.show_hint = not self.show_hint
                    elif ev.key == pygame.K_v:
                        self.show_pip = not self.show_pip
                    elif ev.key == pygame.K_d:
                        self.show_debug = not self.show_debug
                    elif ev.key == pygame.K_s:
                        self.save_cam_snapshot()
                    elif ev.key == pygame.K_g:
                        self._toggle_hand()
                    elif ev.key == pygame.K_r:
                        self._reroll()
                    elif ev.key == pygame.K_p:
                        pygame.image.save(self.frame, f"screenshot_{self.shot:02d}.png")
                        self.shot += 1
                    elif ev.key == pygame.K_F11:
                        pygame.display.toggle_fullscreen()
                elif ev.type == pygame.MOUSEMOTION:
                    self.mouse = ev.pos
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    self.next_segment()

            self.step(dt)
            self.render()
            self.present()

        if getattr(self, "tracker", None):
            self.tracker.stop()
        pygame.quit()

    def save_cam_snapshot(self):
        """存一张当前相机画面（诊断构图），按 S 可以随时存"""
        if not (self.tracker and hasattr(self.tracker, "snapshot")):
            print("[手势] 没有可用的摄像头截图")
            return
        path = os.path.join(APP_DIR, "cam_snapshot.jpg")
        self._snapped = True          # 无论成败都只尝试一次，避免刷屏
        if self.tracker.snapshot(path):
            print(f"[手势] 已保存相机截图：{path}")
        else:
            print("[手势] 没取到相机画面（摄像头被占用或还没就绪）")

    def _toggle_hand(self):
        if not self.hand_on:
            print("[手势] 本次启动未启用手势（用默认参数重新运行即可）")
            return
        if not self.tracker:
            return
        if getattr(self.tracker, "_running", False):
            self.tracker.stop()
            self.hand_lost = 0.0
            self.hand_xy = None
            self.hand_pos = None
            self.hand_grab = self.hand_push = 0.0
            self.hand_drive_t = 99.0
            print("[手势] 已暂停")
        else:
            self.tracker.start()
            print("[手势] 已恢复")

    def _reroll(self):
        self._roll_shapes()
        self.cidx = [pick_color_idx() for _ in range(self.n)]
        self._place_gifts()

    def record(self, outdir, seconds, fps, with_hand=False):
        """离线逐帧渲染（无窗口），交给 ffmpeg 合成视频"""
        os.makedirs(outdir, exist_ok=True)
        self.show_hint = False                     # 录制的成片里不要操作提示
        self.auto = True                           # 离屏渲染要自动演出（否则画面不动）
        if not with_hand:
            self.show_pip = False
        total = int(seconds * fps)
        for i in range(total):
            if with_hand:
                time.sleep(1.0 / fps)           # 等手势线程跟上节奏
            self.step(1.0 / fps)
            self.render()
            pygame.image.save(self.frame, os.path.join(outdir, f"f{i:05d}.png"))
            if i % 60 == 0:
                print(f"  {i}/{total}", flush=True)
        print(f"done: {total} frames -> {outdir}")


# =========================================================================
#  七、照片
# =========================================================================
def make_placeholder_photo(size):
    """没有照片时，程序画一张「雪原黄昏」占位"""
    w, h = size
    surf = pygame.Surface((w, h))
    horizon = int(h * 0.70)
    top, mid, warm = (30, 42, 72), (104, 126, 168), (238, 200, 160)
    for y in range(h):
        if y < horizon * 0.55:
            t = y / max(1.0, horizon * 0.55)
            c = [lerp(top[i], mid[i], t) for i in range(3)]
        elif y < horizon:
            t = (y - horizon * 0.55) / max(1.0, horizon * 0.45)
            c = [lerp(mid[i], warm[i], t) for i in range(3)]
        else:
            t = (y - horizon) / max(1.0, h - horizon)
            c = [lerp(226, 176, t), lerp(234, 190, t), lerp(246, 212, t)]
        pygame.draw.line(surf, tuple(int(clamp(v, 0, 255)) for v in c), (0, y), (w, y))

    sun = make_aura((255, 228, 180), 140, power=2.0)
    surf.blit(sun, (int(w * 0.63) - 140, horizon - 176), special_flags=pygame.BLEND_RGB_ADD)
    pygame.draw.polygon(surf, (78, 96, 132), [(-10, horizon + 4), (w * 0.24, horizon - 76),
                                              (w * 0.48, horizon + 4)])
    pygame.draw.polygon(surf, (66, 84, 118), [(w * 0.32, horizon + 4), (w * 0.60, horizon - 56),
                                              (w * 0.90, horizon + 4)])
    pygame.draw.rect(surf, (214, 224, 238), (0, horizon, w, h - horizon))
    pygame.draw.ellipse(surf, (234, 242, 252), (int(-w * 0.15), horizon - 10, int(w * 1.3), 56))
    for bx, sc, col in ((0.12, 1.0, (44, 58, 88)), (0.23, 0.70, (56, 74, 106)),
                        (0.85, 0.92, (48, 62, 92)), (0.94, 0.60, (62, 80, 112))):
        x, base = w * bx, horizon + 10
        for k in range(3):
            hh = (56 * sc) * (1 - k * 0.20)
            ww = (26 * sc) * (1 - k * 0.18)
            yy = base - k * hh * 0.50
            pygame.draw.polygon(surf, col, [(x - ww, yy), (x + ww, yy), (x, yy - hh)])
        pygame.draw.rect(surf, col, (x - 2, base - 8, 4, 16))
    for _ in range(160):
        pygame.draw.circle(surf, (246, 250, 255),
                           (int(random.uniform(0, w)), int(random.uniform(0, h))),
                           random.choice((1, 1, 2)))
    # 照片质感：四角压暗（白中心 → 暗角的蒙版，乘上去）
    sw, sh = 40, 48
    small = pygame.Surface((sw, sh))
    for y in range(sh):
        for x in range(sw):
            dx = (x - sw / 2) / (sw / 2)
            dy = (y - sh / 2) / (sh / 2)
            d = min(1.0, math.hypot(dx, dy / 1.06) / 1.45)
            v = int(255 * (1.0 - 0.45 * d ** 2.1))
            small.set_at((x, y), (v, v, v))
    surf.blit(pygame.transform.smoothscale(small, (w, h)), (0, 0),
              special_flags=pygame.BLEND_RGB_MULT)
    return surf


def default_photo_path():
    """默认照片：assets/photo.jpg（这里放的是桌面壁纸裁出来的竖版），没有再退回内置插画"""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    for name in ("photo.jpg", "photo.png", "photo.jpeg", "photo.webp"):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def load_photo(path, size):
    """加载照片 → 居中裁切 → 圆角遮罩"""
    w, h = size
    img = None
    if not path:
        path = default_photo_path()
    if path and os.path.isfile(path):
        try:
            img = pygame.image.load(path).convert()
            iw, ih = img.get_size()
            sc = max(w / iw, h / ih)
            img = pygame.transform.smoothscale(img, (max(1, int(iw * sc)), max(1, int(ih * sc))))
            rect = pygame.Rect(0, 0, w, h)
            rect.center = (img.get_width() // 2, img.get_height() // 2)
            img = img.subsurface(rect).copy()
        except Exception as exc:
            print(f"[warn] 照片加载失败({exc})，改用内置插画")
            img = None
    if img is None:
        img = make_placeholder_photo(size)

    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=14)
    out = img.convert_alpha()
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out.convert_alpha()


# =========================================================================
#  八、入口
# =========================================================================
LOG_FILE = None


class _Tee:
    """把 stdout/stderr 同时写到控制台和 run_log.txt（双击运行时也能留证据）"""

    def __init__(self, logfile, stream):
        self.logfile = logfile
        self.stream = stream

    def write(self, data):
        try:
            self.stream.write(data)
            self.stream.flush()
        except Exception:
            pass
        try:
            self.logfile.write(data)
            self.logfile.flush()
        except Exception:
            pass
        return len(data)

    def flush(self):
        for s in (self.stream, self.logfile):
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def log(msg):
    """只写日志文件（进控制台也没关系，但这里刻意只落盘）"""
    if LOG_FILE is not None:
        try:
            LOG_FILE.write(msg + "\n")
            LOG_FILE.flush()
        except Exception:
            pass


_MUTEX = None


def _claim_single_instance(name="MERRY_CHRISTMAS_PARTICLES_SINGLE"):
    """用命名互斥量判断是不是已经有实例在跑（进程退出时自动释放）

    注意：必须用 WinDLL(use_last_error=True) + get_last_error()，
    否则 ctypes 会把 GetLastError 冲掉，判断永远为"没有实例"。
    """
    global _MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
        if not handle:
            return True                      # 创建失败就别拦人
        _MUTEX = handle
        return err != 183                    # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _start_log(path, args):
    """每次运行覆盖写一份 run_log.txt，方便事后排查"""
    global LOG_FILE
    try:
        LOG_FILE = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        LOG_FILE = None
        return
    LOG_FILE.write("=" * 70 + "\n")
    LOG_FILE.write("运行时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    LOG_FILE.write("Python  : " + sys.executable + "\n")
    LOG_FILE.write("参数    : " + " ".join(sys.argv[1:]) + "\n")
    LOG_FILE.write("=" * 70 + "\n")
    sys.stdout = _Tee(LOG_FILE, sys.__stdout__ if sys.__stdout__ else sys.stdout)
    sys.stderr = _Tee(LOG_FILE, sys.__stderr__ if sys.__stderr__ else sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="粒子圣诞树 · MERRY CHRISTMAS")
    ap.add_argument("-n", "--particles", type=int, default=1400, help="粒子数量")
    ap.add_argument("--photo", type=str, default=None, help="放进相框的照片路径")
    ap.add_argument("--no-hand", action="store_true", help="关闭手势控制")
    ap.add_argument("--cam", type=int, default=0, help="摄像头编号")
    ap.add_argument("--hand-model", type=str, default=None, help="hand_landmarker.task 路径")
    ap.add_argument("--hand-video", type=str, default=None, help="用视频文件当手势输入（调试）")
    ap.add_argument("--record-dir", type=str, default=None, help="离屏渲染目录（逐帧 png）")
    ap.add_argument("--seconds", type=float, default=12.0, help="录制时长（秒）")
    ap.add_argument("--fps", type=int, default=30, help="录制帧率")
    ap.add_argument("--seed", type=int, default=7, help="随机种子")
    ap.add_argument("--auto", action="store_true", help="打开自动演出（默认关：只有手势/按键才切形态）")
    ap.add_argument("--keep-auto", action="store_true", help="有手时也不暂停自动演出")
    ap.add_argument("--headless", action="store_true", help="无窗口模式")
    args = ap.parse_args()

    if args.headless or args.record_dir:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        args.headless = True
    _start_log(os.path.join(APP_DIR, "run_log.txt"), args)

    # 单实例保护：摄像头只能被一个程序占用，双击两次的话第二个必然"未就绪"
    if not args.headless and not _claim_single_instance():
        msg = ("已经有一个「粒子圣诞树」在运行了。\n\n"
               "摄像头同一时间只能被一个程序使用，请先关掉那个窗口再启动。\n"
               "（如果你是双击了两次，这个窗口可以直接关掉）")
        print("[启动] " + msg.replace("\n\n", " ").replace("\n", " "), flush=True)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "粒子圣诞树", 0x00000040)
        except Exception:
            pass
        return

    args.hand = not args.no_hand
    random.seed(args.seed)
    app = App(args)
    app.keep_auto = bool(getattr(args, "keep_auto", False))
    app.auto = bool(getattr(args, "auto", False))     # 默认 False：不自动播放
    if args.record_dir:
        app.record(args.record_dir, args.seconds, args.fps, with_hand=bool(args.hand_video))
    else:
        app.run()


if __name__ == "__main__":
    main()
