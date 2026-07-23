from __future__ import annotations

import io
import math

import pandas as pd
import streamlit as st


REQUIRED_COLUMNS = {
    "blue", "red", "win", "duration",
    "kill_blue", "kill_red", "tower_blue", "tower_red",
    "inhibitor_blue", "inhibitor_red", "dragon_blue", "dragon_red",
    "nashor_blue", "nashor_red",
}

STAT_COLUMNS = {
    "击杀数": ("kill_blue", "kill_red"),
    "推塔数": ("tower_blue", "tower_red"),
    "inhibitor 数": ("inhibitor_blue", "inhibitor_red"),
    "小龙数": ("dragon_blue", "dragon_red"),
    "nashor 数": ("nashor_blue", "nashor_red"),
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
    for blue_column, red_column in STAT_COLUMNS.values():
        data[blue_column] = pd.to_numeric(data[blue_column], errors="coerce").fillna(0)
        data[red_column] = pd.to_numeric(data[red_column], errors="coerce").fillna(0)
    duration = pd.to_timedelta(data["duration"], errors="coerce")
    # 当前数据表把“30:22”这类 mm:ss 时长读取为“1 天 6:22”。
    # 将累计小时视作分钟、分钟视作秒，即可还原原始比赛时长。
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
    finished = data.loc[data["win"].notna()].copy()
    blue_games = finished.loc[finished["blue"].eq(team)].copy()
    blue_games["side"] = "蓝方"
    blue_games["opponent"] = blue_games["red"]
    blue_games["won"] = blue_games["win"].eq(team)
    for label, (blue_column, _) in STAT_COLUMNS.items():
        blue_games[label] = blue_games[blue_column]

    red_games = finished.loc[finished["red"].eq(team)].copy()
    red_games["side"] = "红方"
    red_games["opponent"] = red_games["blue"]
    red_games["won"] = red_games["win"].eq(team)
    for label, (_, red_column) in STAT_COLUMNS.items():
        red_games[label] = red_games[red_column]

    return pd.concat([blue_games, red_games], ignore_index=True)


def number_or_dash(value: float | int) -> str:
    return str(int(value)) if pd.notna(value) else "—"


def rate_or_dash(games: pd.DataFrame) -> str:
    return f"{games['won'].mean():.1%}" if not games.empty else "—"


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


def dashboard_table(matches: pd.DataFrame) -> pd.DataFrame:
    groups = {
        "整体": matches,
        "蓝方": matches.loc[matches["side"].eq("蓝方")],
        "红方": matches.loc[matches["side"].eq("红方")],
    }
    rows = []
    rows.append({"指标": "纳入平均的场次", **{name: number_or_dash(len(group)) for name, group in groups.items()}})
    rows.append({"指标": "胜率", **{name: rate_or_dash(group) for name, group in groups.items()}})
    for metric in STAT_COLUMNS:
        rows.append({"指标": f"平均{metric}", **{name: f"{group[metric].mean():.1f}" if not group.empty else "—" for name, group in groups.items()}})
    rows.append({
        "指标": "平均比赛时长",
        **{name: as_minutes_seconds(group["duration_seconds"].mean()) for name, group in groups.items()},
    })
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
    values = matches.loc[matches["side"].eq(side), metric]
    if values.empty:
        values = matches[metric]
    return float(values.mean()) if not values.empty else fallback


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
    completed_durations = data.loc[data["win"].notna(), "duration_seconds"]
    fallback_metrics = {
        label: float(pd.concat([data.loc[data["win"].notna(), blue], data.loc[data["win"].notna(), red]]).mean())
        for label, (blue, red) in STAT_COLUMNS.items()
    }
    blue_first = first_blue == first_team
    game_rows = []
    probabilities: list[float] = []
    for game_number in range(1, 6):
        first_side = "蓝方" if (game_number % 2 == 1) == blue_first else "红方"
        second_side = "红方" if first_side == "蓝方" else "蓝方"
        probability, duration, interval = game_prediction(first, second, first_side, completed_durations)
        probabilities.append(probability)
        game_row = {
            "对局": f"第 {game_number} 局",
            "蓝方": first_team if first_side == "蓝方" else second_team,
            f"{first_team} 胜率": f"{probability:.1%}",
            f"{second_team} 胜率": f"{1 - probability:.1%}",
            "预计时长": as_minutes_seconds(duration),
            "合理区间": f"{as_minutes_seconds(max(0, duration - interval))}–{as_minutes_seconds(duration + interval)}",
        }
        for metric in STAT_COLUMNS:
            game_row[f"{first_team} 预计{metric}"] = f"{metric_profile(first, first_side, metric, fallback_metrics[metric]):.1f}"
            game_row[f"{second_team} 预计{metric}"] = f"{metric_profile(second, second_side, metric, fallback_metrics[metric]):.1f}"
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
    if len(first) < 5 or len(second) < 5:
        evidence += " 样本较少，结果仅供参考。"
    return pd.DataFrame(game_rows), pd.DataFrame(series_rows), evidence


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
    second.metric("平均击杀数", f"{included['击杀数'].mean():.1f}" if not included.empty else "—", "每场比赛")
    third.metric("平均比赛时长", as_minutes_seconds(average_duration), f"{len(future)} 场待赛")
    st.subheader("完整数据汇总")
    st.caption(iqr_note)
    if included.empty:
        st.info(f"{selected} 暂无已完成对局，赛果写入 Excel 后会自动计算全部指标。")
    else:
        st.dataframe(dashboard_table(included), use_container_width=True, hide_index=True)
        st.subheader("红蓝方胜率")
        st.bar_chart(included.groupby("side", sort=False)["won"].mean().reindex(["蓝方", "红方"]).fillna(0).mul(100).rename("胜率（%）"), y="胜率（%）")
    st.subheader("已完成对局")
    if played.empty:
        st.caption("暂无已完成对局")
    else:
        played["对手"] = played["opponent"]
        played["结果"] = played["won"].map({True: "胜", False: "负"})
        played["时长"] = played["duration_seconds"].map(as_minutes_seconds)
        played["平均计算"] = played["纳入平均"].map({True: "纳入", False: "时长异常，剔除"})
        fields = [field for field in ("date", "event", "side", "对手", "结果", "时长", *STAT_COLUMNS.keys(), "平均计算") if field in played.columns]
        result_table = played[fields].copy()
        if "date" in result_table:
            result_table["date"] = result_table["date"].map(display_date)
        st.dataframe(result_table.rename(columns={"date": "日期", "event": "赛事", "side": "方位"}), use_container_width=True, hide_index=True)
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
    first_team = first_column.selectbox("队伍 A", teams, index=teams.index("DK") if "DK" in teams else 0)
    remaining = [team for team in teams if team != first_team]
    second_team = second_column.selectbox("队伍 B", remaining, index=remaining.index("T1") if "T1" in remaining else 0)
    first_blue = st.selectbox("第 1 局蓝方", [first_team, second_team])
    game_table, series_table, evidence = matchup_forecast(data, first_team, second_team, first_blue)
    first_matches = clean_team_matches(data, first_team)[1]
    second_matches = clean_team_matches(data, second_team)[1]
    st.subheader(f"{first_team} vs {second_team} 数据对比")
    comparison = dashboard_table(first_matches)[["指标", "整体"]].rename(columns={"整体": first_team})
    comparison[second_team] = dashboard_table(second_matches)["整体"]
    st.dataframe(comparison, use_container_width=True, hide_index=True)
    st.subheader("单局预测")
    st.caption(evidence + " 蓝红方按每局轮换计算；第 3–5 局仅在需要时进行。")
    st.dataframe(game_table, use_container_width=True, hide_index=True)
    st.subheader("BO1、BO3、BO5 系列赛预测")
    st.dataframe(series_table, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="LOL 战队数据看板", page_icon="🎮", layout="wide")
    st.title("LOL 战队数据看板")
    st.caption("上传更新后的 Excel，即可查看战队数据、对战比较和 BO 系列赛预测。")
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
        selected = st.selectbox("选择战队", teams, index=teams.index("T1") if "T1" in teams else 0)
        render_team_dashboard(data, selected)
    else:
        render_matchup_dashboard(data, teams)


if __name__ == "__main__":
    main()
