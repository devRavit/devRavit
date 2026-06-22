"""WakaTime AI 코딩 카드 → 네이티브 SVG 렌더러.

모든 막대/링/히트맵 기하값은 waka_data.collect() 의 런타임 데이터에서 계산한다.
하드코딩은 레이아웃 상수(색·폰트·패딩·위치)뿐.

GitHub README(camo) 제약 반영:
  - foreignObject/HTML 금지 → 순수 SVG 도형/텍스트
  - 외부 웹폰트 미로드 → font-family 폴백 스택
"""
from __future__ import annotations

import datetime as dt
import html
import math
import os

from waka_data import collect, WakaData

# ---------- palette ----------
BG = "#0d1117"
BORDER = "#20262e"
TILE = "#10161e"
TRACK = "#161b22"
DIV = "#1c222a"
FG = "#f0f6fc"
FG2 = "#c9d1d9"
SUB = "#8b949e"
MUTE = "#7d8590"
FAINT = "#5b6470"
BLUE = "#58A6FF"
BLUE2 = "#79b8ff"
CLAUDE = "#D97757"
CLAUDE2 = "#E8A06F"
PURPLE = "#A371F7"
PURPLE2 = "#8B6FC9"
GREEN = "#2EA043"

SANS = "'Space Grotesk','Segoe UI',system-ui,-apple-system,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace"

W = 840
PAD = 36
INNER = W - PAD * 2  # 768
HEAT_SCALE = ["#161b22", "#0d2d4a", "#15487f", "#2f6fc0", "#58A6FF"]


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def fmt_count(n: float) -> str:
    n = float(n)
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return f"{int(n)}"


def fmt_money(n: float) -> str:
    return "$" + f"{n:,.0f}"


def fmt_delta(pct: float) -> tuple[str, str]:
    arrow = "▲" if pct >= 0 else "▼"
    color = GREEN if pct >= 0 else "#f85149"
    return f"{arrow} {abs(pct):.0f}%", color


class SVG:
    def __init__(self):
        self.parts: list[str] = []

    def add(self, s: str):
        self.parts.append(s)

    def text(self, x, y, s, size=12, color=FG, weight=400, family=MONO,
             anchor="start", spacing=None, upper=False):
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        st = ' style="text-transform:uppercase"' if upper else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{ls}{st}>{esc(s)}</text>'
        )

    def rect(self, x, y, w, h, fill, r=0, stroke=None, sw=1):
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0, w):.1f}" '
                 f'height="{h:.1f}" rx="{r}" fill="{fill}"{st}/>')

    def bar(self, x, y, w, h, pct, fill, track=TRACK, r=None):
        r = h / 2 if r is None else r
        self.rect(x, y, w, h, track, r)
        fw = max(0.0, min(1.0, pct / 100.0)) * w
        if fw > 0:
            self.rect(x, y, max(fw, h if fw > 0 else 0), h, fill, r)

    def section(self, y, title, right=None):
        self.text(PAD, y, title, 12, BLUE, 600, MONO, spacing="1.4", upper=True)
        tx = PAD + 9 + len(title) * 8.2
        self.add(f'<line x1="{tx:.0f}" y1="{y - 4:.0f}" x2="{PAD + INNER - (90 if right else 0):.0f}" '
                 f'y2="{y - 4:.0f}" stroke="{DIV}"/>')
        if right:
            self.text(PAD + INNER, y, right, 11, MUTE, 500, MONO, anchor="end")
        return y + 22

    def out(self, height) -> str:
        body = "\n".join(self.parts)
        return (
            f'<svg width="{W}" height="{height}" viewBox="0 0 {W} {height}" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="{SANS}">\n{body}\n</svg>\n'
        )


def lin(svg: SVG, gid, c0, c1, horizontal=True):
    x2, y2 = (1, 0) if horizontal else (0, 1)
    svg.add(f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f'<stop offset="0" stop-color="{c0}"/><stop offset="1" stop-color="{c1}"/></linearGradient>')


