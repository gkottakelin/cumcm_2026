# 基准集定义（benchmark v1）

固定基准集用于所有调优迭代的"调优前 / 调优后"配对比较。相同 seed 生成完全相同的案例
（频道、位置、接收半径、源类型、发射方向、示向误差），前后对比天然消除案例随机性。
**一旦固定，不得中途更换案例；确需更换时版本号 +1 并重新采集全部基线。**

## BENCH（基准集，v1）

| 项 | 值 |
|---|---|
| 组成 | 问题 3、问题 4 各 50 个案例 |
| 问题 3 命令 | `uv run python python-code\run_local_regression.py --problem 3 --cases 50 --seed 900000 --output out\bench\iter-NNN-p3.json` |
| 问题 4 命令 | `uv run python python-code\run_local_regression.py --problem 4 --cases 50 --seed 900000 --output out\bench\iter-NNN-p4.json` |
| 实际案例种子 | p3: 1200000..1200049；p4: 1300000..1300049（base 900000 + 问题号×100000 + 序号） |
| 存放 | `out\bench\`（`out/` 已 gitignore，原始数据只留本地，统计数字写入调优报告） |
| p3 案例构成 | source_count = rng.integers(10,17)（10~16 个全向源），directional = 0 |
| p4 案例构成 | source_count = 16（其中 5 个定向、11 个全向） |

## VAL（验证集，v1，防过拟合）

| 项 | 值 |
|---|---|
| 组成 | 问题 3、问题 4 各 20 个案例 |
| 命令 | 同上，`--seed 700000 --cases 20`，输出 `out\bench\iter-NNN-val-pX.json` |
| 实际案例种子 | p3: 1000000..1000019；p4: 1100000..1100019 |
| 使用规则 | 重大算法改动（更换策略/目标函数）必须跑；参数微调可免。基准集提升但验证集回退 ⇒ 判定过拟合，如实记录并回退或调整 |

## 统计纪律

1. 调优前/后性能必须来自基准集完整运行的聚合统计，禁止用单案例或少量 seed 代表性能。
2. 每份性能数据同时记录：PASS 率、清除率、`virtual_time_s` 均值 ± 标准差与最坏值、
   总移动距离、有效指令数（从报告 JSON 的 `results[].statistics` 聚合）。
3. 改进量小于 1 个标准差视为噪声水平，结论记"无显著改进"。
4. 单案例 FAIL 先用同 seed 复跑确认可复现，再进入根因分析。
5. 临时探索（复现个案、试参数）可用任意 seed 小规模跑，其结果只用于形成假设，
   不得写进调优前/后性能表。
