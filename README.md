# LOL 战队数据看板

这是一个本地运行的 Python 小应用。每次更新 Excel 后，重新上传文件即可刷新完整的战队数据看板：整体、蓝方和红方的胜率、每场平均击杀、推塔、inhibitor、小龙、nashor 与平均比赛时长。

当某战队已有至少 6 场已完成比赛时，应用会对比赛时长使用 IQR 方法识别异常值；被判定异常的比赛不会计入所有平均指标，并会在逐场明细中标注。

## 对战预测

选择“对战预测”后，可任意选择两支战队并指定第一局蓝方。应用会展示双方历史数据对比、每局的胜率、预计时长与资源数据，以及 BO1、BO3、BO5 的系列赛胜率和比分概率。预测会随着 Excel 中新增的历史赛果自动更新；样本较少时会提示仅供参考。

## 首次安装

在此文件夹打开终端，执行：

```bash
python3 -m pip install -r requirements.txt
```

## 启动

```bash
python3 -m streamlit run app.py
```

浏览器会自动打开。点击“选择比赛数据 Excel”，选择你的 `LOL Esport.xlsx`。

## Excel 数据要求

工作表名称必须为 `match`，并至少包含以下列：

- `blue`：蓝色方战队
- `red`：红色方战队
- `win`：获胜战队
- `duration`：比赛时长
- `kill_blue` / `kill_red`：蓝方 / 红方击杀数
- `tower_blue` / `tower_red`：蓝方 / 红方推塔数
- `inhibitor_blue` / `inhibitor_red`：蓝方 / 红方 inhibitor 数
- `dragon_blue` / `dragon_red`：蓝方 / 红方小龙数
- `nashor_blue` / `nashor_red`：蓝方 / 红方 nashor 数

如果还包含 `team1` 与 `team2`，应用会同时展示尚未有赛果的待赛赛程。
