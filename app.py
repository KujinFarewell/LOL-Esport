from __future__ import annotations

import io
import math

import pandas as pd
import streamlit as st


REQUIRED_COLUMNS = {
    "blue", "red", "win", "duration",
    "kill_blue", "kill_red", "tower_blue", "tower_red",
    "dragon_blue", "dragon_red", "nashor_blue", "nashor_red",
    "first_kill", "first_tower",
}

# 按照指定优先级顺序排列指标（已移除水晶数，新增一血和一塔在单独模块或特定逻辑中展示）
STAT_COLUMNS = {
    "击杀数": ("kill_blue", "kill_red"),
    "推塔数": ("tower_blue", "tower_red"),
    "小龙数": ("dragon_blue", "dragon_red"),
    "大龙数": ("nashor_blue", "nashor_red"),
}


def team_name(value: object) -> str | None:
    """Return a usable team name, keeping blank Excel cells out of filters."""
    if pd.isna(value):
        return None
    name = str(value).strip()
    return name or None


@st.cache_data(show_spinner=False)
def read_matches(workbook_bytes: bytes) -> pd.DataFrame:
    """Load the match sheet and calculate a clean duration in seconds."""
    data = pd.read_excel(io.BytesIO(workbook_bytes), sheet_name="match")
    data.columns = [str(column).strip() for column in data.columns]
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"缺少必要列：{', '.join(sorted(missing))}")

    data["blue"] = data["blue"].map(team_name)
    data["red"] = data["red"].map(team_name)
    data["win"] = data["win"].map(team_name)
    data["first_kill"] = data["first_kill"].map(team_name)
    data["first_tower"] = data["first_tower"].map(team_name)
    
    for blue_column, red_column in STAT_COLUMNS.values():
        data[blue_column] = pd.to_numeric(data[blue_column], errors="coerce")
        data[red_column] = pd.to_numeric(data[red_column], errors="coerce")
        
    duration = pd.to_timedelta(data["duration"], errors="coerce")
    parts = duration.dt.components
    data["duration_seconds"] = ((parts["days"] * 24 + parts["hours"]) * 60 + parts["minutes"])
    data.loc[duration.isna(), "duration_seconds"] = pd.NA
    return data


