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
    y = 34
    canvas.rect(PAD, y - 14, 48, 48, "url(#g_blue)", radius=13)
    canvas.text(PAD + 24, y + 16, "R", 21, "#fff", 700, SANS, anchor="middle")
    canvas.text(PAD + 62, y + 6, "devRavit", 23, theme.foreground, 700, SANS, spacing="-0.2")
    canvas.text(PAD + 62, y + 26, f"WakaTime · {data.range_text} · {data.total_text} coded",
                12, theme.mute, 500, MONO)
    right = PAD + INNER

    def badge(x, label, fill, border, dot=None, emoji=None):
        width = 24 + len(label) * 7.1 + (16 if dot or emoji else 0)
        canvas.rect(x - width, y - 6, width, 26, fill, radius=13, stroke=border)
        cursor = x - width + 13
        if dot:
            canvas.add(f'<circle cx="{cursor}" cy="{y + 7:.0f}" r="3.5" fill="{dot}"/>')
            cursor += 11
        if emoji:
            canvas.text(cursor - 2, y + 11, emoji, 12, theme.foreground, 400, SANS)
            cursor += 16
        canvas.text(cursor, y + 11, label, 11, theme.foreground2, 600, MONO)
        return x - width - 9

    badge_bg = "#11243b" if theme.key == "dark" else "#dbeafe"
    nxt = badge(right, "AI-Native", badge_bg, theme.blue, dot=theme.blue)
    nxt = badge(nxt, "Night Owl", theme.panel, theme.panel_stroke, emoji="🦉")
    streak_bg = "#2a1a10" if theme.key == "dark" else "#fbe9df"
    badge(nxt, f"{data.streak}d streak", streak_bg, CLAUDE, emoji="🔥")
    canvas.text(right, y + 34, f"avg {data.daily_avg_text} / day", 11, theme.faint, 500, MONO, anchor="end")
    return y + 48


def band_hero(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = 14
    hero_h = 150
    hero_bg = "#1a130f" if theme.key == "dark" else "#fbf1ea"
    hero_stroke = "#3a2a20" if theme.key == "dark" else "#f0d9cb"
    canvas.rect(PAD, y, INNER, hero_h, hero_bg, radius=16, stroke=hero_stroke)
    cx, cy, r = PAD + 75, y + hero_h / 2, 52
    circ = 2 * math.pi * r
    offset = circ * (1 - data.ai_coding_pct / 100.0)
    ring_track = "#241a14" if theme.key == "dark" else "#f2ddd0"
    canvas.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="{ring_track}" stroke-width="13"/>')
    canvas.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="url(#g_ring)" stroke-width="13" '
               f'stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}" '
               f'transform="rotate(-90 {cx} {cy:.0f})"/>')
    canvas.text(cx, cy - 2, f"{data.ai_coding_pct:.0f}", 34, theme.foreground, 700, SANS,
                anchor="middle", spacing="-1")
    canvas.text(cx, cy + 16, "% AI-DRIVEN", 9, CLAUDE2, 600, MONO, anchor="middle", spacing="1")

    bx = PAD + 160
    bw = INNER - 160 - 28
    canvas.text(bx, y + 30, "거의 모든 코드를 Claude와 함께 작성했어요", 16, theme.foreground, 600, SANS)
    total = max(1, data.ai_lines + data.human_lines)
    ai_pct = data.ai_lines / total * 100
    human_pct = data.human_lines / total * 100
    row = y + 52
    canvas.add(f'<circle cx="{bx + 4}" cy="{row - 4}" r="4" fill="{CLAUDE}"/>')
    canvas.text(bx + 16, row, "AI", 13, theme.sub, 500, MONO)
    canvas.text(bx + 42, row, fmt_count(data.ai_lines), 15, theme.foreground, 700, SANS)
    canvas.text(bx + bw, row, f"{ai_pct:.0f}%", 13, theme.foreground2, 600, MONO, anchor="end")
    canvas.bar(bx, row + 8, bw, 9, ai_pct, "url(#g_claude)", radius=5)
    row += 36
    canvas.add(f'<circle cx="{bx + 4}" cy="{row - 4}" r="4" fill="{GREEN}"/>')
    canvas.text(bx + 16, row, "Human", 13, theme.sub, 500, MONO)
    canvas.text(bx + 64, row, fmt_count(data.human_lines), 15, theme.foreground, 700, SANS)
    canvas.text(bx + bw, row, f"{human_pct:.0f}%", 13, theme.mute, 600, MONO, anchor="end")
    canvas.bar(bx, row + 8, bw, 9, human_pct, GREEN, radius=5)

    y += hero_h + 16
    tiles = [
        (fmt_count(data.ai_lines), "AI line changes", None),
        (fmt_count(data.tokens_in), f"tokens in · {fmt_count(data.tokens_out)} out", "B"),
        (fmt_money(data.est_cost), "est. cost · 7 days", None),
        (f"{data.lines_per_prompt:.0f}", "lines / prompt", None),
    ]
    tile_w = (INNER - 13 * 3) / 4
    for index, (value, label, suffix) in enumerate(tiles):
        tx = PAD + index * (tile_w + 13)
        canvas.rect(tx, y, tile_w, 70, theme.panel, radius=13, stroke=theme.panel_stroke)
        canvas.text(tx + 16, y + 30, value, 25, theme.foreground, 700, SANS, spacing="-0.5")
        if suffix:
            canvas.text(tx + 16 + len(value) * 15.5, y + 30, suffix, 16, theme.blue, 700, SANS)
        canvas.text(tx + 16, y + 52, label, 11, theme.mute, 500, MONO)
    return y + 70 + 6


