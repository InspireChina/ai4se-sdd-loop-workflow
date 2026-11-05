---
name: start-workflow
description: >-
  准备并拼装 SDD workflow 启动命令（需求到代码再到测试）。在用户要求启动
  workflow、开始实现需求、无人值守/全自动跑完，或给出本地 PRD 路径、Colla、
  Jira 等需求来源时使用。本 skill 只准备命令，不在当前 AI session 内执行启动；
  根据上下文自动拼接全部相关参数（含 --auto / --name / --fresh 等）。
---

# 启动 Workflow

把需求落到一个本地文件，**根据上下文自动拼齐启动参数**，把完整命令交给用户在 AI session 外执行。
不要改 workflow 实现。不要等用户逐个点名参数——从对话意图里推断。

## 硬性约束（必须遵守）

1. **禁止**在当前 AI session 里用 Shell / 终端工具执行 `sddl start`（或 `start.sh` / `start.cmd`）。
2. **禁止**为「续跑」「审批后继续」再次拼装/执行启动命令；审批通过后由**已在外部终端运行的** Python 进程自动续跑。
3. 准备完成后：展示命令并说明在外部终端执行，然后停止（不要调用执行类工具）。
4. **命令必须用空格形式** `sddl start` / `sddl init`（或 `sddl-start` / `sddl-init`），**不要**拼 `sddl:start`。

## 1. 确定 PRD 文件（得到 `--file`）

先看上下文有没有本地 PRD 路径；没有再看是否要从外部系统读。

### 已给出本地路径

1. 解析成绝对路径，确认文件存在。
2. 不要再访问 Colla、Jira 等。
3. 该绝对路径即为 `--file`。

路径不存在或是目录 → 说明情况，停止，不要拼命令。

### 要从 Colla、Jira 或其它外部系统读取

1. MCP 与读法只以本次 skill 输入和项目已有 rule 为准（Cursor rules、`CLAUDE.md`、`AGENTS.md`、omp rules、`ai-rules` 等）。
2. 不要猜 MCP 名，不要自编读法；没说明就问用户，不要拼命令。
3. 读到正文后写入业务根 `<docs_dir>/requirements/<标识>.md`（`docs_dir` 默认 `spec`，以 `sdd-loop-workflow-config/workflow.yaml` 为准）。目录不存在就创建；同名覆盖。
4. 标识优先需求编号，否则用标题（只留字母、数字、中文、`-`）。
5. 正文为空 → 停止。写入后的绝对路径即为 `--file`。

### 两边都没有

问用户要本地 PRD 路径或外部来源。不要拼命令。

## 2. 读取业务 tool 配置

打开业务根 `sdd-loop-workflow-config/workflow.yaml`，检查是否配置了 AI 工具：

- 存在 `defaults.tool`，或任一 `nodes.<id>.tool` → **已配置**
- 否则 → **未配置**

（`model` 可选；编排引擎会处理降级，skill 拼命令时一般不必带 `--model`。）

## 3. 按上下文自动拼接参数

在业务项目根执行（cwd = `app_root`）。

**推荐基底（已配置 tool 时）——不带 `--tool`：**

```bash
sddl start --file "<PRD 绝对路径>"
```

**强制本环境工具基底（调试 / 未配置 / 用户要求）——带 `--tool`：**

```bash
sddl start --tool claude_code --file "<PRD 绝对路径>"
```

再**扫一遍对话/skill 输入**，按下面规则追加参数（能推断就加，不要逐项问用户「要不要加 xxx」）：

| 参数 | 何时加入 |
|------|----------|
| `--tool claude_code` | **仅当**走「强制本环境」命令时加入。值默认 `claude_code`；用户明确要求别的工具（如 `echo`）时才改。已配业务 `defaults.tool` 且用户未要求强制时，**推荐命令不要加** `--tool`。 |
| `--file <绝对路径>` | **始终**加入（上一步得到的路径）。续跑且用户明确说「只续跑、不再读 PRD」且已有 `00-requirement.md` 时，可省略 `--file`，但须同时有可用的 `--name`。 |
| `--name <目录名>` | 用户指定了产出目录名/需求名/slug；或从 PRD 文件名、标题、需求编号能稳定推导出短标识时**主动加上**（便于续跑）。不要用超长标题。 |
| `--docs-dir <路径>` | 用户要覆盖默认产出目录，或明确说产出不在默认 `docs_dir`（如 `spec`）下时加上。未提及则不加。 |
| `--model <名>` | 用户明确指定模型时加上（会覆盖配置中全部节点的 model）。未提及不加。 |
| `--auto` | 出现无人值守意图：**无人值守、全自动、不打断、不提问、自动跑完、别问我、auto、unattended** 等。普通「启动一下」**不要**加。 |
| `--skip-clarification` | 用户只要跳过澄清、或 CI/echo 调试且未要求完整澄清时加上。若已加 `--auto`，**不必再写**。 |
| `--fresh` | 用户明确要重来、清空重跑、从头开始时加上。续跑时**禁止**加。 |
| `--skip-install` | 用户明确跳过依赖安装、加速启动、venv 已就绪时加上。未提及不加。 |
| `-h` / `--help` | 用户只想看帮助时，只输出帮助命令，不要拼启动。 |

规则补充：

1. **推断优先于追问**：上下文够用就直接拼；只有缺 PRD 路径/外部读法时才停下来问。
2. **互斥**：`--fresh` 与「续跑」互斥。
3. **不要**发明上表以外的参数。
4. 拼完后用一两句说明加了哪些开关。

## 4. 交出命令（到此结束，不要执行）

### 业务已配置 tool（`defaults.tool` 或节点 tool）

展示 **两条**命令，并写清区别；**推荐用 A**：

```bash
# A. 推荐：不带 --tool — 按 sdd-loop-workflow-config 的 tool/model（可按节点不同）
sddl start --file "/absolute/path/to/prd.md" --name login

# B. 强制本环境工具：覆盖配置里所有节点的 tool（调试或临时换工具）
sddl start --tool claude_code --file "/absolute/path/to/prd.md" --name login
```

说明：

- **A**：完全按业务 `workflow.yaml` 合并后的配置跑；可不改启动命令切换节点工具。
- **B**：CLI `--tool` 会**覆盖全部节点**，忽略配置里的按节点 tool。

### 业务未配置 tool

只给带 `--tool` 的命令（当前 agent = `claude_code`），并提示可在 `sdd-loop-workflow-config/workflow.yaml` 增加 `defaults.tool` 后改用不带 `--tool` 的启动方式。

```bash
sddl start --tool claude_code --file "/absolute/path/to/prd.md" --name login
```

收尾说明（两种情况都要）：

> 请复制命令，任选一种方式执行（不要在当前 AI 对话里跑）：
>
> 1. **新开一个终端**，`cd` 到业务项目根后粘贴执行；或
> 2. **退出 / 结束当前 AI session** 后，在系统终端里执行。
>
> Workflow 必须在 AI session 外跑，编排进程才能接管节点并自动续跑。