def as_minutes_seconds(seconds: float | int | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def display_date(value: object) -> str:
    if pd.isna(value):
        return "—"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def available_teams(data: pd.DataFrame) -> list[str]:
    fields = [field for field in ("blue", "red", "team1", "team2") if field in data.columns]
    names = {team_name(value) for field in fields for value in data[field]}
    return sorted(name for name in names if name)


def matches_for_team(data: pd.DataFrame, team: str) -> pd.DataFrame:
    """Build one complete, side-aware record for every finished game of a team."""
    finished = data.loc[data["win"].notna() & data["duration_seconds"].notna()].copy()
    
    blue_games = finished.loc[finished["blue"].eq(team)].copy()
    blue_games["side"] = "蓝方"
    blue_games["opponent"] = blue_games["red"]
    blue_games["won"] = blue_games["win"].eq(team)
    blue_games["got_first_kill"] = blue_games["first_kill"].eq(team)
    blue_games["got_first_tower"] = blue_games["first_tower"].eq(team)
    
    for label, (blue_column, red_column) in STAT_COLUMNS.items():
        blue_games[label] = blue_games[blue_column]
        blue_games[f"总{label}"] = blue_games[blue_column] + blue_games[red_column]

    red_games = finished.loc[finished["red"].eq(team)].copy()
    red_games["side"] = "红方"
    red_games["opponent"] = red_games["blue"]
    red_games["won"] = red_games["win"].eq(team)
    red_games["got_first_kill"] = red_games["first_kill"].eq(team)
    red_games["got_first_tower"] = red_games["first_tower"].eq(team)
    
    for label, (blue_column, red_column) in STAT_COLUMNS.items():
        red_games[label] = red_games[red_column]
        red_games[f"总{label}"] = red_games[blue_column] + red_games[red_column]

    return pd.concat([blue_games, red_games], ignore_index=True)


def number_or_dash(value: float | int) -> str:
    return str(int(value)) if pd.notna(value) else "—"


def rate_or_dash(games: pd.DataFrame, column: str = "won") -> str:
    if games.empty or column not in games.columns:
        return "—"
    valid = games[column].dropna()
    return f"{valid.mean():.1%}" if not valid.empty else "—"


def mark_duration_outliers(matches: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Flag unusually long or short games with the IQR method when there are enough samples."""
    marked = matches.copy()
    marked["纳入平均"] = True
    valid = marked["duration_seconds"].dropna()
    if len(valid) < 6:
        return marked, "已完成比赛少于 6 场，暂不启用 IQR 异常值剔除。"

    lower_quartile, upper_quartile = valid.quantile([0.25, 0.75])
    iqr = upper_quartile - lower_quartile
    lower_bound = lower_quartile - 1.5 * iqr
    upper_bound = upper_quartile + 1.5 * iqr
    outlier = marked["duration_seconds"].lt(lower_bound) | marked["duration_seconds"].gt(upper_bound)
    marked.loc[outlier, "纳入平均"] = False
    excluded = int(outlier.sum())
    return marked, f"IQR 异常值剔除：已排除 {excluded} 场时长异常比赛（保留 {len(marked) - excluded}/{len(marked)} 场）。"


def average_or_dash(values: pd.Series) -> str:
    values = values.dropna()
    return f"{values.mean():.1f}" if not values.empty else "—"


def dashboard_table(matches: pd.DataFrame, team: str | None = None) -> pd.DataFrame:
    groups = {
        "整体": matches,
        "蓝方": matches.loc[matches["side"].eq("蓝方")],
        "红方": matches.loc[matches["side"].eq("红方")],
    }
    team_prefix = f"{team}" if team else "战队"
    rows = []
    rows.append({"指标": "纳入平均的场次", **{name: number_or_dash(len(group)) for name, group in groups.items()}})
    rows.append({"指标": "胜率", **{name: rate_or_dash(group, "won") for name, group in groups.items()}})
    rows.append({"指标": "一血率", **{name: rate_or_dash(group, "got_first_kill") for name, group in groups.items()}})
    rows.append({"指标": "一塔率", **{name: rate_or_dash(group, "got_first_tower") for name, group in groups.items()}})
    rows.append({
        "指标": "平均比赛时长",
        **{name: as_minutes_seconds(group["duration_seconds"].mean()) for name, group in groups.items()},
    })
    for metric in STAT_COLUMNS:
        rows.append({"指标": f"{team_prefix}{metric}", **{name: average_or_dash(group[metric]) for name, group in groups.items()}})
        rows.append({"指标": f"总{metric}", **{name: average_or_dash(group[f"总{metric}"]) for name, group in groups.items()}})
    return pd.DataFrame(rows)


def clean_team_matches(data: pd.DataFrame, team: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    all_matches, note = mark_duration_outliers(matches_for_team(data, team))
    return all_matches, all_matches.loc[all_matches["纳入平均"]].copy(), note


def smoothed_win_rate(matches: pd.DataFrame, side: str | None = None) -> float:
    sample = matches if side is None else matches.loc[matches["side"].eq(side)]
    if sample.empty and side is not None:
        sample = matches
    return (float(sample["won"].sum()) + 1) / (len(sample) + 2)


def duration_profile(matches: pd.DataFrame, side: str, fallback: pd.Series) -> tuple[float, float]:
    values = matches.loc[matches["side"].eq(side), "duration_seconds"].dropna()
    if values.empty:
        values = matches["duration_seconds"].dropna()
    if values.empty:
        values = fallback.dropna()
    mean = float(values.mean()) if not values.empty else 1800.0
    spread = float(values.std(ddof=1)) if len(values) > 1 else float(fallback.std(ddof=1))
    return mean, max(120.0, 0.0 if pd.isna(spread) else spread)


def metric_profile(matches: pd.DataFrame, side: str, metric: str, fallback: float) -> float:
    values = matches.loc[matches["side"].eq(side), metric].dropna()
    if values.empty:
        values = matches[metric].dropna()
    mean = float(values.mean()) if not values.empty else fallback
    return 0.0 if pd.isna(mean) else mean


def game_prediction(
    first: pd.DataFrame, second: pd.DataFrame, first_side: str, fallback_duration: pd.Series,
) -> tuple[float, float, float]:
    second_side = "红方" if first_side == "蓝方" else "蓝方"
    first_rate = smoothed_win_rate(first, first_side)
    second_rate = smoothed_win_rate(second, second_side)
    first_win_probability = max(0.05, min(0.95, 0.5 + (first_rate - second_rate) / 2))
    first_duration, first_spread = duration_profile(first, first_side, fallback_duration)
    second_duration, second_spread = duration_profile(second, second_side, fallback_duration)
    expected_duration = (first_duration + second_duration) / 2
    interval = max(120.0, math.sqrt(first_spread**2 + second_spread**2) / 2 * 1.28)
    return first_win_probability, expected_duration, interval


def series_distribution(probabilities: list[float], wins_needed: int) -> dict[str, float]:
    outcomes: dict[str, float] = {}

    def walk(game_index: int, first_wins: int, second_wins: int, probability: float) -> None:
        if first_wins == wins_needed or second_wins == wins_needed:
            outcomes[f"{first_wins}:{second_wins}"] = outcomes.get(f"{first_wins}:{second_wins}", 0) + probability
            return
        p = probabilities[game_index]
        walk(game_index + 1, first_wins + 1, second_wins, probability * p)
        walk(game_index + 1, first_wins, second_wins + 1, probability * (1 - p))

    walk(0, 0, 0, 1.0)
    return outcomes


def matchup_forecast(data: pd.DataFrame, first_team: str, second_team: str, first_blue: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    _, first, _ = clean_team_matches(data, first_team)
    _, second, _ = clean_team_matches(data, second_team)
    
    first_h2h = first.loc[first["opponent"] == second_team]
    second_h2h = second.loc[second["opponent"] == first_team]
    
    h2h_count = len(first_h2h)
    w_h2h = min(0.70, h2h_count * 0.15)
    w_gen = 1.0 - w_h2h

    completed_durations = data.loc[data["win"].notna() & data["duration_seconds"].notna(), "duration_seconds"]
    fallback_metrics = {
        label: float(pd.concat([data.loc[data["win"].notna() & data["duration_seconds"].notna(), blue], data.loc[data["win"].notna() & data["duration_seconds"].notna(), red]]).dropna().mean())
        for label, (blue, red) in STAT_COLUMNS.items()
    }
    
    blue_first = first_blue == first_team
    game_rows = []
    probabilities: list[float] = []
    
    for game_number in range(1, 6):
        first_side = "蓝方" if (game_number % 2 == 1) == blue_first else "红方"
        second_side = "红方" if first_side == "蓝方" else "蓝方"
        
        gen_prob, gen_duration, interval = game_prediction(first, second, first_side, completed_durations)
        
        if h2h_count > 0:
            h2h_prob = first_h2h["won"].mean()
            h2h_duration = first_h2h["duration_seconds"].mean()
            probability = w_h2h * h2h_prob + w_gen * gen_prob
            duration = w_h2h * h2h_duration + w_gen * gen_duration
        else:
            probability = gen_prob
            duration = gen_duration
            
        probabilities.append(probability)
        
        game_row = {
            "对局": f"第 {game_number} 局",
            "蓝方": first_team if first_side == "蓝方" else second_team,
            "预计时长": as_minutes_seconds(duration),
            "合理区间": f"{as_minutes_seconds(max(0, duration - interval))}–{as_minutes_seconds(duration + interval)}",
            f"{first_team} 胜率": f"{probability:.1%}",
            f"{second_team} 胜率": f"{1 - probability:.1%}",
        }
        
        for metric in STAT_COLUMNS:
            v1_gen = metric_profile(first, first_side, metric, fallback_metrics[metric])
            v2_gen = metric_profile(second, second_side, metric, fallback_metrics[metric])
            
            if h2h_count > 0:
                v1_h2h = metric_profile(first_h2h, first_side, metric, v1_gen)
                v2_h2h = metric_profile(second_h2h, second_side, metric, v2_gen)
                v1 = w_h2h * v1_h2h + w_gen * v1_gen
                v2 = w_h2h * v2_h2h + w_gen * v2_gen
            else:
                v1 = v1_gen
                v2 = v2_gen
                
            game_row[f"{first_team}预计{metric}"] = f"{v1:.1f}"
            game_row[f"{second_team}预计{metric}"] = f"{v2:.1f}"
            game_row[f"预计总{metric}"] = f"{v1 + v2:.1f}"
            
        game_rows.append(game_row)

    series_rows = []
    for label, wins_needed in (("BO1", 1), ("BO3", 2), ("BO5", 3)):
        outcomes = series_distribution(probabilities[: 2 * wins_needed - 1], wins_needed)
        first_total = sum(chance for score, chance in outcomes.items() if int(score.split(":")[0]) == wins_needed)
        second_total = 1 - first_total
        first_scores = "、".join(f"{score} {chance:.1%}" for score, chance in outcomes.items() if score.startswith(str(wins_needed) + ":"))
        second_scores = "、".join(f"{score} {chance:.1%}" for score, chance in outcomes.items() if score.endswith(":" + str(wins_needed)))
        series_rows.append({"赛制": label, f"{first_team} 系列赛胜率": f"{first_total:.1%}", f"{second_team} 系列赛胜率": f"{second_total:.1%}", f"{first_team} 比分概率": first_scores, f"{second_team} 比分概率": second_scores})

    evidence = f"预测样本：{first_team} {len(first)} 场、{second_team} {len(second)} 场。"
    if h2h_count > 0:
         evidence += f" 🛡️ 启用动态权重：混合 {h2h_count} 场历史交锋记录 (H2H 权重 {(w_h2h*100):.0f}%)。"
    if len(first) < 5 or len(second) < 5:
        evidence += " ⚠️ 样本较少，结果仅供参考。"
        
    return pd.DataFrame(game_rows), pd.DataFrame(series_rows), evidence


def calculate_diff(val1: str, val2: str, is_time: bool = False) -> str:
    if val1 == "—" or val2 == "—":
        return "—"
    try:
        if is_time:
            m1, s1 = map(int, val1.split(":"))
            m2, s2 = map(int, val2.split(":"))
            diff_sec = (m1 * 60 + s1) - (m2 * 60 + s2)
            sign = "+" if diff_sec > 0 else ("-" if diff_sec < 0 else "")
            abs_sec = abs(diff_sec)
            return f"{sign}{abs_sec // 60}:{abs_sec % 60:02d}"
        elif "%" in val1 and "%" in val2:
            f1 = float(val1.replace("%", ""))
            f2 = float(val2.replace("%", ""))
            diff = f1 - f2
            return f"{diff:+.1f}%"
        else:
            f1, f2 = float(val1), float(val2)
            diff = f1 - f2
            return f"{diff:+.1f}" if "." in val1 or "." in val2 else f"{int(diff):+d}"
    except ValueError:
        return "—"


def style_comparison(row):
    styles = pd.Series([''] * len(row), index=row.index)
    metric = row['指标']
    if metric in ['纳入平均的场次', '平均比赛时长'] or metric.startswith('总'):
        return styles

    t1_col, t2_col = row.index[1], row.index[2] 
    v1, v2 = str(row[t1_col]), str(row[t2_col])

    if v1 == '—' or v2 == '—':
        return styles

    try:
        if '%' in v1:
            f1 = float(v1.strip('%'))
            f2 = float(v2.strip('%'))
        else:
            f1 = float(v1)
            f2 = float(v2)

        highlight = 'color: #00c853; font-weight: bold;'
        if f1 > f2:
            styles[t1_col] = highlight
        elif f2 > f1:
            styles[t2_col] = highlight
    except:
        pass
        
    return styles


def render_team_dashboard(data: pd.DataFrame, selected: str) -> None:
    played, included, iqr_note = clean_team_matches(data, selected)
    wins = int(included["won"].sum())
    losses = len(included) - wins
    average_duration = included["duration_seconds"].mean() if not included.empty else None
    future = pd.DataFrame()
    if {"team1", "team2"}.issubset(data.columns):
        future = data.loc[data["win"].isna() & (data["team1"].eq(selected) | data["team2"].eq(selected))].copy()
    rate = f"{wins / len(included):.0%}" if len(included) else "—"
    
    first, second, third = st.columns(3)
    first.metric("胜率", rate, f"{wins} 胜 · {losses} 负" if len(played) else "暂无已完成对局")
    second.metric(f"{selected}击杀数", average_or_dash(included["击杀数"]) if not included.empty else "—", "纳入平均的每场数据")
    third.metric("平均比赛时长", as_minutes_seconds(average_duration), f"{len(future)} 场待赛")
    
    st.subheader("完整数据汇总")
    st.caption(iqr_note)
    if included.empty:
        st.info(f"{selected} 暂无已完成对局，赛果写入 Excel 后会自动计算全部指标。")
    else:
        st.dataframe(dashboard_table(included, selected), use_container_width=True, hide_index=True)
        
        # --- 新增：一血和一塔对胜负的影响关系展示 ---
        st.subheader("🎯 前期节奏与胜负影响关系")
        fk_games = included.dropna(subset=["got_first_kill"])
        ft_games = included.dropna(subset=["got_first_tower"])
        
        # 筛选出该队【实际拿到一血/一塔】的对局胜负情况
        fk_won = included.loc[included["got_first_kill"].eq(True), "won"]
        ft_won = included.loc[included["got_first_tower"].eq(True), "won"]
        
        # 若子集为空或均值为 NaN，直接显示 "—"；否则格式化显示百分比
        fk_win_rate_str = f"{fk_won.mean():.1%}" if not fk_won.empty and pd.notna(fk_won.mean()) else "—"
        ft_win_rate_str = f"{ft_won.mean():.1%}" if not ft_won.empty and pd.notna(ft_won.mean()) else "—"
        
        col_a, col_b = st.columns(2)
        col_a.metric(
            "拿到【一血】时的胜率", 
            fk_win_rate_str, 
            f"基于 {len(fk_games)} 场有效样本（触发 {len(fk_won)} 次）"
        )
        col_b.metric(
            "拿到【一塔】时的胜率", 
            ft_win_rate_str, 
            f"基于 {len(ft_games)} 场有效样本（触发 {len(ft_won)} 次）"
        )
        
        st.subheader("红蓝方胜率")
        st.bar_chart(included.groupby("side", sort=False)["won"].mean().reindex(["蓝方", "红方"]).fillna(0).mul(100).rename("胜率（%）"), y="胜率（%）")
        
    st.subheader("已完成对局")
    if played.empty:
        st.caption("暂无已完成对局")
    else:
        played["对手"] = played["opponent"]
        played["结果"] = played["won"].map({True: "胜", False: "负"})
        played["一血"] = played["got_first_kill"].map({True: "是", False: "否"})
        played["一塔"] = played["got_first_tower"].map({True: "是", False: "否"})
        played["时长"] = played["duration_seconds"].map(as_minutes_seconds)
        played["平均计算"] = played["纳入平均"].map({True: "纳入", False: "时长异常，剔除"})
        
        display_stats = []
        for metric in STAT_COLUMNS:
            display_stats.extend([f"总{metric}", metric])
            
        fields = [field for field in ("date", "event", "side", "对手", "结果", "一血", "一塔", "时长", *display_stats, "平均计算") if field in played.columns]
        result_table = played[fields].copy()
        if "date" in result_table:
            result_table["date"] = result_table["date"].map(display_date)
        rename_columns = {"date": "日期", "event": "赛事", "side": "方位", **{metric: f"{selected}{metric}" for metric in STAT_COLUMNS}}
        st.dataframe(result_table.rename(columns=rename_columns), use_container_width=True, hide_index=True)
        
    st.subheader("待赛赛程")
    if future.empty:
        st.caption("暂无待赛赛程")
    else:
        future["对阵"] = future["team1"].fillna("—") + " vs " + future["team2"].fillna("—")
        fields = [field for field in ("date", "event", "对阵", "stage") if field in future.columns]
        schedule_table = future[fields].copy()
        if "date" in schedule_table:
            schedule_table["date"] = schedule_table["date"].map(display_date)
        st.dataframe(schedule_table.rename(columns={"date": "日期", "event": "赛事", "stage": "阶段"}), use_container_width=True, hide_index=True)


def render_matchup_dashboard(data: pd.DataFrame, teams: list[str]) -> None:
    first_column, second_column = st.columns(2)
    
    # 动态获取 session_state 中保存的历史选择索引
    idx_a = teams.index(st.session_state["team_a"]) if st.session_state.get("team_a") in teams else None
    idx_b = teams.index(st.session_state["team_b"]) if st.session_state.get("team_b") in teams else None

    first_team = first_column.selectbox(
        "队伍 A", teams, index=idx_a, placeholder="请选择队伍 A", key="select_team_a"
    )
    st.session_state["team_a"] = first_team

    second_team = second_column.selectbox(
        "队伍 B", teams, index=idx_b, placeholder="请选择队伍 B", key="select_team_b"
    )
    st.session_state["team_b"] = second_team
    
    # 检查是否两支队伍都已选择
    if not first_team or not second_team:
        st.info("💡 请在上方选择两支队伍以生成对战预测。")
        return
        
    # 增加校验：防止用户在 A 和 B 中选择了同一支队伍
    if first_team == second_team:
        st.warning("⚠️ 队伍 A 和 队伍 B 不能相同，请选择两支不同的队伍！")
        return
        
    # 第 1 局蓝方选择及状态保留
    blue_options = [first_team, second_team]
    idx_blue = blue_options.index(st.session_state["first_blue"]) if st.session_state.get("first_blue") in blue_options else None

    first_blue = st.selectbox(
        "第 1 局蓝方", blue_options, index=idx_blue, placeholder="请选择首局蓝方队伍", key="select_first_blue"
    )
    st.session_state["first_blue"] = first_blue
    
    if not first_blue:
        st.info("💡 请选择首局位于蓝方的队伍以查看完整数据。")
        return
    
    h2h_condition = (
        ((data["blue"] == first_team) & (data["red"] == second_team)) |
        ((data["blue"] == second_team) & (data["red"] == first_team))
    )
    h2h_matches = data.loc[h2h_condition & data["win"].notna() & data["duration_seconds"].notna()].copy()

    st.markdown("---")
    st.subheader(f"⚔️ {first_team} vs {second_team} 历史交锋记录 (H2H)")
    
    if h2h_matches.empty:
        st.info("📊 暂无这两支战队的直接交手记录，预测将100%参照基础常规数据。")
    else:
        first_wins = (h2h_matches["win"] == first_team).sum()
        second_wins = (h2h_matches["win"] == second_team).sum()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("交手总场次", f"{len(h2h_matches)} 场")
        col2.metric(f"{first_team} 胜场", f"{first_wins} 胜")
        col3.metric(f"{second_team} 胜场", f"{second_wins} 胜")
        
        h2h_display = h2h_matches.copy()
        h2h_display["胜者"] = h2h_display["win"]
        h2h_display["时长"] = h2h_display["duration_seconds"].map(as_minutes_seconds)
        
        display_fields = ["date", "event", "blue", "red", "胜者", "时长"]
        h2h_display = h2h_display[[f for f in display_fields if f in h2h_display.columns]]
        
        if "date" in h2h_display.columns:
            h2h_display["date"] = h2h_display["date"].map(display_date)
            
        h2h_display = h2h_display.rename(columns={
            "date": "日期", "event": "赛事", "blue": "蓝方", "red": "红方"
        })
        
        st.dataframe(h2h_display, use_container_width=True, hide_index=True)

    game_table, series_table, evidence = matchup_forecast(data, first_team, second_team, first_blue)
    first_matches = clean_team_matches(data, first_team)[1]
    second_matches = clean_team_matches(data, second_team)[1]
    
    st.markdown("---")
    st.subheader("整体数据对比")
    
    table1 = dashboard_table(first_matches, first_team)[["指标", "整体"]].rename(columns={"整体": first_team})
    table2 = dashboard_table(second_matches, second_team)[["指标", "整体"]].rename(columns={"整体": second_team})
    
    table1["通用指标"] = table1["指标"].apply(lambda x: x.replace(first_team, "") if x.startswith(first_team) else x)
    table2["通用指标"] = table2["指标"].apply(lambda x: x.replace(second_team, "") if x.startswith(second_team) else x)
    
    comparison = table1.merge(table2, on="通用指标", how="outer", suffixes=("", "_drop"))
    
    ordered_metrics = ["纳入平均的场次", "胜率", "一血率", "一塔率", "平均比赛时长"]
    for m in STAT_COLUMNS:
        ordered_metrics.extend([m, f"总{m}"])
    
    comparison["指标"] = comparison["通用指标"]
    comparison = comparison[["指标", first_team, second_team]]
    
    comparison['sort_key'] = comparison['指标'].apply(lambda x: ordered_metrics.index(x) if x in ordered_metrics else 999)
    comparison = comparison.sort_values('sort_key').drop(columns=['sort_key']).reset_index(drop=True)
    
    diffs = []
    for _, row in comparison.iterrows():
        is_time = row["指标"] == "平均比赛时长"
        diffs.append(calculate_diff(str(row[first_team]), str(row[second_team]), is_time=is_time))
    
    comparison[f"差异 ({first_team} - {second_team})"] = diffs
    
    styled_comparison = comparison.style.apply(style_comparison, axis=1)
    st.dataframe(styled_comparison, use_container_width=True, hide_index=True)
    
    st.subheader("单局混合预测")
    st.caption(evidence + " (蓝红方按每局轮换；第 3–5 局仅在需要时进行)")
    st.dataframe(game_table, use_container_width=True, hide_index=True)
    
    st.subheader("BO1、BO3、BO5 系列赛预测")
    st.dataframe(series_table, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="LOL 战队数据看板", page_icon="🎮", layout="wide")
    st.title("LOL 战队数据看板")
    st.caption("上传更新后的 Excel，即可查看战队数据、交手记录和 BO 系列赛动态预测。")
    
    # 初始化全局战队选择状态（首次启动全为 None，即置空）
    for state_key in ["selected_team", "team_a", "team_b", "first_blue"]:
        if state_key not in st.session_state:
            st.session_state[state_key] = None

    uploaded = st.file_uploader("选择比赛数据 Excel", type=["xlsx"])
    if uploaded is None:
        st.info("请选择包含 `match` 工作表的 Excel 文件。")
        return
    try:
        data = read_matches(uploaded.getvalue())
    except Exception as error:
        st.error(f"无法读取文件：{error}")
        return
    teams = available_teams(data)
    if not teams:
        st.warning("文件中没有可识别的战队名称。")
        return
    mode = st.radio("查看方式", ["单队数据", "对战预测"], horizontal=True)
    
    if mode == "单队数据":
        # 获取单队历史选择索引
        idx_single = teams.index(st.session_state["selected_team"]) if st.session_state.get("selected_team") in teams else None
        
        selected = st.selectbox("选择战队", teams, index=idx_single, placeholder="请选择战队", key="select_single_team")
        st.session_state["selected_team"] = selected
        
        if selected:
            render_team_dashboard(data, selected)
        else:
            st.info("💡 请在上方下拉框中选择一支战队以查看单队数据。")
    else:
        render_matchup_dashboard(data, teams)

if __name__ == "__main__":
    main()
