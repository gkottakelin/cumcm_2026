# 无线电干扰源环境模拟器测试工作流

## 1. 适用范围

本文记录问题 3（全向干扰源）和问题 4（定向干扰源）的本地演练流程。当前客户端入口为：

```text
python-code/simulator_client.py
```

客户端只连接本机模拟器，不保存队号，也不会自行切换演练/正式测试页面。客户端现在是**强制演练专用**：只有模拟器的活动恢复状态能够证明当前已获演练授权，并且状态文件或模拟器窗口标题能够证明当前题号与参数一致时，才允许发送接口请求；检测到正式测试、没有活动测试、状态不明确或题号不一致都会立即退出。队号、问题编号和端口均通过命令行参数传入。

## 2. 测试前准备

1. 启动模拟器：

   ```text
   D:\cumcm2026\Jammers-simulator-win64\Jammers-simulator\jammers-simulator.exe
   ```

2. 在模拟器中完成登录并选择“演练测试”的问题 3 或问题 4。
3. 确认页面显示“等待机器狗进入”，并记下“接口端口”。当前默认端口为 `2026`。
4. 打开 PowerShell，进入项目：

   ```powershell
   Set-Location D:\cumcm2026\cumcm-2026
   ```

5. 不要使用浏览器直接打开接口地址。接口要求精确的 JSON `POST` 请求；浏览器发送的 `GET`、错误路径或末尾多出的 `/` 会产生 `404`。

### 2.1 只检查演练安全状态

在正式运行前可以先执行零网络请求的检查：

```powershell
uv run python-code\simulator_client.py --problem 4 --team <你的队号> --check-only
```

只有看到以下两行才表示可以运行：

```text
PREFLIGHT practice problem 4 verified ...
CHECK   passed; no API request was sent
```

如果页面是总览页、正式测试页或题号不匹配，程序会输出 `PRACTICE GUARD BLOCKED` 或找不到活动演练，并且不会调用 `/enter`、`/measure`、`/clear`、`/exit` 中的任何接口。

该检查依赖模拟器当前版本的活动恢复状态目录。v1.1 的 `behavior.journal.jsonl` 使用 `practice_authorized` 证明演练授权，但不再写入题号；遇到这种格式时，客户端只读检查模拟器 WebView 的活动标题，必须恰好识别到对应的“问题3 演练测试”或“问题4 演练测试”。它不会点击或切换页面。若磁盘授权与窗口题号任一项无法确认，保护逻辑都会拒绝运行，而不会静默放行。

## 3. 一键运行

### 3.1 问题 3

```powershell
uv run python-code\simulator_client.py --problem 3 --team <你的队号> --port 2026
```

问题 3 使用中心点加六个外圈点的七点覆盖方案，逐点扫描频道 `1` 至 `20`。

### 3.2 问题 4

```powershell
uv run python-code\simulator_client.py --problem 4 --team <你的队号> --port 2026
```

问题 4 使用间距 700 m、扩展到目标圆外侧的 45 点方格检测网。检测点从不同方向包围潜在源位置，用于处理定向源背面无信号的问题。

### 3.3 已经调用过进入接口

如果当前测试已经手动或通过其他程序调用过 `/enter`，增加：

```text
--already-entered
```

例如：

```powershell
uv run python-code\simulator_client.py --problem 4 --team <你的队号> --port 2026 --already-entered
```

### 3.4 暂不自动退出

默认情况下，客户端完成搜索和清除后会调用 `/exit`。如需保留现场排查失败频道，增加：

```text
--keep-open
```

## 4. 客户端内部工作流

```text
启动模拟器并选择测试
        ↓
读取 behavior-runs 活动恢复状态，确认 practice 授权且不存在 formal 证据
        ↓
从状态文件读取 problem_no；v1.1 未记录题号时只读核对窗口活动标题
        ↓
无法证明或发现 formal → 立即退出，零接口请求
        ↓
POST /enter
        ↓
访问预定覆盖点并扫描 1～20 频道
        ↓
记录 direction + svd_deg 方位结果
        ↓
用 ±1° 方位扇区和最大接收距离递推定位区域
        ↓
计算定位区域的最小包围圆
        ↓
不确定半径 ≤ 18 m 时 POST /clear
        ↓
汇总检测频道、清除成功数和失败频道
        ↓
POST /exit
```

收到 `near` 时会直接在当前点尝试清除。收到 `no_signal` 时：

- 问题 3 可理解为当前点没有收到该频道信号；
- 问题 4 不能据此判断频道不存在，因为检测点可能位于定向源背面。

## 5. 本地接口约定

模拟器在测试页面开启本地监听，当前地址为：

```text
http://127.0.0.1:2026
```

