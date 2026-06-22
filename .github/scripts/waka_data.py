"""WakaTime 데이터 수집·계산 레이어. SVG 렌더와 분리.

무료 API만 사용:
  - GET /users/current/stats/last_7_days
  - GET /users/current/summaries (최근 30일)  → 스트릭·히트맵·주간시간
  - GET /users/current/durations?date=...      → 시간대 버킷·첫/마지막·최장세션·지난주 AI량
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

API = "https://wakatime.com/api/v1/users/current"

# ---------- redaction ----------
# 민감 식별자는 코드에 박지 않는다.
#   1) 숫자 ID(5자리+)는 제네릭 정규식으로 자동 마스킹
#   2) 도메인성 단어는 WAKA_REDACT 시크릿(콤마구분)에서 주입받아 매칭
_DIGIT_RUN = re.compile(r"\d{5,}")


def _mask_token(s: str) -> str:
    s = str(s)
    if len(s) <= 2:
        return (s[0] + "*") if s else s
    if len(s) <= 4:
        return s[0] + "*" * (len(s) - 2) + s[-1]
    return s[:2] + "*" * (len(s) - 3) + s[-1]


def _deny_terms() -> list[str]:
    return [t.strip().lower() for t in os.environ.get("WAKA_REDACT", "").split(",") if t.strip()]


def _redact(name: str, deny: list[str]) -> str:
    low = name.lower()
    for term in deny:
        if term and term in low:
            return _mask_token(name)
    return _DIGIT_RUN.sub(lambda m: _mask_token(m.group()), name)


def _get(path: str, key: str) -> dict:
    token = base64.b64encode(f"{key}:".encode()).decode()
    req = urllib.request.Request(API + path, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# ---------- buckets ----------
TIME_BUCKETS = [
    ("새벽", "🌙", 0, 6),
    ("아침", "🌅", 6, 12),
    ("낮", "☀️", 12, 18),
    ("저녁", "🌆", 18, 22),
    ("밤", "🌃", 22, 24),
]
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


@dataclass
class WakaData:
    raw_stats: dict = field(default_factory=dict)
    tz: str = "Asia/Seoul"

    # 헤더
    total_text: str = ""
    daily_avg_text: str = ""
    range_text: str = ""

    # AI 핵심
    ai_coding_pct: float = 0.0
    ai_lines: int = 0
    human_lines: int = 0
    ai_additions: int = 0
    ai_deletions: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost: float = 0.0
    sessions: int = 0
    prompts: int = 0
    prompt_len_avg: int = 0
    prompts_per_session: float = 0.0

    # 파생
    lines_per_prompt: float = 0.0
    lines_per_hour: float = 0.0

    # 분포 (name, pct, text)
    languages: list = field(default_factory=list)
    editors: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    machines: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    agents: list = field(default_factory=list)  # (name, lines, cost)

    # 시간대 (label, emoji, seconds, pct)
    time_of_day: list = field(default_factory=list)
    hour_hist: list = field(default_factory=list)
    peak_hour: int = 0
    peak_hour_text: str = ""
    late_night_pct: float = 0.0
    longest_session_text: str = ""

    # 요일 (label, seconds, pct, is_peak)
    weekdays: list = field(default_factory=list)
    peak_weekday: str = ""
    best_day_text: str = ""

    # 스트릭·히트맵
    streak: int = 0
    heatmap: list = field(default_factory=list)  # [(date, seconds, level0-4)]

    # 주간 비교 (this, last, delta_pct)
    wow_time: tuple = (0.0, 0.0, 0.0)
    wow_ai_lines: tuple = (0, 0, 0.0)
    wow_tokens: tuple = (0, 0, 0.0)


def _hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _pct_delta(cur: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return (cur - prev) / prev * 100.0


def collect(key: str, today: dt.date | None = None) -> WakaData:
    d = WakaData()
    stats = _get("/stats/last_7_days", key)["data"]
    d.raw_stats = stats
    d.tz = stats.get("timezone") or "Asia/Seoul"
    tz = ZoneInfo(d.tz)
    today = today or dt.datetime.now(tz).date()

    # ----- 헤더/핵심 -----
    d.total_text = stats.get("human_readable_total", "")
    d.daily_avg_text = stats.get("human_readable_daily_average", "")
    d.range_text = stats.get("human_readable_range", "last 7 days")
    cats = {c["name"]: c["percent"] for c in stats.get("categories", [])}
    d.ai_coding_pct = cats.get("AI Coding", 0.0)
    d.ai_lines = int(stats.get("ai_line_changes_total") or 0)
    d.ai_additions = int(stats.get("ai_additions") or 0)
    d.ai_deletions = int(stats.get("ai_deletions") or 0)
    d.human_lines = int(stats.get("human_additions") or 0) + int(stats.get("human_deletions") or 0)
    d.tokens_in = int(stats.get("ai_input_tokens") or 0)
    d.tokens_out = int(stats.get("ai_output_tokens") or 0)
    d.est_cost = float(stats.get("ai_agent_total_cost") or 0.0)
    d.sessions = int(stats.get("ai_sessions") or 0)
    d.prompts = int(stats.get("ai_prompt_events_total") or 0)
    d.prompt_len_avg = int(stats.get("ai_prompt_length_avg") or 0)
    d.prompts_per_session = float(stats.get("ai_prompt_events_avg_per_session") or 0)

    total_seconds = float(stats.get("total_seconds") or 0)
    d.lines_per_prompt = d.ai_lines / d.prompts if d.prompts else 0.0
    d.lines_per_hour = d.ai_lines / (total_seconds / 3600) if total_seconds else 0.0

    deny = _deny_terms()

    def dist(name, n, redact=False):
        out = []
        for x in stats.get(name, [])[:n]:
            nm = _redact(x["name"], deny) if redact else x["name"]
            out.append((nm, x.get("percent", 0.0), x.get("text", "")))
        return out

    d.languages = dist("languages", 5)
    d.editors = dist("editors", 4)
    d.projects = dist("projects", 5, redact=True)
    d.machines = dist("machines", 3, redact=True)
    d.dependencies = dist("dependencies", 6, redact=True)
    d.agents = [(a["name"], int(a.get("lines", 0)), float(a.get("cost", 0.0)))
                for a in stats.get("ai_agent_breakdown", [])]

    d.best_day_text = ""
    bd = stats.get("best_day")
    if bd:
        bdate = dt.date.fromisoformat(bd["date"])
        d.best_day_text = f"{WEEKDAY_KO[bdate.weekday()]}요일 · {bd.get('text','')}"

    # ----- 30일 summaries: 스트릭/히트맵/주간시간 -----
    start30 = today - dt.timedelta(days=29)
    summ = _get(f"/summaries?start={start30}&end={today}", key).get("data", [])
    day_secs: dict[str, float] = {}
    for s in summ:
        day_secs[s["range"]["date"]] = float(s["grand_total"]["total_seconds"])

    # 스트릭: 가장 최근 날부터 연속 활동일
    streak = 0
    cur = today
    while True:
        sec = day_secs.get(cur.isoformat(), 0.0)
        if sec <= 0:
            # 오늘이 0이면 어제부터 시작 허용
            if cur == today:
                cur -= dt.timedelta(days=1)
                continue
            break
        streak += 1
        cur -= dt.timedelta(days=1)
    d.streak = streak

    # 히트맵: 최근 30일
    maxsec = max(day_secs.values()) if day_secs else 0.0
    hm = []
    for i in range(29, -1, -1):
        day = today - dt.timedelta(days=i)
        sec = day_secs.get(day.isoformat(), 0.0)
        level = 0 if sec <= 0 else min(4, 1 + int((sec / maxsec) * 3.999)) if maxsec else 0
        hm.append((day.isoformat(), sec, level))
    d.heatmap = hm

    # 요일 합산 (30일)
    wd_secs = [0.0] * 7
    for ds, sec in day_secs.items():
        wd_secs[dt.date.fromisoformat(ds).weekday()] += sec
    wd_max = max(wd_secs) if any(wd_secs) else 1.0
    wd_total = sum(wd_secs) or 1.0
    peak_i = wd_secs.index(max(wd_secs))
    d.weekdays = [(WEEKDAY_KO[i], wd_secs[i], wd_secs[i] / wd_total * 100, i == peak_i)
                  for i in range(7)]
    d.peak_weekday = WEEKDAY_KO[peak_i]

    # 주간 시간 비교 (이번 7일 vs 이전 7일)
    def sum_range(a: dt.date, b: dt.date) -> float:
        return sum(day_secs.get((a + dt.timedelta(days=k)).isoformat(), 0.0)
                   for k in range((b - a).days + 1))
    this_a, this_b = today - dt.timedelta(days=6), today
    last_a, last_b = today - dt.timedelta(days=13), today - dt.timedelta(days=7)
    t_now, t_prev = sum_range(this_a, this_b), sum_range(last_a, last_b)
    d.wow_time = (t_now, t_prev, _pct_delta(t_now, t_prev))

    # ----- durations: 시간대/첫·마지막/최장세션 (이번주) + 지난주 AI량 -----
    def durations_for(days: list[dt.date]) -> list[dict]:
        rows = []
        for day in days:
            try:
                rows += _get(f"/durations?date={day.isoformat()}", key).get("data", [])
            except Exception:
                pass
        return rows

    this_days = [this_a + dt.timedelta(days=k) for k in range(7)]
    last_days = [last_a + dt.timedelta(days=k) for k in range(7)]
    this_dur = durations_for(this_days)

    bucket_secs = [0.0] * len(TIME_BUCKETS)
    hour_hist = [0.0] * 24
    longest = 0.0
    for row in this_dur:
        start = float(row.get("time") or 0)
        dur = float(row.get("duration") or 0)
        if start <= 0:
            continue
        local = dt.datetime.fromtimestamp(start, tz)
        hour = local.hour
        hour_hist[hour] += dur
        for bi, (_, _, h0, h1) in enumerate(TIME_BUCKETS):
            if h0 <= hour < h1:
                bucket_secs[bi] += dur
                break
        longest = max(longest, dur)
    bsum = sum(bucket_secs) or 1.0
    d.time_of_day = [(TIME_BUCKETS[i][0], TIME_BUCKETS[i][1], bucket_secs[i],
                      bucket_secs[i] / bsum * 100) for i in range(len(TIME_BUCKETS))]
    d.longest_session_text = _hms(longest)
    d.hour_hist = hour_hist
    peak_h = hour_hist.index(max(hour_hist)) if any(hour_hist) else 0
    d.peak_hour = peak_h
    d.peak_hour_text = f"{peak_h:02d}:00–{(peak_h + 1) % 24:02d}:00"
    # 새벽(0-6) 코딩 비중 = night-owl 지표
    d.late_night_pct = d.time_of_day[0][3]

    # 지난주 AI 라인/토큰 (durations 합산) — WoW용
    def ai_sum(rows):
        lines = sum(int(r.get("ai_additions") or 0) + int(r.get("ai_deletions") or 0) for r in rows)
        tin = sum(int(r.get("ai_input_tokens") or 0) for r in rows)
        tout = sum(int(r.get("ai_output_tokens") or 0) for r in rows)
        return lines, tin, tout
    last_dur = durations_for(last_days)
    cur_lines, cur_tin, cur_tout = ai_sum(this_dur)
    prev_lines, prev_tin, prev_tout = ai_sum(last_dur)
    d.wow_ai_lines = (cur_lines, prev_lines, _pct_delta(cur_lines, prev_lines))
    d.wow_tokens = (cur_tin + cur_tout, prev_tin + prev_tout,
                    _pct_delta(cur_tin + cur_tout, prev_tin + prev_tout))

    return d


if __name__ == "__main__":
    key = os.environ["WAKATIME_API_KEY"]
    data = collect(key)
    import pprint
    out = {k: v for k, v in data.__dict__.items() if k != "raw_stats"}
    pprint.pprint(out, width=120, sort_dicts=False)
