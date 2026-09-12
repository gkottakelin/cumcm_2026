# 调优报告索引

| 迭代号 | 日期 | commit | 手段摘要 | 前/后 p3+p4 均值虚拟时间 | 结论 | 报告文件 |
|---|---|---|---|---|---|---|
| iter-001 | 2026-09-12 | 9f24cd1 | 动态清除插入 + 极小极大追加选点 + p3 no_signal 更新 | p3: 8216.5→4665.8；p4: 17791.5→11280.8（s） | 100% 清除保持；p3 −43.2%、p4 −36.6%；VAL 无过拟合 | [iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md](iter-001-dynamic-clear-scheduling-and-minimax-viewpoints.md) |
| iter-002 | 2026-09-12 | 7173ce4 | p4 认证稀疏覆盖网（29 点@870m+极点+NN 巡回）+ 定向源结构化探针（行进线/双侧横向/同侧罚分） | p3: 4665.8→4665.8；p4: 11280.8→8858.4（s） | 100% 清除保持（修复 attempt1 两种漏清模式）；p4 −21.5%，累计 −50.2%；VAL −23.3% 无过拟合 | [iter-002-sparse-certified-coverage-and-directional-probes.md](iter-002-sparse-certified-coverage-and-directional-probes.md) |
| iter-003 | 2026-09-12 | 931ecad | p4 覆盖巡回 16 源检出即停（题面固定源数，检出满 16 跳过剩余巡回点） | p3: 4665.8→4665.8；p4: 8858.4→6978.2（s） | 100% 清除保持；p4 −21.2%，累计 −60.8%；VAL −22.4% 无过拟合；p3 零回归 | [iter-003-early-stop-at-known-source-count.md](iter-003-early-stop-at-known-source-count.md) |
| iter-004 | 2026-09-12 | e2aeda4 | 安全清除阈值 18→19.5 m（数学等价安全，提前终止追加测量） | p3: 4665.8→4591.0；p4: 6978.2→6763.3（s） | 100% 清除保持；p3 −1.6%、p4 −3.1%（小幅稳定，符号检验显著）；累计 p3 −44.1%、p4 −62.0% | [iter-004-raise-safe-clear-threshold.md](iter-004-raise-safe-clear-threshold.md) |
| iter-005 | 2026-09-12 | a28b102 | p4 内环先行巡回 + 追加探针三重缺陷修复（短锚点/行进括号/共线罚分/同侧计数） | p3: 4591.0→4590.7；p4: 6763.3→6222.3（s） | 100% 清除保持；p4 −8.0%（37/50 改善）；累计 p3 −44.1%、p4 −65.0%；VAL −1.7% 无过拟合 | [iter-005-inner-first-tour-and-probe-robustness.md](iter-005-inner-first-tour-and-probe-robustness.md) |
| iter-006 | 2026-09-12 | cf55a97 | 覆盖后阶段 2-opt 任务排序（选择性续巡负结果已回退：+599 s） | p3: 4590.7→4541.7；p4: 6222.3→6151.1（s） | 100% 清除保持；两问各 −1.1%（方向高度一致）；累计 p3 −44.7%、p4 −65.4%；VAL 无过拟合 | [iter-006-post-tour-2opt-ordering.md](iter-006-post-tour-2opt-ordering.md) |
