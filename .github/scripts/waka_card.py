"""WakaTime AI 코딩 카드 → 풀폭 밴드 SVG 렌더러 (투명 배경 · dark/light 테마).

단일 카드 대신 너비 840 풀폭 밴드 6장으로 분리한다. 각 밴드는 배경 투명이라
README 에서 <picture> 로 세로 스택하면 정렬이 깨지지 않는다.
모든 막대/링/히트맵 기하값은 waka_data.collect() 런타임 데이터에서 계산한다.

밴드: header / hero / week / rhythm / stack / heatmap
테마: dark / light  (밴드별 *-dark.svg, *-light.svg 생성 → <picture> 전환)
"""
from __future__ import annotations

import datetime as dt
import html
import math
import os
from dataclasses import dataclass

from waka_data import collect, WakaData

WIDTH = 840
PAD = 18
INNER = WIDTH - PAD * 2
PAD_IN = 18          # 카드 내부 패딩
GAP = 14             # 영역 카드 세로 간격
HGAP = 16            # 좌우 카드 간격
TOP = 7              # 밴드 상/하 여백
HALF = (INNER - HGAP) / 2

SANS = "'Space Grotesk','Segoe UI',system-ui,-apple-system,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace"

# 강조색은 두 테마 공용 (밝/어두운 배경 모두에서 충분히 대비)
BLUE = "#3b82f6"
BLUE_D = "#58A6FF"
CLAUDE = "#D97757"
CLAUDE2 = "#E8A06F"
PURPLE = "#A371F7"
PURPLE2 = "#8B6FC9"
GREEN = "#2EA043"
RED = "#e5484d"


@dataclass
class Theme:
    key: str
    foreground: str
    foreground2: str
    sub: str
    mute: str
    faint: str
    card_bg: str
    card_stroke: str
    panel: str
    panel_stroke: str
    track: str
    divider: str
    blue: str
    heat: tuple


DARK = Theme(
    key="dark",
    foreground="#f0f6fc", foreground2="#c9d1d9", sub="#8b949e", mute="#7d8590", faint="#5b6470",
    card_bg="#0d1117", card_stroke="#20262e",
    panel="#161b22", panel_stroke="#283039", track="#1c222b", divider="#222a33",
    blue=BLUE_D,
    heat=("#161b22", "#0d2d4a", "#15487f", "#2f6fc0", "#58A6FF"),
)
LIGHT = Theme(
    key="light",
    foreground="#1f2328", foreground2="#3a424b", sub="#57606a", mute="#6e7781", faint="#9aa3ad",
    card_bg="#ffffff", card_stroke="#d0d7de",
    panel="#f4f6f8", panel_stroke="#d8dee4", track="#e7ebef", divider="#d8dee4",
    blue=BLUE,
    heat=("#ebedf0", "#bcd7f5", "#7fb1ec", "#4a8de0", "#1f6fdb"),
)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_count(number: float) -> str:
    number = float(number)
    if number >= 1e9:
        return f"{number / 1e9:.2f}B"
    if number >= 1e6:
        return f"{number / 1e6:.1f}M"
    if number >= 1e3:
        return f"{number / 1e3:.1f}K"
    return f"{int(number)}"


def fmt_money(number: float) -> str:
    return "$" + f"{number:,.0f}"


def fmt_delta(percent: float, theme: Theme) -> tuple[str, str]:
    arrow = "▲" if percent >= 0 else "▼"
    color = GREEN if percent >= 0 else RED
    return f"{arrow} {abs(percent):.0f}%", color