def band_week(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = 14
    box_h = 132
    canvas.rect(PAD, y, INNER, box_h, theme.panel, radius=14, stroke=theme.panel_stroke)
    canvas.text(PAD + 20, y + 26, "THIS WEEK vs LAST WEEK", 11, theme.faint, 600, MONO, spacing="1.2", upper=True)
    delta, color = fmt_delta(data.wow_time[2], theme)
    canvas.text(PAD + 20, y + 52, delta, 22, color, 700, SANS, spacing="-0.5")
    canvas.text(PAD + 20 + len(delta) * 14 + 12, y + 52, "coding time", 12, theme.sub, 500, MONO)
    canvas.text(PAD + INNER - 20, y + 26,
                f"{data.wow_time[0] / 3600:.0f}h vs {data.wow_time[1] / 3600:.0f}h",
                12, theme.mute, 500, MONO, anchor="end")
    rows = [
        ("Coding time", data.wow_time[0] / 3600, data.wow_time[1] / 3600, data.wow_time[2], "h", theme.blue),
        ("AI lines", data.wow_ai_lines[0], data.wow_ai_lines[1], data.wow_ai_lines[2], "#", CLAUDE),
        ("Tokens", data.wow_tokens[0], data.wow_tokens[1], data.wow_tokens[2], "t", PURPLE),
    ]
    col_w = (INNER - 40 - 40) / 3
    ry = y + 72
    for index, (label, current, previous, percent, kind, color) in enumerate(rows):
        rx = PAD + 20 + index * (col_w + 20)
        current_text = f"{current:.0f}h" if kind == "h" else fmt_count(current)
        previous_text = f"{previous:.0f}h" if kind == "h" else fmt_count(previous)
        delta_text, delta_color = fmt_delta(percent, theme)
        canvas.text(rx, ry, label, 11, theme.foreground2, 500, MONO)
        canvas.text(rx + col_w, ry, delta_text, 11, delta_color, 600, MONO, anchor="end")
        canvas.bar(rx, ry + 8, col_w, 6, 100, color, radius=3)
        ratio = (previous / current * 100) if current else 0
        canvas.bar(rx, ry + 18, col_w, 6, ratio, theme.faint, radius=3)
        canvas.text(rx, ry + 38, f"now {current_text}", 10, theme.mute, 500, MONO)
        canvas.text(rx + col_w, ry + 38, f"prev {previous_text}", 10, theme.faint, 500, MONO, anchor="end")

    y += box_h + 22
    y = canvas.section(y, "AI Agents", "lines · est. cost")
    half = (INNER - 26) / 2
    name, lines, cost = (data.agents[0] if data.agents else ("Claude", data.ai_lines, data.est_cost))
    canvas.rect(PAD, y, half, 78, theme.panel, radius=13, stroke=theme.panel_stroke)
    canvas.rect(PAD + 18, y + 16, 18, 18, CLAUDE, radius=6)
    canvas.text(PAD + 27, y + 29, name[0], 11, "#fff", 700, SANS, anchor="middle")
    canvas.text(PAD + 44, y + 30, name, 14, theme.foreground, 600, SANS)
    canvas.text(PAD + half - 18, y + 30, fmt_money(cost), 13, theme.foreground2, 600, MONO, anchor="end")
    canvas.text(PAD + 18, y + 56, "lines", 10, theme.faint, 500, MONO)
    canvas.bar(PAD + 56, y + 49, half - 56 - 80, 7, 100, "url(#g_claude)", radius=4)
    canvas.text(PAD + half - 18, y + 55, f"{lines:,}", 11, theme.foreground2, 600, MONO, anchor="end")

    mx = PAD + half + 26
    canvas.rect(mx, y, half, 78, theme.panel, radius=13, stroke=theme.panel_stroke)
    canvas.text(mx + 18, y + 26, "MACHINES", 10, theme.faint, 600, MONO, spacing="1", upper=True)
    my = y + 46
    for index, (machine, percent, _) in enumerate(data.machines[:2]):
        label = machine.split(".")[0].replace("ui-MacBookPro", "")[:14]
        canvas.text(mx + 18, my, label, 11, theme.foreground2, 500, MONO)
        canvas.bar(mx + 18, my + 6, half - 36 - 50, 6, percent,
                   "url(#g_blue)" if index == 0 else theme.faint, radius=3)
        canvas.text(mx + half - 18, my, f"{percent:.0f}%", 11, theme.mute, 600, MONO, anchor="end")
        my += 22
    return y + 78


def band_rhythm(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    half = (INNER - 26) / 2
    col_split = PAD + half + 26
    top = 14
    y2 = canvas.section(top, "When I code", data.peak_hour_text, x=PAD, width=half)
    colors5 = ["#4C5FD5", "#E0A14B", canvas.theme.blue, "#A371F7", "#7C4DD0"]
    canvas.add(f'<clipPath id="todclip"><rect x="{PAD}" y="{y2}" width="{half:.1f}" height="13" rx="6"/></clipPath>')
    canvas.add('<g clip-path="url(#todclip)">')
    cursor = PAD
    for index, (_, _, _, percent) in enumerate(data.time_of_day):
        width = half * percent / 100
        canvas.rect(cursor, y2, width + 0.5, 13, colors5[index])
        cursor += width
    canvas.add('</g>')
    line_y = y2 + 30
    for index, (label, emoji, _, percent) in enumerate(data.time_of_day):
        canvas.rect(PAD, line_y - 9, 9, 9, colors5[index], radius=3)
        canvas.text(PAD + 16, line_y, f"{emoji} {label}", 12, theme.foreground2, 500, MONO)
        canvas.text(PAD + half, line_y, f"{percent:.1f}%", 12, theme.foreground2, 600, MONO, anchor="end")
        line_y += 20

    canvas.section(top, "Weekday", f"peak {data.peak_weekday}요일", x=col_split, width=half)
    weekday_max = max((w[1] for w in data.weekdays), default=1) or 1
    bars_y = top + 22
    bar_area = 110
    gap = 8
    bar_w = (half - gap * 6) / 7
    for index, (label, seconds, _, peak) in enumerate(data.weekdays):
        height = max(4, (seconds / weekday_max) * bar_area)
        bx = col_split + index * (bar_w + gap)
        by = bars_y + bar_area - height
        fill = "url(#g_peak)" if peak else theme.faint
        canvas.rect(bx, by, bar_w, height, fill, radius=4)
        canvas.text(bx + bar_w / 2, bars_y + bar_area + 16, label, 11,
                    theme.blue if peak else theme.mute, 600 if peak else 500, MONO, anchor="middle")

    y = top + max(line_y - top, bars_y + bar_area + 16 - top) + 16
    badge_bg = "#0e1722" if theme.key == "dark" else "#eef3f8"
    canvas.rect(PAD, y, INNER, 34, badge_bg, radius=10, stroke=theme.panel_stroke)
    canvas.text(PAD + 16, y + 22, "🏆 가장 생산적인 날", 12, theme.foreground2, 500, MONO)
    canvas.text(PAD + INNER - 16, y + 22, data.best_day_text, 12, theme.blue, 600, MONO, anchor="end")
    canvas.text(PAD + INNER / 2, y + 22,
                f"🔥 {data.streak}일 연속 · 최장 몰입 {data.longest_session_text}",
                12, theme.mute, 500, MONO, anchor="middle")
    return y + 34


def band_stack(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    half = (INNER - 26) / 2
    col_split = PAD + half + 26
    y = canvas.section(14, "Languages")
    lang_colors = ["url(#g_purple)", "#3A82A8", CLAUDE, "#6E7681", theme.blue]
    for index, (name, percent, text) in enumerate(data.languages):
        canvas.text(PAD, y + 9, name, 13, theme.foreground2, 500, MONO)
        canvas.bar(PAD + 100, y + 1, INNER - 100 - 150, 9, percent, lang_colors[index % 5], radius=5)
        canvas.text(PAD + INNER, y + 9, f"{text} · {percent:.1f}%", 12, theme.mute, 500, MONO, anchor="end")
        y += 22

    y += 6
    base = y
    y2 = canvas.section(y, "Editors", x=PAD, width=half)
    for index, (name, percent, _) in enumerate(data.editors):
        canvas.text(PAD, y2 + 8, name[:14], 12, theme.foreground2, 500, MONO)
        canvas.bar(PAD + 90, y2 + 1, half - 90 - 48, 8, percent,
                   "url(#g_claude)" if index == 0 else theme.faint, radius=4)
        canvas.text(PAD + half, y2 + 8, f"{percent:.1f}%", 11, theme.mute, 600 if index == 0 else 500,
                    MONO, anchor="end")
        y2 += 24
    yp = canvas.section(base, "Projects", x=col_split, width=half)
    project_colors = ["url(#g_blue)", "url(#g_purple)", theme.faint, theme.faint]
    for index, (name, percent, _) in enumerate(data.projects[:4]):
        canvas.text(col_split, yp + 8, name[:12], 12, theme.foreground2, 500, MONO)
        canvas.bar(col_split + 86, yp + 1, half - 86 - 48, 8, percent, project_colors[index], radius=4)
        canvas.text(col_split + half, yp + 8, f"{percent:.1f}%", 11, theme.mute, 600 if index < 2 else 500,
                    MONO, anchor="end")
        yp += 24
    y = max(y2, yp) + 14

    y = canvas.section(y, "Dependencies", "detected libraries")
    dep_w = (INNER - 26) / 2
    for index, (name, percent, _) in enumerate(data.dependencies[:6]):
        column = index % 2
        rownum = index // 2
        dx = PAD + column * (dep_w + 26)
        dy = y + rownum * 24
        canvas.text(dx, dy + 8, name[:20], 12, theme.foreground2, 500, MONO)
        canvas.bar(dx + 150, dy + 1, dep_w - 150 - 44, 8, percent, "url(#g_blue)", radius=4)
        canvas.text(dx + dep_w, dy + 8, f"{percent:.0f}%", 11, theme.mute, 500, MONO, anchor="end")
    return y + ((len(data.dependencies[:6]) + 1) // 2) * 24 - 8


def band_heatmap(canvas: Canvas, data: WakaData) -> float:
    theme = canvas.theme
    y = canvas.section(14, "Last 30 days", f"{data.streak}일 연속 활동 🔥")
    count = len(data.heatmap)
    gap = 5
    cell = (INNER - gap * (count - 1)) / count
    for index, (_, _, level) in enumerate(data.heatmap):
        hx = PAD + index * (cell + gap)
        canvas.rect(hx, y, cell, cell, theme.heat[level], radius=3)
    y += cell + 12
    canvas.text(PAD, y + 8, "Less", 10, theme.faint, 500, MONO)
    lx = PAD + 34
    for level in range(5):
        canvas.rect(lx, y, 11, 11, theme.heat[level], radius=3)
        lx += 15
    canvas.text(lx + 4, y + 8, "More", 10, theme.faint, 500, MONO)

    y += 11 + 20
    canvas.add(f'<line x1="{PAD}" y1="{y}" x2="{PAD + INNER}" y2="{y}" stroke="{theme.divider}"/>')
    y += 18
    owl = "저녁형" if data.late_night_pct < 25 else "새벽형"
    canvas.text(PAD, y, f"저는 {owl} 인간이에요 🦉 · 피크 {data.peak_hour_text} · 평균 {data.daily_avg_text}/day",
                11, theme.mute, 500, MONO)
    canvas.text(PAD + INNER, y, "powered by WakaTime", 10, theme.faint, 500, MONO, anchor="end")
    return y + 12


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
    bg_index = len(canvas.parts)
    content_height = draw(canvas, data)
    total = content_height + 14
    # 밴드별 카드 배경 (테마 적응) — 위/아래 6px 투명 여백으로 스택 시 카드 간 간극
    background = (f'<rect x="1" y="6" width="{WIDTH - 2}" height="{total - 12:.0f}" rx="16" '
                 f'fill="{theme.card_bg}" stroke="{theme.card_stroke}"/>')
    canvas.parts.insert(bg_index, background)
    return wrap(canvas, total)


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