接口均为 JSON `POST`：

| 接口 | 用途 | 额外字段 |
| --- | --- | --- |
| `/enter` | 机器狗进入测试 | 无 |
| `/measure` | 在指定位置检测频道 | `position`、`channel` |
| `/clear` | 在指定位置清除频道 | `position`、`channel` |
| `/exit` | 结束本次测试 | 无 |

所有请求都包含：

```json
{
  "arena_id": "default",
  "robot_id": "通过 --team 传入的队号",
  "request_id": "每次请求生成的新 UUID"
}
```

路径和请求方法必须完全匹配，例如 `/enter/` 不等于 `/enter`。

## 6. 已完成的实测结果

### 问题 3 演练

- 检测到 11 个有效频道；
- 成功清除 11 个，失败 0 个；
- 共执行 162 条有效指令；
- 模拟时间约 7316.7 s；
- 程序墙钟时间约 2.2 s；
- `/exit` 正常返回 `user_exit`。

### 问题 4 演练

- 检测到 16 个有效频道；
- 成功清除 16 个，失败 0 个；
- 共执行 916 条有效指令；
- 模拟时间约 18224.6 s；
- 程序墙钟时间约 9.1 s；
- `/exit` 正常返回 `user_exit`。

问题 4 的 45 点方案还使用 4053 个目标位置和每 5° 一个发射方向做过离散覆盖验证，未覆盖采样状态数为 0。当前方案优先保证找全和清全，并非最短虚拟时间方案。

## 7. 常见故障

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| `404 未知接口或请求路径不精确` | 使用 GET、错误路径或路径末尾多 `/` | 使用客户端发送精确 JSON POST |
| 连接被拒绝 | 模拟器未启动、未选择测试或端口不一致 | 检查进程、页面状态和端口 |
| 请求被拒绝 | 队号不匹配、测试未就绪、重复进入或测试已结束 | 核对 `--team`，按页面状态选择是否加 `--already-entered` |
| `PRACTICE GUARD BLOCKED` | 当前状态是正式测试、状态不明确或题号不一致 | 不要绕过保护；返回演练页并启动正确题号 |
| `practice guard found no active test` | 当前停留在总览页，没有开始演练 | 手动点击正确的“开始问题X演练测试”后再运行 |
| 找到频道但清除失败 | 方位交会不足或定位区域数值异常 | 使用 `--keep-open` 保留现场并查看 `LOCATE` 日志 |
| `uv` 无法运行 | Python 环境或 uv 缓存权限异常 | 在项目 PowerShell 环境中重新执行，必要时检查 `.venv` 与 uv 权限 |

## 8. 自建本地测试程序

为了在不打开官方 EXE、也不接触正式测试的情况下反复验证算法，项目提供两个本地测试入口：

```text
python-code/local_test_simulator.py
python-code/run_local_regression.py
```

`local_test_simulator.py` 是与官方四个 JSON 接口兼容的本地服务；`run_local_regression.py` 负责生成随机案例、启动本地服务、运行 `simulator_client.py`，最后使用模拟器内部真值检查是否存在漏检或漏清除。

### 8.1 已实现的题面规则

| 规则 | 本地实现 |
| --- | --- |
| 目标区域 | 干扰源均匀随机生成在半径 1800 m 的圆域内 |
| 频道 | 从 1～20 中无重复抽取，每个有效频道对应一个干扰源 |
| 接收半径 | 每个干扰源独立生成，范围为 1000～1500 m |
| 问题 3 | 只生成全向干扰源 |
| 问题 4 | 同时生成全向与定向干扰源；定向源采用 180° 发射半平面判据 |
| 示向误差 | 真方位上叠加不超过 ±1° 的确定性误差；同一案例、频道和位置重复检测得到相同误差 |
| 近距离 | 机器狗到干扰源的距离不超过 5 m 时返回 `near` |
| 清除 | 对应频道未清除且距离不超过 20 m 时成功 |
| 移动与耗时 | 速度 5 m/s；检测 5 s；切换频道 1 s；清除成功 5 s、失败 3 s |
| 接口状态 | 检查进入顺序、队号一致性、频道范围、坐标有效性和 `request_id` 唯一性 |

本地服务另外提供只读的 `/health` 和 `/state` 接口。`/state` 含有本地案例真值，仅用于回归判定，正式算法不能依赖它。

### 8.2 安全隔离

本地测试具有以下硬性边界：

1. 只绑定 `127.0.0.1`，不会向外部网络开放；
2. 默认使用端口 `2027`；
3. 两个本地入口都会拒绝端口 `2026`，因为该端口保留给官方模拟器；
4. 不查找、不启动、不点击官方模拟器 EXE；
5. 每个回归案例使用独立临时目录生成本地 `practice` 状态，结束后自动删除；
6. 如果端口已被其他程序占用，本地服务启动失败，不会转而连接该程序。

