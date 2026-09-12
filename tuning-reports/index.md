# 调优报告索引

| 迭代号 | 日期 | commit | 手段摘要 | 前/后 p3+p4 均值虚拟时间 | 结论 | 报告文件 |
|---|---|---|---|---|---|---|
| iter-001 | 2026-09-12 | 9f24cd1 | 动态清除插入 + 极小极大追加选点 + p3 no_signal 更新 | p3: 8216.5→4665.8；p4: 17791.5→11280.8（s） | 100% 清除保持；p3 −43.2%、p4 −36.6%；VAL 无过拟合 | [iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md](iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md) |
| iter-002 | 2026-09-12 | 7173ce4 | p4 认证稀疏覆盖网（29 点@870m+极点+NN 巡回）+ 定向源结构化探针（行进线/双侧横向/同侧罚分） | p3: 4665.8→4665.8；p4: 11280.8→8858.4（s） | 100% 清除保持（修复 attempt1 两种漏清模式）；p4 −21.5%，累计 −50.2%；VAL −23.3% 无过拟合 | [iter-002-sparse-certified-coverage-and-directional-probes.md](iter-002-sparse-certified-coverage-and-directional-probes.md) |
