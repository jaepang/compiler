#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
V37 LP playlist background generator — integrated edition
==========================================================
Approved LP design + four background modes:
  1) solid
  2) image
  3) radial-gradient (grain + optional LP-area underlay)
  4) transparent (LP only, with alpha — for compositing in an editor;
     --alpha-codec prores = ProRes 4444 .mov, vp9 = VP9 .webm about 1/4.5 the size)

User-controlled parameters:
  - duration (HH:MM:SS)
  - dot color (and --dot-opaque: every dot at full opacity instead of its tone alpha)
  - --dark-alpha (transparent only): remap alpha so dark dots composited in linear light
    look like the exact negative of the light-dot render
  - dot alpha / size gain (--dot-alpha-gain, --dot-size-gain; e.g. a dark-dot pass that stays visible on light backgrounds)
  - output resolution
  - FPS
  - seed (blank = random)
  - output filename
  - background mode and its parameters

The approved V37 LP geometry/motion is intentionally fixed.
The script renders the LP at 1920x1080 and lets FFmpeg scale the final
video to the requested 16:9 resolution (default 3840x2160).

Required companion file in the same folder:
  - lp_density_reference.png

Outputs:
  - <output>.mp4 (transparent mode: <output>.mov, or <output>.webm with --alpha-codec vp9)
  - <output_stem>_settings.json
  - <output_stem>_seed.txt

Install:
  pip install numpy opencv-python pycairo

FFmpeg must be installed and available in PATH.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    import cairo
except ImportError:
    cairo = None


SCRIPT_VERSION = "V37-integrated-1.6"

# Fixed design render size. Final output may be 4K or another 16:9 size.
RENDER_W = 1920
RENDER_H = 1080

DEFAULT_DURATION = "00:30:00"
DEFAULT_DOT = "#FFFFFF"
DEFAULT_RESOLUTION = "3840x2160"
DEFAULT_FPS = 30
DEFAULT_OUTPUT = "lp_playlist_bg.mp4"

DEFAULT_BG_MODE = "radial-gradient"
DEFAULT_BG_SOLID = "#FFFFFF"

# Current approved radial-gradient defaults (white dots visibility tuned)
DEFAULT_RADIAL_CENTER = "#2F6BFF"
DEFAULT_RADIAL_OUTER = "#EEF3FF"
DEFAULT_RADIAL_LP_RADIUS = 1.06
DEFAULT_RADIAL_START = 0.28
DEFAULT_RADIAL_END = 2.25
DEFAULT_RADIAL_CURVE = 1.38
DEFAULT_RADIAL_GLOW = 0.02
DEFAULT_RADIAL_GRAIN = 0.055
DEFAULT_RADIAL_UNDERLAY = "#183A9A"
DEFAULT_RADIAL_UNDERLAY_OPACITY = 0.10

# Image-background defaults
DEFAULT_BG_IMAGE_FIT = "cover"
DEFAULT_BG_IMAGE_BLUR = 0.0
DEFAULT_BG_IMAGE_BRIGHTNESS = 1.0
DEFAULT_BG_IMAGE_OPACITY = 1.0
DEFAULT_BG_IMAGE_MATTE = "#FFFFFF"
DEFAULT_BG_IMAGE_OVERLAY = "#000000"
DEFAULT_BG_IMAGE_OVERLAY_OPACITY = 0.0
DEFAULT_BG_IMAGE_FALLBACK = "#FFFFFF"

# Fixed V37 design constants
DESIGN_SCALE = RENDER_W / 1280.0
INNER_R = 92.0 * DESIGN_SCALE
OUTER_R = 366.0 * DESIGN_SCALE
ESCAPE_OUTER_R = 548.0 * DESIGN_SCALE
TRACK_STEP = 4.9 * DESIGN_SCALE
ARC_PITCH = 5.4 * DESIGN_SCALE
MIN_RADIUS = 0.28 * DESIGN_SCALE
MAX_RADIUS = 1.85 * DESIGN_SCALE
MAX_RADIUS_CAP = 2.24 * 0.75 * DESIGN_SCALE
MAIN_SPEED_BASE = 4.15
MOTION_PERIOD_SEC = 10.0

# Approved V37 tuning
BOTTOM_DENSITY_BOOST = 0.12
BOTTOM_LONGTAIL_BOOST = 0.035
MOVING_FRAG_RADIUS_REDUCTION = 0.05
ADJACENT_GAP_RATIO = 0.44

NAMED_COLORS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "blue": "#2F6BFF",
    "흰색": "#FFFFFF",
    "검정": "#000000",
    "화이트": "#FFFFFF",
    "블랙": "#000000",
    "파랑": "#2F6BFF",
    "파란색": "#2F6BFF",
}

BG_MODES = {"solid", "image", "radial-gradient", "transparent"}
ALPHA_CODECS = {"prores": ".mov", "vp9": ".webm"}
IMAGE_FITS = {"cover", "contain", "stretch"}


def parse_duration(text: str) -> float:
    m = re.fullmatch(r"\s*(\d+):([0-5]\d):([0-5]\d)\s*", text)
    if not m:
        raise ValueError("재생 시간은 HH:MM:SS 형식이어야 합니다. 예: 00:30:00")
    h, minute, sec = map(int, m.groups())
    total = h * 3600 + minute * 60 + sec
    if total <= 0:
        raise ValueError("재생 시간은 0초보다 길어야 합니다.")
    return float(total)


def parse_resolution(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX×:]\s*(\d+)\s*", text)
    if not m:
        raise ValueError("해상도는 3840x2160 같은 형식이어야 합니다.")
    w, h = map(int, m.groups())
    if w < 320 or h < 180:
        raise ValueError("해상도가 너무 작습니다.")
    if abs((w / h) - (16 / 9)) > 0.02:
        raise ValueError("현재 디자인은 16:9 해상도만 권장합니다.")
    return w, h