因此，本地回归可以交给 OpenCode 或其他脚本无人值守执行，不存在误点“正式测试”的路径。

### 8.3 一键批量回归

在项目根目录执行问题 3、4 各 10 个随机案例，并保存 JSON 报告：

```powershell
uv run python python-code\run_local_regression.py `
  --problem both `
  --cases 10 `
  --seed 2026 `
  --output out\local-regression.json
```

指定 `--output` 后，还会自动创建 `out\local-regression-cases`，每个案例输出三份便于调优的文件：

| 文件 | 内容与用途 |
| --- | --- |
| `pX-seedN.json` | 单案例完整记录：真值、频道统计、完整命令、轨迹、客户端标准输出和错误输出 |
| `pX-seedN-events.jsonl` | 一行一条结构化命令，适合流式读取、筛选失败测量和比较耗时 |
| `pX-seedN-trajectory.csv` | 按执行顺序排列的位置、分段距离、累计距离和到达虚拟时间，可直接用 Excel、Pandas 或绘图程序分析 |

如需把逐案例文件放到指定目录，可以增加 `--artifacts-dir <目录>`。

只测试问题 3：

```powershell
uv run python python-code\run_local_regression.py --problem 3 --cases 10
```

只测试问题 4，并在终端同步展开每个客户端的完整输出：

```powershell
uv run python python-code\run_local_regression.py --problem 4 --cases 10 --verbose
```

`--seed` 控制可复现的随机案例。相同参数会生成相同的频道、位置、接收半径、源类型、发射方向和测向误差，便于修复失败后精确复测。

无论是否使用 `--verbose`，保存的 JSON 报告都会包含 `client_stdout` 和 `client_stderr`；`--verbose` 只控制是否同时把这些内容展开到终端。

一个案例只有同时满足以下条件才记为 `PASS`：

1. 客户端退出码为 0；
2. 客户端正常调用 `/exit`；
3. 根据本地真值，每一个实际生成的干扰源都已清除。

第三项很重要：客户端自身的汇总只能列出“已经检测到”的频道，而本地真值检查还能发现完全漏检的频道。

### 8.4 单独启动本地服务

需要观察完整接口交互时，可在第一个 PowerShell 中启动固定案例：

```powershell
$stateDir = Join-Path $env:TEMP 'jammers-local-state'
uv run python python-code\local_test_simulator.py `
  --problem 4 `
  --seed 2026 `
  --port 2027 `
  --state-dir $stateDir `
  --log-file out\standalone-p4-2026.jsonl
```

然后在第二个 PowerShell 中运行客户端：

```powershell
uv run python python-code\simulator_client.py `
  --problem 4 `
  --team LOCAL-TEST `
  --port 2027 `
  --simulator-data-dir $stateDir
```

浏览器中访问 `http://127.0.0.1:2027/state` 可以查看该本地案例的完整当前状态。未指定 `--log-file` 时，服务仍会默认在 `$stateDir` 下生成 `local-simulator-p<题号>-<种子>.jsonl`，每收到一条命令就立即追加并刷新到文件，因此即使测试中途停止，之前的记录也仍然存在。

### 8.5 完整日志字段

本地日志版本由 `log_schema_version` 标识。目前完整输出包含：

1. **案例真值**：每个干扰源的频道、真实坐标、接收半径、全向/定向类型、定向发射方向和最终清除状态；
2. **每条命令**：顺序号、UTC 记录时间、`request_id`、动作、频道、起止坐标、移动距离、移动耗时、频道切换及耗时、操作耗时、操作前后虚拟时间、模拟器响应；
3. **测量诊断**：`no_signal`、`near` 或 `direction`，以及对应干扰源真值、真实距离、真实方位、报告方位、注入的方位误差、当时是否处于接收范围；
4. **清除诊断**：成功或失败、清除前后状态、到真实干扰源的距离、是否位于 20 m 清除半径；
5. **拒绝记录**：非法路径、无效 JSON、进入顺序错误、重复请求 ID、错误题号或无效坐标等请求及错误原因；
6. **机器狗轨迹**：初始点和每次测量/清除的位置、分段距离、累计距离、到达虚拟时间；
7. **耗时分解**：移动、测量、频道切换和清除耗时，以及总虚拟耗时和客户端真实运行耗时；
8. **逐频道汇总**：有无真实干扰源、首次检出时刻、各测量结果次数、清除尝试次数与成功/失败次数；
9. **客户端原始输出**：完整 `stdout`、`stderr`、退出码以及是否正常调用 `/exit`。

