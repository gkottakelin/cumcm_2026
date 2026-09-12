# 调优报告索引

| 迭代号 | 日期 | commit | 手段摘要 | 前/后 p3+p4 均值虚拟时间 | 结论 | 报告文件 |
|---|---|---|---|---|---|---|
| iter-001 | 2026-09-12 | 9f24cd1 | 动态清除插入 + 极小极大追加选点 + p3 no_signal 更新 | p3: 8216.5→4665.8；p4: 17791.5→11280.8（s） | 100% 清除保持；p3 −43.2%、p4 −36.6%；VAL 无过拟合 | [iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md](iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md) |