def normalize_hex_color(text: str) -> str:
    s = text.strip()
    lower = s.lower()
    s = NAMED_COLORS.get(lower, NAMED_COLORS.get(s, s))
    if not s.startswith("#"):
        s = "#" + s
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", s):
        raise ValueError("색상은 #RRGGBB 형식이어야 합니다. 예: #FFFFFF")
    return s.upper()


def hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    s = hex_color.lstrip("#")
    return tuple(int(s[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def hex_to_bgr_u8(hex_color: str) -> np.ndarray:
    s = hex_color.lstrip("#")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return np.array([b, g, r], dtype=np.float32)


def smoothstep01(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def wrap_angle(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def lobe_bias(a):
    b1 = np.exp(-0.5 * (wrap_angle(a - 2.34) / 0.55) ** 2)
    b2 = np.exp(-0.5 * (wrap_angle(a + 0.78) / 0.60) ** 2)
    return np.clip(0.58 * b1 + 0.54 * b2, 0.0, 1.0)


def sample_bilinear(img, xs, ys):
    h, w = img.shape
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    x0 = np.clip(x0, 0, w - 1)
    y0 = np.clip(y0, 0, h - 1)
    fx = xs - x0
    fy = ys - y0
    return (
        img[y0, x0] * (1 - fx) * (1 - fy)
        + img[y0, x1] * fx * (1 - fy)
        + img[y1, x0] * (1 - fx) * fy
        + img[y1, x1] * fx * fy
    )


def normalize(v, lo, hi):
    return np.clip((v - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def bottom_bias(a):
    # Image coordinates: +Y is downward, so sin(angle)>0 is lower half.
    return smoothstep01((np.sin(a) + 0.12) / 0.95)


def prompt(default_value, label):
    entered = input(f"{label} [{default_value}]: ").strip()
    return entered if entered else default_value


def load_density_map(script_dir: Path):
    path = script_dir / "lp_density_reference.png"
    if not path.exists():
        raise FileNotFoundError(
            f"필수 파일이 없습니다: {path.name}\n"
            "lp_generator_v37_integrated.py와 lp_density_reference.png를 같은 폴더에 두세요."
        )
    src = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if src is None:
        raise RuntimeError("lp_density_reference.png를 읽지 못했습니다.")

    target = cv2.resize(src.astype(np.float32), (RENDER_W, RENDER_H), interpolation=cv2.INTER_CUBIC)
    fine = cv2.GaussianBlur(target, (0, 0), 2.0 * DESIGN_SCALE)
    macro = cv2.GaussianBlur(target, (0, 0), 8.0 * DESIGN_SCALE)
    return (
        fine,
        macro,
        2.0,
        float(np.percentile(fine, 99.4)),
        2.0,
        float(np.percentile(macro, 99.4)),
    )


def build_rings(seed: int):
    rng = np.random.default_rng(seed)
    rings = []

    for i, rr in enumerate(np.arange(INNER_R, ESCAPE_OUTER_R + 1e-6, TRACK_STEP)):
        N = max(36, int(round(2 * np.pi * rr / ARC_PITCH)))
        phase = rng.uniform(0, 2 * np.pi)
        speed = MAIN_SPEED_BASE * (0.92 + 0.16 * (0.5 + 0.5 * np.sin(i * 0.67)))
        steps_per_period = max(1, int(round(speed * MOTION_PERIOD_SEC * N / 360.0)))

        base_angles = phase + 2 * np.pi * np.arange(N, dtype=np.float32) / N

        rings.append({
            "rr": float(rr),
            "base_angles": base_angles,
            "steps": steps_per_period,
            "keep_seed": rng.random(N).astype(np.float32),
            "keep_seed2": rng.random(N).astype(np.float32),
            "tail_seed": rng.random(N).astype(np.float32),
            "size_jitter": rng.uniform(0.93, 1.17, N).astype(np.float32),
            "dark_jitter": rng.uniform(0.92, 1.08, N).astype(np.float32),
            "escape_phase": rng.uniform(0.0, 2*np.pi, N).astype(np.float32),
            "escape_amp": rng.uniform(0.65, 1.35, N).astype(np.float32),
            "tangential_amp": rng.uniform(0.75, 1.25, N).astype(np.float32),
            "frag_size_jitter": rng.uniform(0.95, 1.18, N).astype(np.float32),
        })

    return rings


def limit_fragment_overlap(x, y, radii, frag, q):
    """V37 roundness protection for moving fragments."""
    if len(radii) < 2:
        return radii

    r = radii.copy()
    r *= (1.0 - MOVING_FRAG_RADIUS_REDUCTION * np.clip(q, 0.0, 1.0))

    order = np.argsort(np.arctan2(y - RENDER_H/2.0, x - RENDER_W/2.0))
    xo = x[order]
    yo = y[order]
    ro = r[order]
    fo = frag[order]

    d_prev = np.hypot(xo - np.roll(xo, 1), yo - np.roll(yo, 1))
    d_next = np.hypot(xo - np.roll(xo, -1), yo - np.roll(yo, -1))
    local_dist = np.minimum(d_prev, d_next)

    allowed = np.maximum(0.22 * DESIGN_SCALE, ADJACENT_GAP_RATIO * local_dist)
    frag_mask = fo > 0.05
    ro[frag_mask] = np.minimum(ro[frag_mask], allowed[frag_mask])

    out = np.empty_like(r)
    out[order] = ro
    return out


# -----------------------------------------------------------------------------
# Background builders
# -----------------------------------------------------------------------------

def fit_image_to_canvas(img: np.ndarray, width: int, height: int, fit: str, matte_bgr: np.ndarray):
    ih, iw = img.shape[:2]

    if fit == "stretch":
        return cv2.resize(img, (width, height), interpolation=cv2.INTER_CUBIC)

    matte = np.asarray(matte_bgr, dtype=np.uint8)
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:] = matte

    scale = max(width / iw, height / ih) if fit == "cover" else min(width / iw, height / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_CUBIC)

    if fit == "cover":
        x0 = (nw - width) // 2
        y0 = (nh - height) // 2
        return resized[y0:y0+height, x0:x0+width].copy()

    x0 = (width - nw) // 2
    y0 = (height - nh) // 2
    canvas[y0:y0+nh, x0:x0+nw] = resized
    return canvas


def build_solid_background(color_hex: str) -> np.ndarray:
    bgr = hex_to_bgr_u8(color_hex).astype(np.uint8)
    frame = np.empty((RENDER_H, RENDER_W, 3), dtype=np.uint8)
    frame[:] = bgr
    return frame


def build_image_background(settings: dict) -> tuple[np.ndarray, bool]:
    """
    Returns (background, used_fallback).
    If path is empty/missing/unreadable, automatically falls back to a solid color.
    """
    path_text = settings.get("bg_image", "").strip()
    fallback = settings["bg_image_fallback"]

    if not path_text:
        print(f"[배경] 이미지 경로가 비어 있어 fallback 단색 {fallback} 사용")
        return build_solid_background(fallback), True

    path = Path(path_text)
    if not path.exists():
        print(f"[배경] 이미지가 없어 fallback 단색 {fallback} 사용: {path}")
        return build_solid_background(fallback), True

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"[배경] 이미지를 읽지 못해 fallback 단색 {fallback} 사용: {path}")
        return build_solid_background(fallback), True

    matte = hex_to_bgr_u8(settings["bg_image_matte"]).astype(np.uint8)
    bg = fit_image_to_canvas(img, RENDER_W, RENDER_H, settings["bg_image_fit"], matte)

    blur_sigma = settings["bg_image_blur"]
    if blur_sigma > 0:
        bg = cv2.GaussianBlur(bg, (0, 0), blur_sigma)

    brightness = settings["bg_image_brightness"]
    if brightness != 1.0:
        bg = np.clip(bg.astype(np.float32) * brightness, 0, 255).astype(np.uint8)

    opacity = settings["bg_image_opacity"]
    if opacity < 1.0:
        matte_frame = np.empty_like(bg)
        matte_frame[:] = matte
        bg = np.clip(
            bg.astype(np.float32) * opacity
            + matte_frame.astype(np.float32) * (1.0 - opacity),
            0,
            255,
        ).astype(np.uint8)

    overlay_opacity = settings["bg_image_overlay_opacity"]
    if overlay_opacity > 0:
        overlay = hex_to_bgr_u8(settings["bg_image_overlay"]).astype(np.float32)
        bg = np.clip(
            bg.astype(np.float32) * (1.0 - overlay_opacity)
            + overlay * overlay_opacity,
            0,
            255,
        ).astype(np.uint8)

    return bg, False


def build_radial_background(settings: dict) -> np.ndarray:
    """Clean radial gradient + grain + optional LP-area underlay."""
    rng = np.random.default_rng(settings["seed"])

    y, x = np.mgrid[0:RENDER_H, 0:RENDER_W].astype(np.float32)
    cx = RENDER_W * 0.5
    cy = RENDER_H * 0.5

    # Normalize both axes by height so the gradient is a true circle in 16:9.
    dx = (x - cx) / RENDER_H
    dy = (y - cy) / RENDER_H
    r = np.sqrt(dx**2 + dy**2)

    c_center = hex_to_bgr_u8(settings["radial_center"])
    c_outer = hex_to_bgr_u8(settings["radial_outer"])
    c_under = hex_to_bgr_u8(settings["radial_underlay"])

    lp_r = settings["radial_lp_radius"] * 0.5
    start_r = lp_r * settings["radial_start"]
    end_r = lp_r * settings["radial_end"]

    t = smoothstep(start_r, end_r, r)
    t = np.clip(t ** max(settings["radial_curve"], 1e-6), 0.0, 1.0)

    img = c_center * (1.0 - t[..., None]) + c_outer * t[..., None]

    glow_strength = settings["radial_glow"]
    if glow_strength > 0:
        ring = np.exp(-((r - lp_r * 0.98) / max(lp_r * 0.20, 1e-6)) ** 2)
        img = (
            img * (1.0 - glow_strength * 0.18 * ring[..., None])
            + c_outer * (glow_strength * 0.18 * ring[..., None])
        )

    underlay_opacity = settings["radial_underlay_opacity"]
    if underlay_opacity > 0:
        inner = smoothstep(lp_r * 0.12, lp_r * 0.30, r)
        outer = 1.0 - smoothstep(lp_r * 1.00, lp_r * 1.55, r)
        underlay_mask = np.clip(inner * outer, 0.0, 1.0)
        alpha = underlay_opacity * underlay_mask[..., None]
        img = img * (1.0 - alpha) + c_under * alpha

    grain_strength = settings["radial_grain"]
    if grain_strength > 0:
        noise = rng.normal(0.0, 1.0, (RENDER_H, RENDER_W, 1)).astype(np.float32)
        noise = cv2.GaussianBlur(noise, (0, 0), 0.30)
        if noise.ndim == 2:
            noise = noise[..., None]
        luminance = img.mean(axis=2, keepdims=True) / 255.0
        grain_mask = 0.70 + 0.30 * (1.0 - luminance)
        img = img * (1.0 + grain_strength * grain_mask * noise)

    return np.clip(img, 0, 255).astype(np.uint8)


def build_background(settings: dict) -> tuple[np.ndarray, bool]:
    mode = settings["bg_mode"]
    if mode == "solid":
        return build_solid_background(settings["bg"]), False
    if mode == "image":
        return build_image_background(settings)
    if mode == "radial-gradient":
        return build_radial_background(settings), False
    if mode == "transparent":
        return None, False
    raise ValueError(f"알 수 없는 배경 모드: {mode}")


# -----------------------------------------------------------------------------
# LP dot renderer (transparent Cairo layer)
# -----------------------------------------------------------------------------

def render_dot_layer(frame_index: int, fps: int, rings, density_data, dot_rgb, opaque: bool = False,
                     alpha_gain: float = 1.0, size_gain: float = 1.0):
    if cairo is None:
        raise RuntimeError("pycairo가 설치되어 있지 않습니다. pip install pycairo")

    fine, macro, fine_lo, fine_hi, macro_lo, macro_hi = density_data

    # Cairo ARGB32 on little-endian systems exposes premultiplied BGRA bytes.
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, RENDER_W, RENDER_H)
    ctx = cairo.Context(surface)

    # Transparent canvas
    ctx.set_operator(cairo.OPERATOR_SOURCE)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    ctx.set_operator(cairo.OPERATOR_OVER)

    t_sec = frame_index / fps
    u = t_sec / MOTION_PERIOD_SEC
    cx, cy = RENDER_W / 2.0, RENDER_H / 2.0

    for ring in rings:
        rr = ring["rr"]
        base_angles = ring["base_angles"]
        N = len(base_angles)
        a_base = base_angles + 2 * np.pi * ring["steps"] * u / N

        src_r = min(rr, OUTER_R)
        sx = cx + src_r * np.cos(a_base)
        sy = cy + src_r * np.sin(a_base)

        fv = sample_bilinear(fine, sx, sy)
        mv = sample_bilinear(macro, sx, sy)
        fn = normalize(fv, fine_lo, fine_hi)
        mn = normalize(mv, macro_lo, macro_hi)
        density = np.clip(0.74 * fn + 0.26 * mn, 0, 1)

        base_radii = MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * (density ** 0.72)
        base_dark = np.clip(0.032 + 0.938 * (density ** 0.58), 0, 0.97)

        if rr <= 325.0 * DESIGN_SCALE:
            mask = np.ones(N, dtype=bool)
            t = np.zeros(N, dtype=np.float32)
        else:
            lb = lobe_bias(a_base)
            wav = (
                8.0 * DESIGN_SCALE * np.sin(3.0*a_base + 0.028*rr)
                + 5.0 * DESIGN_SCALE * np.sin(7.0*a_base - 0.016*rr)
                + 3.0 * DESIGN_SCALE * np.sin(11.0*a_base + 0.009*rr)
            )

            start_r = 323.0 * DESIGN_SCALE + 8.0 * DESIGN_SCALE * lb + wav
            end_r = (
                390.0 * DESIGN_SCALE
                + 110.0 * DESIGN_SCALE * lb
                + 10.0 * DESIGN_SCALE * np.sin(2.0*a_base + 0.01*rr)
                + 5.0 * DESIGN_SCALE * np.sin(5.0*a_base - 0.006*rr)
            )

            t = np.clip((rr - start_r) / np.maximum(end_r - start_r, 1e-3), 0.0, 1.0)

            gloss_anchor = smoothstep01((density - 0.44) / 0.30)
            lower = bottom_bias(a_base)

            base_keep = np.clip(
                (1.0 - 0.74 * (t ** 1.12))
                * (0.88 + 0.30 * gloss_anchor)
                * (1.0 + BOTTOM_DENSITY_BOOST * lower),
                0.14,
                1.0,
            )

            vis_mod = 0.05 * np.sin(2*np.pi*u + 3.0*a_base + 0.012*rr)
            primary_mask = ring["keep_seed"] < np.clip(base_keep + vis_mod, 0.08, 1.0)

            outer_falloff = 1.0 - 0.52 * (t ** 1.35)
            outer_falloff *= (0.92 + 0.08 * gloss_anchor)
            secondary_mask = ring["keep_seed2"] < np.clip(outer_falloff, 0.26, 1.0)

            long_tail_prob = np.clip(
                0.05
                + 0.13 * gloss_anchor
                + 0.10 * (t ** 1.2)
                + BOTTOM_LONGTAIL_BOOST * lower,
                0.05,
                0.30,
            )
            long_tail_mask = ring["tail_seed"] < long_tail_prob
            mask = primary_mask & (secondary_mask | long_tail_mask)

        if not np.any(mask):
            continue

        a_m = a_base[mask]
        t_m = t[mask]
        den_m = density[mask]
        br = base_radii[mask]
        bd = base_dark[mask]

        sj = ring["size_jitter"][mask]
        dj = ring["dark_jitter"][mask]
        eph = ring["escape_phase"][mask]
        eamp = ring["escape_amp"][mask]
        tamp = ring["tangential_amp"][mask]
        fsj = ring["frag_size_jitter"][mask]

        body_amount = 1.0 - smoothstep01((rr - 285.0 * DESIGN_SCALE) / (70.0 * DESIGN_SCALE))
        light_zone = (1.0 - den_m) ** 0.72
        tone_relief = 1.0 - body_amount * 0.25 * light_zone
        size_relief = 1.0 - body_amount * 0.08 * light_zone

        body_fill = body_amount * smoothstep01((0.60 - den_m) / 0.60)
        nongloss_fill = body_amount * smoothstep01((0.48 - den_m) / 0.48)

        tone_boost = 1.0 + 0.29 * body_fill + 0.10 * nongloss_fill
        size_boost = 1.0 + 0.12 * body_fill + 0.05 * nongloss_fill

        frag = smoothstep01((t_m - 0.08) / 0.92)
        gloss_frag = smoothstep01((den_m - 0.42) / 0.32)
        peel_bias = 0.55 + 0.45 * gloss_frag

        cyc1 = 0.5 + 0.5 * np.sin(2*np.pi*u + eph)
        cyc2 = 0.5 + 0.5 * np.sin(4*np.pi*u + 1.3*eph + 0.4*np.sin(3.0*a_m))

        q = (
            frag
            * np.clip(0.24 + 0.52*cyc1 + 0.28*cyc2, 0.0, 1.0)
            * (0.70 + 0.60*gloss_frag)
        )

        ang_lag = q * (0.055 + 0.18*frag + 0.06*gloss_frag) * tamp

        curl = q * gloss_frag * (
            0.035*np.sin(2*np.pi*u + 1.6*eph + 2.4*np.sin(a_m))
            + 0.020*np.sin(4*np.pi*u + 4.5*a_m)
        )

        ang_scatter = q * (
            0.020*np.sin(2*np.pi*u + 1.7*eph)
            + 0.015*np.sin(4*np.pi*u + 5.0*a_m)
            + 0.010*gloss_frag*np.sin(2*np.pi*u + 9.0*a_m)
        )

        radial_push = (
            q
            * peel_bias
            * (4.5*DESIGN_SCALE + 22.0*DESIGN_SCALE*frag)
            * eamp
        )

        radial_scatter = q * (
            2.2*DESIGN_SCALE*np.sin(2*np.pi*u + 0.9*eph)
            + 1.4*DESIGN_SCALE*np.sin(4*np.pi*u - 3.0*a_m)
            + 0.8*DESIGN_SCALE*gloss_frag*np.sin(2*np.pi*u + 7.0*a_m)
        )

        a_draw = a_m - ang_lag + curl + ang_scatter
        rr_draw = rr + radial_push + radial_scatter

        x = cx + rr_draw * np.cos(a_draw)
        y = cy + rr_draw * np.sin(a_draw)

        micro = 0.95 + 0.05 * np.sin(9.5*a_m + 0.013*rr)
        frag_size_boost = 1.0 + 0.07*frag*fsj + 0.05*frag*gloss_frag
        far_size = 1.0 - 0.08 * (t_m ** 1.25)

        radii = (
            br
            * sj
            * (1.00 - 0.03*t_m)
            * micro
            * size_relief
            * size_boost
            * frag_size_boost
            * far_size
        )

        # Glossy-body roundness protection: reduce only the largest dots in dense areas.
        gloss_body = body_amount * smoothstep01((den_m - 0.48) / 0.28)
        local_cap = MAX_RADIUS_CAP * (1.0 - 0.10 * gloss_body)

        knee = local_cap * 0.80
        over = np.maximum(radii - knee, 0.0)
        radii = np.where(radii > knee, knee + 0.55 * over, radii)
        radii = np.minimum(radii, local_cap)
        radii = np.maximum(radii, 0.22 * DESIGN_SCALE)
        radii = radii * size_gain

        # Keep moving fragment circles from touching into oval-looking blobs.
        radii = limit_fragment_overlap(x, y, radii, frag, q)

        frag_tone_boost = 1.0 + 0.11*frag + 0.20*frag*gloss_frag
        far_tone = 1.0 - 0.07 * (t_m ** 1.15)

        alpha_values = (
            bd
            * dj
            * (1.00 - 0.38*t_m)
            * tone_relief
            * tone_boost
            * frag_tone_boost
            * far_tone
        )

        alpha_values *= np.minimum(1.0, np.maximum(radii, 0.15*DESIGN_SCALE) ** 0.60)
        alpha_values = np.clip(alpha_values, 0.010, 0.92)
        if alpha_gain != 1.0:
            alpha_values = np.clip(alpha_values * alpha_gain, 0.010, 1.0)

        for px, py, radius, alpha in zip(x, y, radii, alpha_values):
            if (
                px < -50
                or px > RENDER_W + 50
                or py < -50
                or py > RENDER_H + 50
                or alpha < 0.010
            ):
                continue

            ctx.set_source_rgba(dot_rgb[0], dot_rgb[1], dot_rgb[2], 1.0 if opaque else float(alpha))
            ctx.arc(float(px), float(py), float(radius), 0.0, 2.0 * math.pi)
            ctx.fill()

    surface.flush()
    buf = np.frombuffer(surface.get_data(), dtype=np.uint8).reshape(
        (RENDER_H, surface.get_stride() // 4, 4)
    )
    return np.ascontiguousarray(buf[:, :RENDER_W, :])  # premultiplied BGRA


def composite_premult_bgra_over_bgr(fg_bgra: np.ndarray, bg_bgr: np.ndarray) -> np.ndarray:
    """Composite Cairo premultiplied BGRA over an OpenCV BGR background."""
    alpha = fg_bgra[:, :, 3:4].astype(np.float32) / 255.0
    fg_bgr_premult = fg_bgra[:, :, :3].astype(np.float32)
    bg = bg_bgr.astype(np.float32)
    out = fg_bgr_premult + bg * (1.0 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


def _srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1.0 / 2.4) - 0.055)


# Light dots over a dark background in a linear-light compositor (FilmCraft) show
# srgb(a); dark dots over a light one show 1 - srgb(a') = srgb(1 - a'). Picking
# a' = 1 - lin(1 - srgb(a)) makes the dark pass the exact negative of the light pass.
_DARK_ALPHA_LUT = np.round(
    255.0 * (1.0 - _srgb_to_linear(1.0 - _linear_to_srgb(np.arange(256) / 255.0)))
).astype(np.uint8)


def unpremultiply_bgra(fg_bgra: np.ndarray) -> np.ndarray:
    """Cairo premultiplied BGRA -> straight-alpha BGRA (what FFmpeg/ProRes expect)."""
    alpha = fg_bgra[:, :, 3:4].astype(np.float32)
    color = fg_bgra[:, :, :3].astype(np.float32) * 255.0 / np.maximum(alpha, 1.0)
    out = np.empty_like(fg_bgra)
    out[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
    out[:, :, 3:4] = fg_bgra[:, :, 3:4]
    return out


def resolve_inputs(args):
    duration = args.duration or prompt(DEFAULT_DURATION, "재생 시간 HH:MM:SS")
    resolution = args.resolution or prompt(DEFAULT_RESOLUTION, "출력 해상도")
    fps_text = str(args.fps) if args.fps is not None else prompt(str(DEFAULT_FPS), "FPS")
    output = args.output or prompt(DEFAULT_OUTPUT, "출력 파일명")
    dot = args.dot or prompt(DEFAULT_DOT, "점 색 #RRGGBB")
    bg_mode = args.bg_mode or prompt(DEFAULT_BG_MODE, "배경 모드 (solid / image / radial-gradient / transparent)")

    if args.seed is None:
        seed_text = input("Seed [Enter = 랜덤 생성]: ").strip()
        seed = int(seed_text) if seed_text else secrets.randbits(32)
    else:
        seed = int(args.seed)

    duration_sec = parse_duration(duration)
    out_w, out_h = parse_resolution(resolution)
    fps = int(fps_text)

    if fps < 1 or fps > 120:
        raise ValueError("FPS는 1~120 범위로 입력하세요.")

    dot = normalize_hex_color(dot)
    if args.dot_alpha_gain <= 0 or args.dot_size_gain <= 0:
        raise ValueError("dot_alpha_gain / dot_size_gain은 0보다 커야 합니다.")
    bg_mode = bg_mode.strip().lower()
    if args.alpha_codec not in ALPHA_CODECS:
        raise ValueError("--alpha-codec는 prores / vp9 중 하나여야 합니다.")
    if args.dark_alpha and bg_mode.strip().lower() != "transparent":
        raise ValueError("--dark-alpha는 transparent 모드에서만 씁니다.")
    if bg_mode not in BG_MODES:
        raise ValueError("배경 모드는 solid / image / radial-gradient / transparent 중 하나여야 합니다.")

    settings = {
        "duration": duration,
        "duration_sec": duration_sec,
        "out_w": out_w,
        "out_h": out_h,
        "resolution": f"{out_w}x{out_h}",
        "fps": fps,
        "seed": seed,
        "dot": dot,
        "dot_opaque": bool(args.dot_opaque),
        "dot_alpha_gain": float(args.dot_alpha_gain),
        "dot_size_gain": float(args.dot_size_gain),
        "dark_alpha": bool(args.dark_alpha),
        "alpha_codec": args.alpha_codec,
        "bg_mode": bg_mode,
    }

    if bg_mode == "solid":
        settings["bg"] = normalize_hex_color(args.bg or prompt(DEFAULT_BG_SOLID, "배경색 #RRGGBB"))

    elif bg_mode == "image":
        # Empty/missing path is allowed: builder will use fallback solid color.
        bg_image = args.bg_image if args.bg_image is not None else input("배경 이미지 경로 [비우면 fallback 단색]: ").strip()
        fit = (args.bg_image_fit or DEFAULT_BG_IMAGE_FIT).strip().lower()
        if fit not in IMAGE_FITS:
            raise ValueError("bg_image_fit은 cover / contain / stretch 중 하나여야 합니다.")

        blur = float(args.bg_image_blur if args.bg_image_blur is not None else DEFAULT_BG_IMAGE_BLUR)
        brightness = float(args.bg_image_brightness if args.bg_image_brightness is not None else DEFAULT_BG_IMAGE_BRIGHTNESS)
        opacity = float(args.bg_image_opacity if args.bg_image_opacity is not None else DEFAULT_BG_IMAGE_OPACITY)
        matte = normalize_hex_color(args.bg_image_matte or DEFAULT_BG_IMAGE_MATTE)
        overlay = normalize_hex_color(args.bg_image_overlay or DEFAULT_BG_IMAGE_OVERLAY)
        overlay_opacity = float(
            args.bg_image_overlay_opacity
            if args.bg_image_overlay_opacity is not None
            else DEFAULT_BG_IMAGE_OVERLAY_OPACITY
        )
        fallback = normalize_hex_color(args.bg_image_fallback or DEFAULT_BG_IMAGE_FALLBACK)

        if blur < 0:
            raise ValueError("bg_image_blur는 0 이상이어야 합니다.")
        if brightness <= 0:
            raise ValueError("bg_image_brightness는 0보다 커야 합니다.")
        if not (0.0 <= opacity <= 1.0):
            raise ValueError("bg_image_opacity는 0~1 범위여야 합니다.")
        if not (0.0 <= overlay_opacity <= 1.0):
            raise ValueError("bg_image_overlay_opacity는 0~1 범위여야 합니다.")

        settings.update({
            "bg_image": bg_image,
            "bg_image_fit": fit,
            "bg_image_blur": blur,
            "bg_image_brightness": brightness,
            "bg_image_opacity": opacity,
            "bg_image_matte": matte,
            "bg_image_overlay": overlay,
            "bg_image_overlay_opacity": overlay_opacity,
            "bg_image_fallback": fallback,
        })

    elif bg_mode == "radial-gradient":
        settings.update({
            "radial_center": normalize_hex_color(args.radial_center or DEFAULT_RADIAL_CENTER),
            "radial_outer": normalize_hex_color(args.radial_outer or DEFAULT_RADIAL_OUTER),
            "radial_lp_radius": float(args.radial_lp_radius if args.radial_lp_radius is not None else DEFAULT_RADIAL_LP_RADIUS),
            "radial_start": float(args.radial_start if args.radial_start is not None else DEFAULT_RADIAL_START),
            "radial_end": float(args.radial_end if args.radial_end is not None else DEFAULT_RADIAL_END),
            "radial_curve": float(args.radial_curve if args.radial_curve is not None else DEFAULT_RADIAL_CURVE),
            "radial_glow": float(args.radial_glow if args.radial_glow is not None else DEFAULT_RADIAL_GLOW),
            "radial_grain": float(args.radial_grain if args.radial_grain is not None else DEFAULT_RADIAL_GRAIN),
            "radial_underlay": normalize_hex_color(args.radial_underlay or DEFAULT_RADIAL_UNDERLAY),
            "radial_underlay_opacity": float(
                args.radial_underlay_opacity
                if args.radial_underlay_opacity is not None
                else DEFAULT_RADIAL_UNDERLAY_OPACITY
            ),
        })

        if settings["radial_lp_radius"] <= 0:
            raise ValueError("radial_lp_radius는 0보다 커야 합니다.")
        if settings["radial_end"] <= settings["radial_start"]:
            raise ValueError("radial_end는 radial_start보다 커야 합니다.")
        if settings["radial_curve"] <= 0:
            raise ValueError("radial_curve는 0보다 커야 합니다.")
        if settings["radial_glow"] < 0:
            raise ValueError("radial_glow는 0 이상이어야 합니다.")
        if settings["radial_grain"] < 0:
            raise ValueError("radial_grain는 0 이상이어야 합니다.")
        if not (0.0 <= settings["radial_underlay_opacity"] <= 1.0):
            raise ValueError("radial_underlay_opacity는 0~1 범위여야 합니다.")

    # Transparent mode needs an alpha-capable container/codec: ProRes 4444 .mov or VP9 .webm.
    suffix = ALPHA_CODECS[args.alpha_codec] if bg_mode == "transparent" else ".mp4"
    out_path = Path(output)
    if out_path.suffix.lower() != suffix:
        out_path = out_path.with_suffix(suffix)
    settings["output"] = out_path

    return settings


def save_settings(settings, output_path: Path, used_fallback: bool):
    base = output_path.with_suffix("")
    json_path = Path(str(base) + "_settings.json")
    seed_path = Path(str(base) + "_seed.txt")

    payload = {
        "generator_version": SCRIPT_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "duration": settings["duration"],
        "duration_seconds": settings["duration_sec"],
        "dot_color": settings["dot"],
        "dot_opaque": settings["dot_opaque"],
        "dot_alpha_gain": settings["dot_alpha_gain"],
        "dot_size_gain": settings["dot_size_gain"],
        "dark_alpha": settings["dark_alpha"],
        "background_mode": settings["bg_mode"],
        "output_resolution": settings["resolution"],
        "render_resolution": f"{RENDER_W}x{RENDER_H}",
        "fps": settings["fps"],
        "seed": int(settings["seed"]),
        "output_file": str(output_path.name),
    }

    if settings["bg_mode"] == "solid":
        payload["background"] = {"mode": "solid", "color": settings["bg"]}
    elif settings["bg_mode"] == "image":
        payload["background"] = {
            "mode": "image",
            "image": settings["bg_image"],
            "fit": settings["bg_image_fit"],
            "blur": settings["bg_image_blur"],
            "brightness": settings["bg_image_brightness"],
            "opacity": settings["bg_image_opacity"],
            "matte": settings["bg_image_matte"],
            "overlay_color": settings["bg_image_overlay"],
            "overlay_opacity": settings["bg_image_overlay_opacity"],
            "fallback_color": settings["bg_image_fallback"],
            "fallback_used": bool(used_fallback),
        }
    elif settings["bg_mode"] == "radial-gradient":
        payload["background"] = {
            "mode": "radial-gradient",
            "center_color": settings["radial_center"],
            "outer_color": settings["radial_outer"],
            "lp_radius_ratio": settings["radial_lp_radius"],
            "gradient_start_ratio": settings["radial_start"],
            "gradient_end_ratio": settings["radial_end"],
            "gradient_curve": settings["radial_curve"],
            "glow_strength": settings["radial_glow"],
            "grain_strength": settings["radial_grain"],
            "underlay_color": settings["radial_underlay"],
            "underlay_opacity": settings["radial_underlay_opacity"],
        }
    elif settings["bg_mode"] == "transparent":
        payload["background"] = {
            "mode": "transparent",
            "codec": "prores_ks 4444 (yuva444p10le)" if settings["alpha_codec"] == "prores" else "libvpx-vp9 crf20 realtime cpu-used 5, 1s GOP (yuva420p)",
        }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    seed_path.write_text(str(settings["seed"]) + "\n", encoding="utf-8")
    return json_path, seed_path


def start_ffmpeg(output_path: Path, out_w: int, out_h: int, fps: int, transparent: bool = False,
                 alpha_codec: str = "prores"):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg를 찾을 수 없습니다. FFmpeg를 설치하고 PATH에 추가하세요.")

    vf = f"scale={out_w}:{out_h}:flags=lanczos"
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel", "warning",
        "-f", "rawvideo",
        "-pix_fmt", "bgra" if transparent else "bgr24",
        "-s", f"{RENDER_W}x{RENDER_H}",
        "-r", str(fps),
        "-i", "-",
        "-an",
        "-vf", vf,
    ]
    if transparent and alpha_codec == "vp9":
        # FilmCraft decodes VP9 alpha. The default "good" deadline encodes at ~4 fps and
        # becomes the bottleneck; realtime/cpu-used 5 keeps up (~12 fps) at ~1/4.5 of ProRes.
        cmd += [
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-b:v", "0",
            "-crf", "20",
            "-row-mt", "1",
            "-tile-columns", "2",
            "-deadline", "realtime",
            "-cpu-used", "5",
            "-g", str(fps),  # 1 s keyframes: FilmCraft seeks took up to 6 s without this
        ]
    elif transparent:
        cmd += [
            "-c:v", "prores_ks",
            "-profile:v", "4444",
            "-pix_fmt", "yuva444p10le",
            "-alpha_bits", "16",
            "-vendor", "apl0",
        ]
    else:
        cmd += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]
    cmd.append(str(output_path))
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, bufsize=10**7)


def format_eta(seconds):
    if not np.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def print_settings(settings, total_frames, used_fallback):
    print("\n--- 렌더 설정 ---")
    print(f"시간       : {settings['duration']}")
    print(f"점 색      : {settings['dot']}" + (" (불투명)" if settings["dot_opaque"] else ""))
    print(f"점 배율    : alpha x{settings['dot_alpha_gain']} / size x{settings['dot_size_gain']}")
    if settings["dark_alpha"]:
        print("dark alpha : 선형광 합성용 어두운 점 보정")
    print(f"배경 모드  : {settings['bg_mode']}")

    if settings["bg_mode"] == "solid":
        print(f"배경색     : {settings['bg']}")
    elif settings["bg_mode"] == "image":
        print(f"배경 이미지: {settings['bg_image'] or '(없음)'}")
        print(f"fit/blur   : {settings['bg_image_fit']} / {settings['bg_image_blur']}")
        print(f"brightness : {settings['bg_image_brightness']}")
        print(f"opacity    : {settings['bg_image_opacity']}")
        print(f"overlay    : {settings['bg_image_overlay']} @ {settings['bg_image_overlay_opacity']}")
        if used_fallback:
            print(f"fallback   : {settings['bg_image_fallback']} (사용됨)")
    elif settings["bg_mode"] == "radial-gradient":
        print(f"중심/외곽  : {settings['radial_center']} -> {settings['radial_outer']}")
        print(f"range/curve: {settings['radial_start']} -> {settings['radial_end']} / {settings['radial_curve']}")
        print(f"grain      : {settings['radial_grain']}")
        print(f"underlay   : {settings['radial_underlay']} @ {settings['radial_underlay_opacity']}")
    elif settings["bg_mode"] == "transparent":
        codec = "ProRes 4444 .mov" if settings["alpha_codec"] == "prores" else "VP9 .webm"
        print(f"배경       : 없음 (알파 채널, {codec})")

    print(f"출력       : {settings['resolution']} / {settings['fps']} fps")
    print(f"Seed       : {settings['seed']}")
    print(f"프레임 수  : {total_frames:,}")
    print(f"파일       : {settings['output']}")
    print("-----------------\n")


def main():
    parser = argparse.ArgumentParser(description="V37 LP 장시간 배경 영상 생성기 (통합 배경 모드)")
    parser.add_argument("--duration", help="HH:MM:SS")
    parser.add_argument("--dot", help="#RRGGBB")
    parser.add_argument("--dot-alpha-gain", type=float, default=1.0, help="점 alpha 배율 (1 초과면 상한 0.92 -> 1.0)")
    parser.add_argument("--dot-size-gain", type=float, default=1.0, help="점 반지름 배율")
    parser.add_argument("--alpha-codec", default="prores", help="transparent 출력 코덱: prores(.mov, 큼) / vp9(.webm, 약 1/4.5)")
    parser.add_argument("--dark-alpha", action="store_true",
                        help="transparent 전용. 어두운 점이 선형광 편집기에서 흰 점 렌더의 정확한 반전으로 보이게 alpha 를 보정")
    parser.add_argument("--dot-opaque", action="store_true", help="점을 전부 불투명(alpha 1)으로 그린다. 기본은 점마다 톤 alpha(0.01~0.92)")
    parser.add_argument("--resolution", help="예: 3840x2160")
    parser.add_argument("--fps", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", help="output.mp4")

    parser.add_argument("--bg-mode", help="solid / image / radial-gradient / transparent")
    parser.add_argument("--bg", help="solid 배경색 #RRGGBB")

    parser.add_argument("--bg-image", help="배경 이미지 경로")
    parser.add_argument("--bg-image-fit", help="cover / contain / stretch")
    parser.add_argument("--bg-image-blur", type=float)
    parser.add_argument("--bg-image-brightness", type=float)
    parser.add_argument("--bg-image-opacity", type=float)
    parser.add_argument("--bg-image-matte", help="#RRGGBB")
    parser.add_argument("--bg-image-overlay", help="#RRGGBB")
    parser.add_argument("--bg-image-overlay-opacity", type=float)
    parser.add_argument("--bg-image-fallback", help="#RRGGBB")

    parser.add_argument("--radial-center", help="#RRGGBB")
    parser.add_argument("--radial-outer", help="#RRGGBB")
    parser.add_argument("--radial-lp-radius", type=float)
    parser.add_argument("--radial-start", type=float)
    parser.add_argument("--radial-end", type=float)
    parser.add_argument("--radial-curve", type=float)
    parser.add_argument("--radial-glow", type=float)
    parser.add_argument("--radial-grain", type=float)
    parser.add_argument("--radial-underlay", help="#RRGGBB")
    parser.add_argument("--radial-underlay-opacity", type=float)

    args = parser.parse_args()

    if cairo is None:
        print("ERROR: pycairo가 필요합니다.")
        print("설치: pip install pycairo")
        sys.exit(1)

    try:
        settings = resolve_inputs(args)
    except Exception as e:
        print(f"입력 오류: {e}")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    density_data = load_density_map(script_dir)
    dot_rgb = hex_to_rgb01(settings["dot"])
    rings = build_rings(settings["seed"])
    bg_frame, used_fallback = build_background(settings)

    total_frames = int(round(settings["duration_sec"] * settings["fps"]))
    settings["output"].parent.mkdir(parents=True, exist_ok=True)

    print_settings(settings, total_frames, used_fallback)
    json_path, seed_path = save_settings(settings, settings["output"], used_fallback)
    transparent = settings["bg_mode"] == "transparent"
    proc = start_ffmpeg(settings["output"], settings["out_w"], settings["out_h"], settings["fps"], transparent,
                        settings["alpha_codec"])

    if proc.stdin is None:
        raise RuntimeError("FFmpeg stdin을 열지 못했습니다.")

    started = time.time()
    last_print = started

    try:
        for i in range(total_frames):
            dots_bgra = render_dot_layer(i, settings["fps"], rings, density_data, dot_rgb, settings["dot_opaque"],
                                         settings["dot_alpha_gain"], settings["dot_size_gain"])
            if transparent:
                frame = unpremultiply_bgra(dots_bgra)
                if settings["dark_alpha"]:
                    frame[:, :, 3] = _DARK_ALPHA_LUT[frame[:, :, 3]]
            else:
                frame = composite_premult_bgra_over_bgr(dots_bgra, bg_frame)
            proc.stdin.write(frame.tobytes())

            now = time.time()
            if now - last_print >= 2.0 or i == total_frames - 1:
                done = i + 1
                elapsed = now - started
                rate = done / max(elapsed, 1e-6)
                eta = (total_frames - done) / rate if rate > 0 else float("inf")
                pct = done / total_frames * 100.0
                print(
                    f"\r{pct:6.2f}%  "
                    f"{done:,}/{total_frames:,} frames  "
                    f"{rate:5.2f} fps  "
                    f"ETA {format_eta(eta)}",
                    end="",
                    flush=True,
                )
                last_print = now

    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다.")
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        sys.exit(130)

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    return_code = proc.wait()
    print()

    if return_code != 0:
        raise RuntimeError(f"FFmpeg가 오류 코드 {return_code}로 종료되었습니다.")

    print("\n완료")
    print(f"영상 : {settings['output']}")
    print(f"설정 : {json_path}")
    print(f"Seed : {seed_path}")


if __name__ == "__main__":
    main()