其中 `truth_jammers`、命令内的 `truth` 和 `/state` 只允许用于本地回归判定和事后调优，算法运行时不得读取，否则会形成依赖模拟器真值的“作弊式”通过。

### 8.6 当前验证结果与使用边界

原有回归共执行了问题 3、4 各 4 个随机案例，合计 8 个案例、107 个干扰源，全部被检测并清除。增加完整日志后又执行了问题 3、4 各 1 个案例，新增 26 个干扰源也全部被检测并清除，并核对了事件数量、轨迹文件、频道汇总及各类虚拟耗时之和；Python 语法、Ruff 格式和 Ruff 规则检查均已通过。端口保护仍会在 `--port 2026` 时于启动任何服务前退出。

自建程序是“题面规则级仿真”，适合算法回归、极端案例构造、统计试验和性能比较，但不能证明与官方程序的隐藏案例生成方式、边界浮点处理、错误消息和所有计时细节逐字节一致。提交前仍需在官方**演练测试**中做最终验收。

## 9. OpenCode 自动化边界

对于无人值守的自动测试，优先让 OpenCode 执行第 8 节的 `run_local_regression.py`。这条路径不打开官方 EXE，也不包含任何正式测试入口。

对于官方演练，OpenCode 自带 shell/Bash 工具，得到相应权限后可以运行终端命令，因此它可以：

1. 启动 Windows 模拟器 EXE；
2. 轮询 `127.0.0.1:2026`，等待 EXE 建立监听；
3. 先执行 `--check-only`，验证活动状态是对应题号的演练；
4. 调用本项目的 Python 客户端；
5. 读取输出，判断检测数、清除数、失败频道和退出状态；
6. 根据失败日志修改代码，再启动下一次演练。

但需要区分两件事：

- **OpenCode 可以启动 EXE，但端口是模拟器 EXE 自己监听的，不是 OpenCode 创建的。**
- **OpenCode 默认的终端工具不能可靠点击原生 GUI。** 如果登录、选择问题或启动演练必须点击界面，通常仍需人工完成；除非登录状态和测试选择可持久化，或者另外配置 Windows UI Automation 工具。

建议采用半自动方式：OpenCode 启动可见的模拟器窗口，用户完成登录和选择题目，随后 OpenCode 自动等待端口并运行客户端。示意命令如下：

```powershell
$simulatorPath = 'D:\cumcm2026\Jammers-simulator-win64\Jammers-simulator\jammers-simulator.exe'
Start-Process -FilePath $simulatorPath

# 用户在窗口中登录并选择演练题目后，OpenCode 可以执行：
Test-NetConnection -ComputerName 127.0.0.1 -Port 2026
Set-Location D:\cumcm2026\cumcm-2026
uv run python-code\simulator_client.py --problem 4 --team <你的队号> --port 2026
```

为降低 Windows EXE、PowerShell、Windows Python 环境和本机端口之间的兼容风险，本项目更适合让 OpenCode **直接运行在 Windows**。OpenCode 官方也支持直接在 Windows 运行，虽然其通用开发场景更推荐 WSL。若从 WSL 启动，需要额外验证 Windows EXE 互操作、`localhost` 转发以及 Linux/Windows Python 环境差异。

OpenCode 相关官方资料：

- [Tools：shell/Bash 工具](https://opencode.ai/docs/tools/)
- [Permissions：命令授权规则](https://opencode.ai/docs/permissions/)
- [CLI：`opencode run` 自动化](https://opencode.ai/docs/cli/)
- [Windows/WSL 使用说明](https://opencode.ai/docs/windows-wsl/)

建议保留 `bash` 为需要确认的权限，而不是全局无限制放行。若从 `D:\cumcm2026` 启动 OpenCode，项目和模拟器都位于其工作目录下，路径授权也更简单。

为了防止 OpenCode 绕过安全闸直接使用 `curl`、`Invoke-WebRequest` 或自行修改客户端，执行演练时不要启用 `--auto`：将 `edit` 设为 `deny`、`bash` 设为 `ask`，并且只批准 `uv run python-code\simulator_client.py ...` 这条受保护入口。任何直接访问 `127.0.0.1:2026` 的其他命令都应拒绝。

## 10. 正式测试注意事项

1. 正式测试前先用新的演练案例复测。
2. 队号必须通过 `--team` 传入，不写死在提交代码中。
3. 确认问题编号和模拟器页面一致，防止把问题 3 的七点策略用于问题 4。
4. 正式测试没有完成结果上传前，不要关闭模拟器。
5. 当前客户端强制拒绝正式测试。需要正式运行时应另建经过人工审核的正式入口，不要删除或增加“忽略安全检查”参数来复用演练入口。