def render(d: WakaData) -> str:
    s = SVG()
    # defs
    s.add("<defs>")
    lin(s, "g_claude", CLAUDE, CLAUDE2)
    lin(s, "g_blue", BLUE, BLUE2)
    lin(s, "g_purple", PURPLE2, PURPLE)
    lin(s, "g_ring", CLAUDE, CLAUDE2, horizontal=False)
    lin(s, "g_peak", BLUE, PURPLE, horizontal=False)
    s.add(f'<radialGradient id="glow_o" cx="50%" cy="50%" r="50%">'
          f'<stop offset="0" stop-color="{CLAUDE}" stop-opacity="0.16"/>'
          f'<stop offset="0.68" stop-color="{CLAUDE}" stop-opacity="0"/></radialGradient>')
    s.add(f'<radialGradient id="glow_b" cx="50%" cy="50%" r="50%">'
          f'<stop offset="0" stop-color="{BLUE}" stop-opacity="0.12"/>'
          f'<stop offset="0.7" stop-color="{BLUE}" stop-opacity="0"/></radialGradient>')
    s.add("</defs>")

    # placeholder background+border (height set later)
    HEIGHT_TOKEN = "@@H@@"
    s.add(f'<rect x="1" y="1" width="{W - 2}" height="{HEIGHT_TOKEN}" rx="18" fill="{BG}" stroke="{BORDER}"/>')
    s.add(f'<circle cx="{W - 120}" cy="40" r="210" fill="url(#glow_o)"/>')
    s.add(f'<circle cx="90" cy="{HEIGHT_TOKEN}" r="180" fill="url(#glow_b)"/>')

    y = 56
    # ===== HEADER =====
    s.rect(PAD, y - 14, 48, 48, "url(#g_blue)", r=13)
    s.text(PAD + 24, y + 16, "R", 21, "#fff", 700, SANS, anchor="middle")
    s.text(PAD + 62, y + 6, "devRavit", 23, FG, 700, SANS, spacing="-0.2")
    s.text(PAD + 62, y + 26, f"WakaTime · {d.range_text} · {d.total_text} coded", 12, MUTE, 500, MONO)
    # badges (right)
    bx = PAD + INNER
    def badge(x, label, fill, border, dot=None, emoji=None):
        w = 24 + len(label) * 7.1 + (16 if dot or emoji else 0)
        s.rect(x - w, y - 6, w, 26, fill, r=13, stroke=border)
        cx = x - w + 13
        if dot:
            s.add(f'<circle cx="{cx}" cy="{y + 7:.0f}" r="3.5" fill="{dot}"/>')
            cx += 11
        if emoji:
            s.text(cx - 2, y + 11, emoji, 12, FG, 400, SANS)
            cx += 16
        s.text(cx, y + 11, label, 11, FG2, 600, MONO)
        return x - w - 9
    nx = badge(bx, "AI-Native", "#11243b", "#1f4a73", dot=BLUE)
    nx = badge(nx, "Night Owl", TILE, BORDER, emoji="🦉")
    badge(nx, f"{d.streak}d streak", "#2a1a10", "#5a3a20", emoji="🔥")
    s.text(bx, y + 34, f"avg {d.daily_avg_text} / day", 11, FAINT, 500, MONO, anchor="end")

    y += 58
    # ===== HERO: ring + AI vs Human =====
    hero_h = 150
    s.rect(PAD, y, INNER, hero_h, "#1a130f", r=16, stroke="#3a2a20")
    # ring
    cx, cy, r = PAD + 75, y + hero_h / 2, 52
    circ = 2 * math.pi * r
    off = circ * (1 - d.ai_coding_pct / 100.0)
    s.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="#241a14" stroke-width="13"/>')
    s.add(f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" stroke="url(#g_ring)" stroke-width="13" '
          f'stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{off:.1f}" '
          f'transform="rotate(-90 {cx} {cy:.0f})"/>')
    s.text(cx, cy - 2, f"{d.ai_coding_pct:.0f}", 34, FG, 700, SANS, anchor="middle", spacing="-1")
    s.text(cx, cy + 16, "% AI-DRIVEN", 9, CLAUDE2, 600, MONO, anchor="middle", spacing="1")
    # AI vs human bars
    bx0 = PAD + 160
    bw = INNER - 160 - 28
    s.text(bx0, y + 30, "거의 모든 코드를 Claude와 함께 작성했어요", 16, FG, 600, SANS)
    total_lines = max(1, d.ai_lines + d.human_lines)
    ai_pct = d.ai_lines / total_lines * 100
    hu_pct = d.human_lines / total_lines * 100
    yy = y + 52
    s.add(f'<circle cx="{bx0 + 4}" cy="{yy - 4}" r="4" fill="{CLAUDE}"/>')
    s.text(bx0 + 16, yy, "AI", 13, SUB, 500, MONO)
    s.text(bx0 + 42, yy, fmt_count(d.ai_lines), 15, FG, 700, SANS)
    s.text(bx0 + bw, yy, f"{ai_pct:.0f}%", 13, FG2, 600, MONO, anchor="end")
    s.bar(bx0, yy + 8, bw, 9, ai_pct, "url(#g_claude)", r=5)
    yy += 36
    s.add(f'<circle cx="{bx0 + 4}" cy="{yy - 4}" r="4" fill="{GREEN}"/>')
    s.text(bx0 + 16, yy, "Human", 13, SUB, 500, MONO)
    s.text(bx0 + 64, yy, fmt_count(d.human_lines), 15, FG, 700, SANS)
    s.text(bx0 + bw, yy, f"{hu_pct:.0f}%", 13, MUTE, 600, MONO, anchor="end")
    s.bar(bx0, yy + 8, bw, 9, hu_pct, GREEN, r=5)

    y += hero_h + 18
    # ===== METRIC TILES (4) =====
    tiles = [
        (fmt_count(d.ai_lines), "AI line changes", None),
        (fmt_count(d.tokens_in), f"tokens in · {fmt_count(d.tokens_out)} out", "B"),
        (fmt_money(d.est_cost), "est. cost · 7 days", None),
        (f"{d.lines_per_prompt:.0f}", "lines / prompt", None),
    ]
    tw = (INNER - 13 * 3) / 4
    for i, (val, label, suffix) in enumerate(tiles):
        tx = PAD + i * (tw + 13)
        s.rect(tx, y, tw, 70, TILE, r=13, stroke=BORDER)
        s.text(tx + 16, y + 30, val, 25, FG, 700, SANS, spacing="-0.5")
        if suffix:
            s.text(tx + 16 + len(val) * 15.5, y + 30, suffix, 16, BLUE, 700, SANS)
        s.text(tx + 16, y + 52, label, 11, MUTE, 500, MONO)

    y += 70 + 26
    # ===== THIS WEEK vs LAST WEEK (replaces vs-average) =====
    box_h = 132
    s.rect(PAD, y, INNER, box_h, TILE, r=14, stroke=BORDER)
    s.text(PAD + 20, y + 26, "THIS WEEK vs LAST WEEK", 11, FAINT, 600, MONO, spacing="1.2", upper=True)
    big_delta, big_color = fmt_delta(d.wow_time[2])
    s.text(PAD + 20, y + 52, big_delta, 22, big_color, 700, SANS, spacing="-0.5")
    s.text(PAD + 20 + len(big_delta) * 14 + 12, y + 52, "coding time", 12, SUB, 500, MONO)
    s.text(PAD + INNER - 20, y + 26,
           f"{d.wow_time[0] / 3600:.0f}h vs {d.wow_time[1] / 3600:.0f}h",
           12, MUTE, 500, MONO, anchor="end")
    rows = [
        ("Coding time", d.wow_time[0] / 3600, d.wow_time[1] / 3600, d.wow_time[2], "h", BLUE),
        ("AI lines", d.wow_ai_lines[0], d.wow_ai_lines[1], d.wow_ai_lines[2], "#", CLAUDE),
        ("Tokens", d.wow_tokens[0], d.wow_tokens[1], d.wow_tokens[2], "t", PURPLE),
    ]
    cw = (INNER - 40 - 40) / 3
    ry = y + 72
    for i, (lbl, cur, prev, pct, kind, col) in enumerate(rows):
        rx = PAD + 20 + i * (cw + 20)
        curs = (f"{cur:.0f}h" if kind == "h" else fmt_count(cur))
        prevs = (f"{prev:.0f}h" if kind == "h" else fmt_count(prev))
        delta, dc = fmt_delta(pct)
        s.text(rx, ry, lbl, 11, FG2, 500, MONO)
        s.text(rx + cw, ry, delta, 11, dc, 600, MONO, anchor="end")
        s.bar(rx, ry + 8, cw, 6, 100, col, r=3)
        ratio = (prev / cur * 100) if cur else 0
        s.bar(rx, ry + 18, cw, 6, ratio, "#3d4757", r=3)
        s.text(rx, ry + 38, f"now {curs}", 10, MUTE, 500, MONO)
        s.text(rx + cw, ry + 38, f"prev {prevs}", 10, FAINT, 500, MONO, anchor="end")

    y += box_h + 26
    # ===== AI AGENT + MACHINES =====
    y = s.section(y, "AI Agents", "lines · est. cost")
    half = (INNER - 26) / 2
    # agent card (Claude)
    name, lines, cost = (d.agents[0] if d.agents else ("Claude", d.ai_lines, d.est_cost))
    s.rect(PAD, y, half, 78, TILE, r=13, stroke=BORDER)
    s.rect(PAD + 18, y + 16, 18, 18, CLAUDE, r=6)
    s.text(PAD + 27, y + 29, name[0], 11, "#fff", 700, SANS, anchor="middle")
    s.text(PAD + 44, y + 30, name, 14, FG, 600, SANS)
    s.text(PAD + half - 18, y + 30, fmt_money(cost), 13, FG2, 600, MONO, anchor="end")
    s.text(PAD + 18, y + 56, "lines", 10, FAINT, 500, MONO)
    s.bar(PAD + 56, y + 49, half - 56 - 80, 7, 100, "url(#g_claude)", r=4)
    s.text(PAD + half - 18, y + 55, f"{lines:,}", 11, FG2, 600, MONO, anchor="end")
    # machines card
    mx = PAD + half + 26
    s.rect(mx, y, half, 78, TILE, r=13, stroke=BORDER)
    s.text(mx + 18, y + 26, "MACHINES", 10, FAINT, 600, MONO, spacing="1", upper=True)
    my = y + 46
    for i, (mname, mpct, mtext) in enumerate(d.machines[:2]):
        short = mname.split(".")[0].replace("ui-MacBookPro", "")[:14]
        s.text(mx + 18, my, short, 11, FG2, 500, MONO)
        s.bar(mx + 18, my + 6, half - 36 - 50, 6, mpct, "url(#g_blue)" if i == 0 else "#3d4757", r=3)
        s.text(mx + half - 18, my, f"{mpct:.0f}%", 11, MUTE, 600, MONO, anchor="end")
        my += 22

    y += 78 + 26
    # ===== WHEN I CODE (5 buckets) + WEEKDAY =====
    col_split = PAD + half + 26
    base_y = y
    y2 = s.section(y, "When I code", d.peak_hour_text)
    # stacked bar
    colors5 = ["#4C5FD5", "#E0A14B", "#58A6FF", "#A371F7", "#7C4DD0"]
    s.add(f'<clipPath id="todclip"><rect x="{PAD}" y="{y2}" width="{half:.1f}" height="13" rx="6"/></clipPath>')
    s.add('<g clip-path="url(#todclip)">')
    cursor = PAD
    for i, (lbl, emo, sec, pct) in enumerate(d.time_of_day):
        w = half * pct / 100
        s.rect(cursor, y2, w + 0.5, 13, colors5[i])
        cursor += w
    s.add('</g>')
    ly = y2 + 30
    for i, (lbl, emo, sec, pct) in enumerate(d.time_of_day):
        s.rect(PAD, ly - 9, 9, 9, colors5[i], r=3)
        s.text(PAD + 16, ly, f"{emo} {lbl}", 12, FG2, 500, MONO)
        s.text(PAD + half, ly, f"{pct:.1f}%", 12, FG2, 600, MONO, anchor="end")
        ly += 20
    # weekday bars (right)
    s.section(base_y, "Weekday", f"peak {d.peak_weekday}요일")
    wd_max = max((w[1] for w in d.weekdays), default=1) or 1
    bars_y = base_y + 22
    bar_area_h = 110
    gap = 8
    bw2 = (half - gap * 6) / 7
    for i, (lbl, sec, pct, peak) in enumerate(d.weekdays):
        bh = max(4, (sec / wd_max) * bar_area_h)
        bxx = col_split + i * (bw2 + gap)
        byy = bars_y + bar_area_h - bh
        fill = "url(#g_peak)" if peak else "#2f3a4a"
        s.rect(bxx, byy, bw2, bh, fill, r=4)
        s.text(bxx + bw2 / 2, bars_y + bar_area_h + 16, lbl, 11,
               BLUE if peak else MUTE, 600 if peak else 500, MONO, anchor="middle")

    y = base_y + max(ly - base_y, bars_y + bar_area_h + 16 - base_y) + 18
    # ===== best_day badge line =====
    s.rect(PAD, y, INNER, 34, "#0e1722", r=10, stroke=BORDER)
    s.text(PAD + 16, y + 22, "🏆 가장 생산적인 날", 12, FG2, 500, MONO)
    s.text(PAD + INNER - 16, y + 22, d.best_day_text, 12, BLUE2, 600, MONO, anchor="end")
    s.text(PAD + INNER / 2, y + 22,
           f"🔥 {d.streak}일 연속 · 최장 몰입 {d.longest_session_text}", 12, MUTE, 500, MONO, anchor="middle")

    y += 34 + 28
    # ===== LANGUAGES =====
    y = s.section(y, "Languages")
    lang_grad = ["#7F52FF", "#3A82A8", "#D9663B", "#6E7681", BLUE]
    for i, (name, pct, text) in enumerate(d.languages):
        s.text(PAD, y + 9, name, 13, FG2, 500, MONO)
        s.bar(PAD + 100, y + 1, INNER - 100 - 150, 9, pct,
              f"url(#g_{['purple','blue','claude','blue','blue'][i % 5]})" if i < 1 else lang_grad[i % 5], r=5)
        s.text(PAD + INNER, y + 9, f"{text} · {pct:.1f}%", 12, MUTE, 500, MONO, anchor="end")
        y += 22

    y += 6
    # ===== EDITORS + PROJECTS =====
    base_y = y
    y2 = s.section(y, "Editors")
    for i, (name, pct, text) in enumerate(d.editors):
        s.text(PAD, y2 + 8, name[:14], 12, FG2, 500, MONO)
        s.bar(PAD + 90, y2 + 1, half - 90 - 48, 8, pct, "url(#g_claude)" if i == 0 else "#3d4757", r=4)
        s.text(PAD + half, y2 + 8, f"{pct:.1f}%", 11, MUTE, 600 if i == 0 else 500, MONO, anchor="end")
        y2 += 24
    yp = s.section(base_y, "Projects")
    pj_fill = ["url(#g_blue)", "url(#g_purple)", "#3d4757", "#3d4757", "#3d4757"]
    for i, (name, pct, text) in enumerate(d.projects[:4]):
        s.text(col_split, yp + 8, name[:12], 12, FG2, 500, MONO)
        s.bar(col_split + 86, yp + 1, half - 86 - 48, 8, pct, pj_fill[i], r=4)
        s.text(col_split + half, yp + 8, f"{pct:.1f}%", 11, MUTE, 600 if i < 2 else 500, MONO, anchor="end")
        yp += 24
    y = max(y2, yp) + 14

    # ===== DEPENDENCIES =====
    y = s.section(y, "Dependencies", "detected libraries")
    dep_cols = 2
    dcw = (INNER - 26) / dep_cols
    for i, (name, pct, text) in enumerate(d.dependencies[:6]):
        col = i % dep_cols
        row = i // dep_cols
        dx = PAD + col * (dcw + 26)
        dyy = y + row * 24
        s.text(dx, dyy + 8, name[:20], 12, FG2, 500, MONO)
        s.bar(dx + 150, dyy + 1, dcw - 150 - 44, 8, pct, "url(#g_blue)", r=4)
        s.text(dx + dcw, dyy + 8, f"{pct:.0f}%", 11, MUTE, 500, MONO, anchor="end")
    y += ((len(d.dependencies[:6]) + 1) // 2) * 24 + 16

    # ===== 30-DAY HEATMAP =====
    y = s.section(y, "Last 30 days", f"{d.streak}일 연속 활동 🔥")
    n = len(d.heatmap)
    cell_gap = 5
    cell = (INNER - cell_gap * (n - 1)) / n
    for i, (date, sec, level) in enumerate(d.heatmap):
        hx = PAD + i * (cell + cell_gap)
        s.rect(hx, y, cell, cell, HEAT_SCALE[level], r=3)
    y += cell + 12
    # legend
    s.text(PAD, y + 8, "Less", 10, FAINT, 500, MONO)
    lx = PAD + 34
    for lv in range(5):
        s.rect(lx, y, 11, 11, HEAT_SCALE[lv], r=3)
        lx += 15
    s.text(lx + 4, y + 8, "More", 10, FAINT, 500, MONO, anchor="start")

    y += 11 + 22
    # ===== FOOTER =====
    s.add(f'<line x1="{PAD}" y1="{y}" x2="{PAD + INNER}" y2="{y}" stroke="{DIV}"/>')
    y += 18
    owl = "저녁형" if d.late_night_pct < 25 else "새벽형"
    s.text(PAD, y, f"저는 {owl} 인간이에요 🦉 · 피크 {d.peak_hour_text} · 평균 {d.daily_avg_text}/day",
           11, MUTE, 500, MONO)
    s.text(PAD + INNER, y, "powered by WakaTime", 10, FAINT, 500, MONO, anchor="end")
    s.add(f'<path d="M{PAD + INNER - 118} {y - 9} l-2.2 8.6 -5.4 -4.2 4.2 5.4 -8.6 2.2 8.6 2.2 '
          f'-4.2 5.4 5.4 -4.2 2.2 8.6 2.2 -8.6 5.4 4.2 -4.2 -5.4 8.6 -2.2 -8.6 -2.2 4.2 -5.4 '
          f'-5.4 4.2z" fill="{FAINT}" transform="translate(0,0)"/>')

    height = y + 24
    return s.out(height).replace("@@H@@", f"{height - 2:.0f}")


def main():
    key = os.environ["WAKATIME_API_KEY"]
    today = None
    if os.environ.get("WAKA_TODAY"):
        today = dt.date.fromisoformat(os.environ["WAKA_TODAY"])
    data = collect(key, today)
    svg = render(data)
    out = os.environ.get("WAKA_OUT", "waka.svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {out} ({len(svg)} bytes, height in svg)")


if __name__ == "__main__":
    main()
