# ai4se-sdd-loop-workflow

从**需求 → 计划/用例 → 评审 → 任务 → 代码 → 测试 → AI Review → 提交**的工程化 Workflow。配置和产出写在业务项目里；结束时汇总须人工执行的后续事项（SQL / 配置等）。

**按项目扩展的核心入口是 `sdd-loop-workflow-config/ai-rules`**（见 [§5](#5-核心扩展点ai-rules)）：把项目规范、以及各节点要用的 MCP / Rules / Skills，写进扩展 md 并在 `ai-rules.yaml` 挂到对应节点即可，**不必改引擎 prompt**。`sddl init` 后改业务侧配置就能用。

CLI（**macOS / Windows 通用**）：`sddl init` / `sddl start`，或 `sddl-init` / `sddl-start`。  

![workflow.jpeg](assets/img/workflow.jpeg)
---

## 1. 快速使用

```bash
git clone <本仓库地址>
cd ai4se-sdd-loop-workflow

# 推荐：一键初始化（项目 .venv + 安装 + 把 venv 写入 PATH，免每次 activate）
# 要求宿主 Python 为 3.10～3.14；旧 venv 不符时加 --force
./init_env.sh            # macOS / Linux
# Windows:  .\init_env.cmd
# 重建 venv: 加 --force；只装不改 PATH: 加 --skip-path
```

也可手动：用 **3.10～3.14** 执行 `python3 -m venv .venv` → 激活 → `python -m pip install -U "pip>=21.3"` → `pip install -e .`。  
Windows 默认过旧时，`init_env.cmd` 会优先 `py -3.14`…`-3.10`（跳过 3.8 等），并把 `.venv\Scripts` 写入**用户 PATH**，新开终端即可直接 `sddl`，无需每次 activate。

装好后在业务项目根：

```bash
sddl init
sddl start --tool cursor --file "/path/to/prd.md" --name login
sddl start --tool cursor --name login --auto      # 无人值守
sddl start --tool cursor --name login             # 续跑，勿加 --fresh
```

`sddl start` / `start.cmd` **绝不**执行 `pip install`；未安装时会提示先跑 `init_env`。

| 开关 | 作用 |
|------|------|
| `--file` | 需求文件 |
| `--name` | 产出目录名（默认落在 `spec/<name>/`） |
| `--auto` | 无人值守 |
| `--fresh` | 清空该需求产出后重来 |
| `--tool` | `cursor` / `claude_code` / `omp` / `echo` |

需要 **Python 3.10～3.14**（不含 3.15+）、**pip ≥ 21.3** 和已登录的 AI CLI。

---

## 2. `init` 在业务项目里生成什么

```text
your-project/
├── sdd-loop-workflow-config/     # 业务配置（改这里）
│   ├── workflow.yaml             # docs_dir 等运行时目录
│   ├── ai-rules.yaml             # 【核心】节点 → 扩展 md 映射
│   └── ai-rules/*.md             # 【核心】项目规范；亦可在此引用 MCP/Rules/Skills
└── .cursor|claude|omp/skills/start-workflow/   # 拼启动命令的 skill（不在对话里执行）
```

| 文件 | 作用 |
|------|------|
| `ai-rules.yaml` + `ai-rules/` | **核心扩展点**（详见 [§5](#5-核心扩展点ai-rules)）：规范 + 工具引用 |
| `workflow.yaml` | `docs_dir` 等运行时目录 |
| `start-workflow` skill | 准备需求文件并拼装启动命令（见下）；**不在当前 AI 对话里执行** |

跑起来后，需求文档在 `<docs_dir>/<name>/`（如 `spec/login/01-requirements.md` … `07-commit.md`）。

### `start-workflow` skill 用在什么时候

`sddl init` 会把该 skill 装到业务项目的 AI 技能目录。在对话里触发它，只做两件事：**落本地需求文件** + **拼好 `sddl start ...` 命令**；真正跑 workflow 必须你自己在**终端**执行。

| 场景 | 你怎么说 | skill 做什么 |
|------|----------|--------------|
| 本地已有 PRD | 给出文件路径 | 校验路径存在，直接拼 `sddl start --file ...` |
| 需求在外部系统（Jira、Colla 等） | 告诉**卡号 / 需求标识** | 按项目已配置的 **MCP** 拉取正文 → 写入本地（如 `docs/requirements/<标识>.md`）→ 再拼启动命令 |
| 两边都没有 | — | 先问你要路径或外部来源，不瞎拼命令 |

要点：

- MCP（Jira / Colla 等）需事先在 AI 环境配好；skill **不猜** MCP 名字，步骤以项目 rule / skill 输入为准。
- skill **禁止**在当前 AI session 里执行启动命令；你复制命令到业务项目根的终端再跑（或结束对话后在系统终端跑），编排进程才能接管交互节点并续跑。
- 审批通过、续跑都**不要**再让 skill 重跑一遍；外部终端里已在跑的进程会自己进下一节点。

---

## 3. 有哪些节点

```text
需求 → 并行(计划+用例) → 评审 → 任务拆分 → 实现 → 测试 → AI Review → 提交
```

| 节点 | 产出 | 做什么 |
|------|------|--------|
| 需求分析 | `01-requirements.md` | 澄清与定稿 |
| 制定计划 / 设计用例 | `02-plan.md`、`02-test-cases.md` | 并行初稿 |
| 计划与用例评审 | `02-plan-test-review.md` | 对齐并确认 |
| 任务拆分 | `03-tasks.md` | 任务 + API 详细设计 |
| 代码实现 | `04-implementation.md` + 业务代码 | 只写生产代码；AI 无法代执行的事项写入「人工后续事项」 |
| 测试自验证 | `05-test-report.md` | 写测→跑绿→置信度；API/E2E 有栈才跑 |
| AI 代码评审 | `06-ai-review.md` | 针对改动代码做技术整洁度/简单重构并测绿（不读需求文档） |
| 提交代码 | `07-commit.md` | 提交（或跳过）+ 定稿「后续 Action List」；**禁止提交 `docs_dir`** |

- 人工：`prompts/*.md`，澄清与审批需确认；`--auto` 用 `*.auto.md`，按 `ai-rules` 自决  
- 测试只在「测试自验证」写；实现节点不写测试  
- **定制项目行为 → 只改 `ai-rules`**（[§5](#5-核心扩展点ai-rules)），不要改引擎 `prompts/`  
- 人工后续（SQL / 配置等）→ Action List；**禁止提交 `docs_dir`**

---

## 4. 断点续接

产出落在 `<docs_dir>/<name>/`（如 `spec/login/`）。每次启动会扫描该目录已有 md 与文末 **Workflow 状态**表，从**未完成的下一节点**接着跑，不会无故从头再来。

### 怎么续

| 情况 | 做法 |
|------|------|
| 编排进程还在跑（终端未退出） | 在对话里完成澄清/审批即可，**进程会自动进下一节点**；不要再执行一遍 `sddl start` |
| 进程已退出 / 中断 / 换机器 | 用**同一个** `--name` 再执行 `sddl start`（可带原 `--file`）；**不要**加 `--fresh` |
| 整条链路已完成（存在完成态的 `07-commit.md`） | 再 `sddl start` 会直接判定已完成；要推倒重来才加 `--fresh`（会清空该需求下除原始需求外的 md 产出） |

```bash
# 续跑（推荐始终带上 --name，与首次一致）
sddl start --tool cursor --name login

# 仅当明确要清空该需求产出、从头再来
sddl start --tool cursor --file "/path/to/prd.md" --name login --fresh
```

### 依据什么定位断点

启动时按「流程越靠后的产出优先」检查，并结合状态表里的 `next_node`、门禁是否通过（内容就绪 + 需审批节点已 `approved`）决定入口，例如：

| 已有关键产出（示意） | 通常从哪继续 |
|----------------------|--------------|
| 仅有需求草稿 / 需求未批完 | `analyze_requirements` |
| `01-requirements` 已完成，计划/用例未齐 | 并行生成或 `review_plan_and_tests` |
| `02-plan-test-review` 已批 | `split_tasks` |
| `03-tasks` 已批 | `implement_code` |
| `04-implementation` 已有 | `verify_tests` |
| `05-test-report` 已有 | `ai_review` |
| `06-ai-review` 已有 | `commit_code` |
| `07-commit` 已 completed 且无下一节点 | 整单结束，无需续跑 |

要点：

- **同名续跑靠 `--name`**（或已有 `spec/<name>/00-requirement.md`）；换 name 等于另一条需求线。
- **`--fresh` 与续跑互斥**；误加会清掉该需求下已有阶段文档。
- 交互节点在外部终端跑着时，审批后由**同一进程**续跑；用 skill 时不要为「接着跑」再拼一次启动命令。

---

## 5. 核心扩展点：`ai-rules`

业务侧目录：`sdd-loop-workflow-config/`。**按项目定制时优先只改 `ai-rules`**，不必改引擎仓库里的 `prompts/` 或节点编排。

| 改什么 | 作用 |
|--------|------|
| `ai-rules.yaml` | 声明「哪个节点注入哪些 md」 |
| `ai-rules/*.md` | 写**你们项目的规范**；需要时在同一文件里引用 MCP / Rules / Skills |

正文经 `{{ai_rules}}` 注入对应节点，**优先级高于**引擎通用提示词；`--auto` 也优先按这里消解歧义。

### 怎么扩展（三步）

1. 在 `ai-rules/` 下准备 md：可先改 init 自带的 `project-standards.md`，或按节点拆成 `implement_code.md`、`verify_tests.md` 等，写清项目约定。  
2. 在 `ai-rules.yaml` 的 `nodes.<节点ID>` 下列出这些文件（未列出的节点不注入）。  
3. 某节点要用项目已有的 **MCP / IDE·Agent Rules / Skills** 时：在**该节点对应的扩展 md**里写明「用哪个、何时用、怎么用」——**不要**在 yaml 里另配工具表。

```yaml
# ai-rules.yaml
ai_rules_dir: ai-rules

nodes:
  analyze_requirements:
    - project-standards.md
  implement_code:
    - project-standards.md   # 可换成 implement_code.md 等
  verify_tests:
    - project-standards.md
  ai_review:
    - project-standards.md
  # commit_code:             # 需要定制提交策略时再打开
  #   - project-standards.md
```

```markdown
# project-standards.md（或节点专用 md）里引用工具

- MCP：`user-jira` — 澄清时按 issue key 拉取描述与验收标准
- Rules：遵守仓库 `.cursor/rules/api-compat.mdc`
- Skills：Colla 需求先按项目 `fetch-colla-prd` 的读法拉取
```

常用节点 ID：`analyze_requirements` / `create_plan` / `design_test_cases` / `review_plan_and_tests` / `split_tasks` / `implement_code` / `verify_tests` / `ai_review` / `commit_code`。

### 提交与后续 Action List

| 行为 | 说明 |
|------|------|
| 未配 `commit_code` | 拟 msg → 问用户；拒绝则跳过；`--auto` 跳过提交 |
| 已配并在 md 写明策略 | 按扩展 md 提交（msg / 是否 push 等） |
| `docs_dir` | **禁止** stage/commit（含 `07-commit.md`） |
| Action List | `04`「人工后续事项」→ `07`「后续 Action List」；须具体，无则写「无」 |

### 其它业务配置：`workflow.yaml`

| 配置项 | 作用 |
|--------|------|
| `docs_dir` | 文档产出根目录（相对业务项目根）。默认 `spec`；如 `spec/login/` |

节点用的 tool / prompt / mode **不在这里配**，在引擎仓库的 `config/workflow.yaml`。