class Canvas:
    def __init__(self, theme: Theme):
        self.theme = theme
        self.parts: list[str] = []

    def add(self, markup: str):
        self.parts.append(markup)

    def text(self, x, y, value, size=12, color=None, weight=400, family=MONO,
             anchor="start", spacing=None, upper=False):
        color = color or self.theme.foreground
        letter = f' letter-spacing="{spacing}"' if spacing else ""
        transform = ' style="text-transform:uppercase"' if upper else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{letter}{transform}>'
            f'{esc(value)}</text>'
        )

    def rect(self, x, y, width, height, fill, radius=0, stroke=None, stroke_width=1):
        stroke_markup = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0, width):.1f}" '
                 f'height="{height:.1f}" rx="{radius}" fill="{fill}"{stroke_markup}/>')

    def bar(self, x, y, width, height, percent, fill, radius=None):
        radius = height / 2 if radius is None else radius
        self.rect(x, y, width, height, self.theme.track, radius)
        filled = max(0.0, min(1.0, percent / 100.0)) * width
        if filled > 0:
            self.rect(x, y, filled, height, fill, radius)

    def card(self, x, y, width, height):
        self.rect(x, y, width, height, self.theme.card_bg, radius=14, stroke=self.theme.card_stroke)

    def ctitle(self, x, y, title, right=None, right_x=None):
        self.text(x, y, title, 11, self.theme.blue, 600, MONO, spacing="1.3", upper=True)
        if right is not None and right_x is not None:
            self.text(right_x, y, right, 10, self.theme.mute, 500, MONO, anchor="end")

    def section(self, y, title, right=None, x=PAD, width=INNER):
        self.text(x, y, title, 12, self.theme.blue, 600, MONO, spacing="1.4", upper=True)
        title_end = x + 9 + len(title) * 8.2
        line_end = x + width - (96 if right else 0)
        self.add(f'<line x1="{title_end:.0f}" y1="{y - 4:.0f}" x2="{line_end:.0f}" '
                 f'y2="{y - 4:.0f}" stroke="{self.theme.divider}"/>')
        if right:
            self.text(x + width, y, right, 11, self.theme.mute, 500, MONO, anchor="end")
        return y + 22


def linear(canvas: Canvas, gid, color0, color1, horizontal=True):
    x2, y2 = (1, 0) if horizontal else (0, 1)
    canvas.add(f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
               f'<stop offset="0" stop-color="{color0}"/>'
               f'<stop offset="1" stop-color="{color1}"/></linearGradient>')


def gradients(canvas: Canvas):
    canvas.add("<defs>")
    linear(canvas, "g_claude", CLAUDE, CLAUDE2)
    linear(canvas, "g_blue", canvas.theme.blue, "#79b8ff")
    linear(canvas, "g_purple", PURPLE2, PURPLE)
    linear(canvas, "g_ring", CLAUDE, CLAUDE2, horizontal=False)
    linear(canvas, "g_peak", canvas.theme.blue, PURPLE, horizontal=False)
    canvas.add("</defs>")


def wrap(canvas: Canvas, height: float) -> str:
    body = "\n".join(canvas.parts)
    return (
        f'<svg width="{WIDTH}" height="{height:.0f}" viewBox="0 0 {WIDTH} {height:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="{SANS}">\n{body}\n</svg>\n'
    )


# ===================== BANDS =====================

def band_header(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    h = 72
    canvas.card(PAD, TOP, INNER, h)
    ix = PAD + PAD_IN
    av = 46
    avy = TOP + (h - av) / 2
    canvas.rect(ix, avy, av, av, "url(#g_blue)", radius=13)
    canvas.text(ix + av / 2, avy + 30, "R", 20, "#fff", 700, SANS, anchor="middle")
    tx = ix + av + 14
    canvas.text(tx, TOP + 30, "devRavit", 22, theme.foreground, 700, SANS, spacing="-0.2")
    canvas.text(tx, TOP + 49, f"WakaTime · {data.range_text} · {data.total_text} coded",
                12, theme.mute, 500, MONO)
    right = PAD + INNER - PAD_IN

    def badge(x, label, fill, border, dot=None, emoji=None):
        width = 24 + len(label) * 7.1 + (16 if dot or emoji else 0)
        top = TOP + 13
        canvas.rect(x - width, top, width, 26, fill, radius=13, stroke=border)
        cursor = x - width + 13
        baseline = top + 17
        if dot:
            canvas.add(f'<circle cx="{cursor}" cy="{top + 13:.0f}" r="3.5" fill="{dot}"/>')
            cursor += 11
        if emoji:
            canvas.text(cursor - 2, baseline, emoji, 12, theme.foreground, 400, SANS)
            cursor += 16
        canvas.text(cursor, baseline, label, 11, theme.foreground2, 600, MONO)
        return x - width - 9

    badge_bg = "#11243b" if theme.key == "dark" else "#dbeafe"
    nxt = badge(right, "AI-Native", badge_bg, theme.blue, dot=theme.blue)
    nxt = badge(nxt, "Night Owl", theme.panel, theme.panel_stroke, emoji="🦉")
    streak_bg = "#2a1a10" if theme.key == "dark" else "#fbe9df"
    badge(nxt, f"{data.streak}d streak", streak_bg, CLAUDE, emoji="🔥")
    canvas.text(right, TOP + 54, f"avg {data.daily_avg_text} / day", 11, theme.faint, 500, MONO, anchor="end")
    return TOP + h


def band_hero(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = TOP
    hero_h = 132
    # 히어로(AI 링)는 배경 없음 — 투명
    cx, cy, r = PAD + PAD_IN + 52, y + hero_h / 2, 52
    circ = 2 * math.pi * r
    offset = circ * (1 - data.ai_coding_pct / 100.0)
    canvas.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="{theme.track}" stroke-width="13"/>')
    canvas.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="url(#g_ring)" stroke-width="13" '
               f'stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}" '
               f'transform="rotate(-90 {cx} {cy:.0f})"/>')
    canvas.text(cx, cy - 2, f"{data.ai_coding_pct:.0f}", 34, theme.foreground, 700, SANS,
                anchor="middle", spacing="-1")
    canvas.text(cx, cy + 16, "% AI-DRIVEN", 9, CLAUDE2, 600, MONO, anchor="middle", spacing="1")

    bx = PAD + PAD_IN + 150
    bright = PAD + INNER - PAD_IN
    bw = bright - bx
    canvas.text(bx, y + 28, "거의 모든 코드를 Claude와 함께 작성했어요", 16, theme.foreground, 600, SANS)
    total = max(1, data.ai_lines + data.human_lines)
    ai_pct = data.ai_lines / total * 100
    human_pct = data.human_lines / total * 100
    row = y + 54
    canvas.add(f'<circle cx="{bx + 4}" cy="{row - 4}" r="4" fill="{CLAUDE}"/>')
    canvas.text(bx + 16, row, "AI", 13, theme.sub, 500, MONO)
    canvas.text(bx + 42, row, fmt_count(data.ai_lines), 15, theme.foreground, 700, SANS)
    canvas.text(bright, row, f"{ai_pct:.0f}%", 13, theme.foreground2, 600, MONO, anchor="end")
    canvas.bar(bx, row + 8, bw, 9, ai_pct, "url(#g_claude)", radius=5)
    row += 36
    canvas.add(f'<circle cx="{bx + 4}" cy="{row - 4}" r="4" fill="{GREEN}"/>')
    canvas.text(bx + 16, row, "Human", 13, theme.sub, 500, MONO)
    canvas.text(bx + 64, row, fmt_count(data.human_lines), 15, theme.foreground, 700, SANS)
    canvas.text(bright, row, f"{human_pct:.0f}%", 13, theme.mute, 600, MONO, anchor="end")
    canvas.bar(bx, row + 8, bw, 9, human_pct, GREEN, radius=5)

    y += hero_h + GAP
    tiles = [
        (fmt_count(data.ai_lines), "AI line changes", None),
        (fmt_count(data.tokens_in), f"tokens in · {fmt_count(data.tokens_out)} out", "B"),
        (fmt_money(data.est_cost), "est. cost · 7 days", None),
        (f"{data.lines_per_prompt:.0f}", "lines / prompt", None),
    ]
    tile_gap = 12
    tile_w = (INNER - tile_gap * 3) / 4
    for index, (value, label, suffix) in enumerate(tiles):
        tx = PAD + index * (tile_w + tile_gap)
        canvas.card(tx, y, tile_w, 72)
        canvas.text(tx + PAD_IN, y + 32, value, 25, theme.foreground, 700, SANS, spacing="-0.5")
        if suffix:
            canvas.text(tx + PAD_IN + len(value) * 15.5, y + 32, suffix, 16, theme.blue, 700, SANS)
        canvas.text(tx + PAD_IN, y + 54, label, 11, theme.mute, 500, MONO)
    return y + 72


def band_week(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = TOP
    wow_h = 130
    canvas.card(PAD, y, INNER, wow_h)
    ix = PAD + PAD_IN
    iright = PAD + INNER - PAD_IN
    canvas.ctitle(ix, y + 24, "THIS WEEK vs LAST WEEK",
                  right=f"{data.wow_time[0] / 3600:.0f}h vs {data.wow_time[1] / 3600:.0f}h", right_x=iright)
    delta, color = fmt_delta(data.wow_time[2], theme)
    canvas.text(ix, y + 50, delta, 22, color, 700, SANS, spacing="-0.5")
    canvas.text(ix + len(delta) * 14 + 12, y + 50, "coding time", 12, theme.sub, 500, MONO)
    rows = [
        ("Coding time", data.wow_time[0] / 3600, data.wow_time[1] / 3600, data.wow_time[2], "h", theme.blue),
        ("AI lines", data.wow_ai_lines[0], data.wow_ai_lines[1], data.wow_ai_lines[2], "#", CLAUDE),
        ("Tokens", data.wow_tokens[0], data.wow_tokens[1], data.wow_tokens[2], "t", PURPLE),
    ]
    inner_w = INNER - 2 * PAD_IN
    col_w = (inner_w - 2 * 20) / 3
    ry = y + 74
    for index, (label, current, previous, percent, kind, color) in enumerate(rows):
        rx = ix + index * (col_w + 20)
        current_text = f"{current:.0f}h" if kind == "h" else fmt_count(current)
        previous_text = f"{previous:.0f}h" if kind == "h" else fmt_count(previous)
        delta_text, delta_color = fmt_delta(percent, theme)
        canvas.text(rx, ry, label, 11, theme.foreground2, 500, MONO)
        canvas.text(rx + col_w, ry, delta_text, 11, delta_color, 600, MONO, anchor="end")
        canvas.bar(rx, ry + 8, col_w, 6, 100, color, radius=3)
        ratio = (previous / current * 100) if current else 0
        canvas.bar(rx, ry + 18, col_w, 6, ratio, theme.faint, radius=3)
        canvas.text(rx, ry + 36, f"now {current_text}", 10, theme.mute, 500, MONO)
        canvas.text(rx + col_w, ry + 36, f"prev {previous_text}", 10, theme.faint, 500, MONO, anchor="end")

    y += wow_h + GAP
    comp_h = 98
    # AI Agent (left)
    canvas.card(PAD, y, HALF, comp_h)
    aix = PAD + PAD_IN
    aright = PAD + HALF - PAD_IN
    name, lines, cost = (data.agents[0] if data.agents else ("Claude", data.ai_lines, data.est_cost))
    canvas.ctitle(aix, y + 24, "AI AGENT", right="lines · cost", right_x=aright)
    canvas.rect(aix, y + 38, 18, 18, CLAUDE, radius=6)
    canvas.text(aix + 9, y + 51, name[0], 11, "#fff", 700, SANS, anchor="middle")
    canvas.text(aix + 26, y + 52, name, 14, theme.foreground, 600, SANS)
    canvas.text(aright, y + 52, fmt_money(cost), 13, theme.foreground2, 600, MONO, anchor="end")
    canvas.text(aix, y + 78, "lines", 10, theme.faint, 500, MONO)
    canvas.bar(aix + 40, y + 71, HALF - 2 * PAD_IN - 40 - 70, 7, 100, "url(#g_claude)", radius=4)
    canvas.text(aright, y + 77, f"{lines:,}", 11, theme.foreground2, 600, MONO, anchor="end")
    # Machines (right)
    mx = PAD + HALF + HGAP
    canvas.card(mx, y, HALF, comp_h)
    mix = mx + PAD_IN
    mright = mx + HALF - PAD_IN
    canvas.ctitle(mix, y + 24, "MACHINES")
    rowy = y + 50
    for index, (machine, percent, _) in enumerate(data.machines[:2]):
        label = machine.split(".")[0].replace("ui-MacBookPro", "")[:14]
        canvas.text(mix, rowy, label, 11, theme.foreground2, 500, MONO)
        canvas.bar(mix + 84, rowy - 7, HALF - 2 * PAD_IN - 84 - 44, 6, percent,
                   "url(#g_blue)" if index == 0 else theme.faint, radius=3)
        canvas.text(mright, rowy, f"{percent:.0f}%", 11, theme.mute, 600, MONO, anchor="end")
        rowy += 24
    return y + comp_h


def band_rhythm(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = TOP
    comp_h = 156
    # When I code (left)
    canvas.card(PAD, y, HALF, comp_h)
    wix = PAD + PAD_IN
    wright = PAD + HALF - PAD_IN
    ww = HALF - 2 * PAD_IN
    canvas.ctitle(wix, y + 24, "WHEN I CODE", right=data.peak_hour_text, right_x=wright)
    colors5 = ["#4C5FD5", "#E0A14B", theme.blue, "#A371F7", "#7C4DD0"]
    bar_y = y + 34
    canvas.add(f'<clipPath id="todclip"><rect x="{wix}" y="{bar_y}" width="{ww:.1f}" height="12" rx="6"/></clipPath>')
    canvas.add('<g clip-path="url(#todclip)">')
    cursor = wix
    for index, (_, _, _, percent) in enumerate(data.time_of_day):
        seg = ww * percent / 100
        canvas.rect(cursor, bar_y, seg + 0.5, 12, colors5[index])
        cursor += seg
    canvas.add('</g>')
    line_y = y + 62
    for index, (label, emoji, _, percent) in enumerate(data.time_of_day):
        canvas.rect(wix, line_y - 9, 9, 9, colors5[index], radius=3)
        canvas.text(wix + 16, line_y, f"{emoji} {label}", 12, theme.foreground2, 500, MONO)
        canvas.text(wright, line_y, f"{percent:.1f}%", 12, theme.foreground2, 600, MONO, anchor="end")
        line_y += 18
    # Weekday (right)
    mx = PAD + HALF + HGAP
    canvas.card(mx, y, HALF, comp_h)
    mix = mx + PAD_IN
    mright = mx + HALF - PAD_IN
    canvas.ctitle(mix, y + 24, "WEEKDAY", right=f"peak {data.peak_weekday}요일", right_x=mright)
    weekday_max = max((w[1] for w in data.weekdays), default=1) or 1
    bars_y = y + 40
    bar_area = 78
    gap = 8
    bw = (HALF - 2 * PAD_IN - gap * 6) / 7
    for index, (label, seconds, _, peak) in enumerate(data.weekdays):
        height = max(4, (seconds / weekday_max) * bar_area)
        bxx = mix + index * (bw + gap)
        by = bars_y + bar_area - height
        fill = "url(#g_peak)" if peak else theme.faint
        canvas.rect(bxx, by, bw, height, fill, radius=4)
        canvas.text(bxx + bw / 2, bars_y + bar_area + 16, label, 11,
                    theme.blue if peak else theme.mute, 600 if peak else 500, MONO, anchor="middle")

    y += comp_h + GAP
    bd_h = 48
    canvas.card(PAD, y, INNER, bd_h)
    canvas.text(PAD + PAD_IN, y + 28, "🏆 가장 생산적인 날", 12, theme.foreground2, 500, MONO)
    canvas.text(PAD + INNER - PAD_IN, y + 28, data.best_day_text, 12, theme.blue, 600, MONO, anchor="end")
    canvas.text(PAD + INNER / 2, y + 28,
                f"🔥 {data.streak}일 연속 · 최장 몰입 {data.longest_session_text}",
                12, theme.mute, 500, MONO, anchor="middle")
    return y + bd_h


def band_stack(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = TOP
    # Languages (full width card)
    lang_h = 46 + (len(data.languages) - 1) * 22 + 9 + 18
    canvas.card(PAD, y, INNER, lang_h)
    lix = PAD + PAD_IN
    lright = PAD + INNER - PAD_IN
    lw = INNER - 2 * PAD_IN
    canvas.ctitle(lix, y + 24, "LANGUAGES")
    ly = y + 46
    lang_colors = ["url(#g_purple)", "#3A82A8", CLAUDE, "#6E7681", theme.blue]
    for index, (name, percent, text) in enumerate(data.languages):
        canvas.text(lix, ly + 9, name, 13, theme.foreground2, 500, MONO)
        canvas.bar(lix + 96, ly + 1, lw - 96 - 150, 9, percent, lang_colors[index % 5], radius=5)
        canvas.text(lright, ly + 9, f"{text} · {percent:.1f}%", 12, theme.mute, 500, MONO, anchor="end")
        ly += 22
    y += lang_h + GAP

    # Editors (left) + Projects (right)
    comp_h = 48 + 3 * 24 + 8 + 18
    canvas.card(PAD, y, HALF, comp_h)
    eix = PAD + PAD_IN
    eright = PAD + HALF - PAD_IN
    canvas.ctitle(eix, y + 24, "EDITORS")
    ey = y + 48
    for index, (name, percent, _) in enumerate(data.editors):
        canvas.text(eix, ey + 8, name[:14], 12, theme.foreground2, 500, MONO)
        canvas.bar(eix + 90, ey + 1, HALF - 2 * PAD_IN - 90 - 48, 8, percent,
                   "url(#g_claude)" if index == 0 else theme.faint, radius=4)
        canvas.text(eright, ey + 8, f"{percent:.1f}%", 11, theme.mute, 600 if index == 0 else 500, MONO, anchor="end")
        ey += 24
    mx = PAD + HALF + HGAP
    canvas.card(mx, y, HALF, comp_h)
    pix = mx + PAD_IN
    pright = mx + HALF - PAD_IN
    canvas.ctitle(pix, y + 24, "PROJECTS")
    py = y + 48
    project_colors = ["url(#g_blue)", "url(#g_purple)", theme.faint, theme.faint]
    for index, (name, percent, _) in enumerate(data.projects[:4]):
        canvas.text(pix, py + 8, name[:12], 12, theme.foreground2, 500, MONO)
        canvas.bar(pix + 86, py + 1, HALF - 2 * PAD_IN - 86 - 48, 8, percent, project_colors[index], radius=4)
        canvas.text(pright, py + 8, f"{percent:.1f}%", 11, theme.mute, 600 if index < 2 else 500, MONO, anchor="end")
        py += 24
    y += comp_h + GAP

    # Dependencies (full width card)
    dep_rows = (len(data.dependencies[:6]) + 1) // 2
    dep_h = 48 + (dep_rows - 1) * 24 + 18
    canvas.card(PAD, y, INNER, dep_h)
    dix = PAD + PAD_IN
    canvas.ctitle(dix, y + 24, "DEPENDENCIES", right="detected libraries", right_x=PAD + INNER - PAD_IN)
    dep_col_w = (INNER - 2 * PAD_IN - HGAP) / 2
    dy0 = y + 48
    for index, (name, percent, _) in enumerate(data.dependencies[:6]):
        column = index % 2
        rownum = index // 2
        dx = dix + column * (dep_col_w + HGAP)
        dy = dy0 + rownum * 24
        canvas.text(dx, dy, name[:20], 12, theme.foreground2, 500, MONO)
        canvas.bar(dx + 150, dy - 7, dep_col_w - 150 - 40, 8, percent, "url(#g_blue)", radius=4)
        canvas.text(dx + dep_col_w, dy, f"{percent:.0f}%", 11, theme.mute, 500, MONO, anchor="end")
    return y + dep_h


def band_heatmap(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = TOP
    hix = PAD + PAD_IN
    hright = PAD + INNER - PAD_IN
    hw = INNER - 2 * PAD_IN
    count = len(data.heatmap)
    gap = 5
    cell = (hw - gap * (count - 1)) / count
    hm_h = 104 + cell
    canvas.card(PAD, y, INNER, hm_h)
    canvas.ctitle(hix, y + 24, "LAST 30 DAYS", right=f"{data.streak}일 연속 활동 🔥", right_x=hright)
    cells_y = y + 38
    for index, (_, _, level) in enumerate(data.heatmap):
        hx = hix + index * (cell + gap)
        canvas.rect(hx, cells_y, cell, cell, theme.heat[level], radius=3)
    legend_y = cells_y + cell + 14
    canvas.text(hix, legend_y + 9, "Less", 10, theme.faint, 500, MONO)
    lx = hix + 36
    for level in range(5):
        canvas.rect(lx, legend_y + 1, 11, 11, theme.heat[level], radius=3)
        lx += 15
    canvas.text(lx + 4, legend_y + 9, "More", 10, theme.faint, 500, MONO)
    foot_y = legend_y + 32
    owl = "저녁형" if data.late_night_pct < 25 else "새벽형"
    canvas.text(hix, foot_y, f"저는 {owl} 인간이에요 🦉 · 피크 {data.peak_hour_text} · 평균 {data.daily_avg_text}/day",
                11, theme.mute, 500, MONO)
    canvas.text(hright, foot_y, "powered by WakaTime", 10, theme.faint, 500, MONO, anchor="end")
    return y + hm_h


BANDS = [
    ("header", band_header),
    ("hero", band_hero),
    ("week", band_week),
    ("rhythm", band_rhythm),
    ("stack", band_stack),
    ("heatmap", band_heatmap),
]


def render_band(draw, data: WakaData, theme: Theme) -> str:
    canvas = Canvas(theme)
    gradients(canvas)
    content_height = draw(canvas, data)
    return wrap(canvas, content_height + TOP)


def readme_snippet() -> str:
    lines = ["<div align=\"center\">", ""]
    for key, _ in BANDS:
        lines += [
            "<picture>",
            f'  <source media="(prefers-color-scheme: dark)" srcset="./cards/{key}-dark.svg">',
            f'  <img alt="WakaTime {key}" src="./cards/{key}-light.svg" width="840">',
            "</picture>",
            "",
        ]
    lines.append("</div>")
    return "\n".join(lines)


def main():
    key = os.environ["WAKATIME_API_KEY"]
    today = dt.date.fromisoformat(os.environ["WAKA_TODAY"]) if os.environ.get("WAKA_TODAY") else None
    data = collect(key, today)
    out_dir = os.environ.get("WAKA_OUT_DIR", "cards")
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for theme in (DARK, LIGHT):
        for key_name, draw in BANDS:
            svg = render_band(draw, data, theme)
            path = os.path.join(out_dir, f"{key_name}-{theme.key}.svg")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(svg)
            written += 1
    if os.environ.get("WAKA_SNIPPET"):
        with open(os.environ["WAKA_SNIPPET"], "w", encoding="utf-8") as handle:
            handle.write(readme_snippet())
    print(f"wrote {written} band svgs to {out_dir}/")


if __name__ == "__main__":
    main()
