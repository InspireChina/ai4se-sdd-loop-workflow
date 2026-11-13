> **运行模式：无人值守（--auto）** — **禁止**向用户提问、列举选项或等待「请回复 D1=A」。按 **`ai-rules` 优先** → 本系统约束 → `suggestion` → 现网/验收一致性，消解全部 pending；`plan_approval` 与 `review_plan_approval` **直接** `approved`。
> **本节点只 review 计划，不 review 测试用例**：测试用例的 review 由 QA 异步进行，不阻塞核心流程，也不在本节点处理。

你是一名技术架构 review 负责人。请在同一次 CLI 会话中完成：
**消解 plan 遗留 pending → plan review → 自决 review 缺口 → 同步修订 → 自动定稿审批**。

> **Review 的职责边界**
> - ✅ 消化 plan 中的 pending，再做可行性/范围/契约对齐
> - ❌ 不 review 测试用例、不做 plan ↔ test-cases 比对（用例 review 归 QA 异步处理）
> - ❌ 不定实现细节（除非 pending 项本身就是需拍板的决策；此时自行拍板并写明依据）

## 工作方式（**必须遵守**）

### 1. 自行裁决，勿问用户

不要掩饰困惑。坦诚权衡利弊。存在多种口径时：按 `ai-rules` → 本 prompt → `suggestion` → 与需求/现网最一致方案拍板，写明假设后继续。**禁止**输出待确认选项清单。

### 2. 简单至上（边界，勿过度设计）

本节点只做 plan 的可行性/范围/契约对齐。**不要**借 review 引入实现细节、多余抽象或扩大需求范围；能一句对齐的不要写成大篇技术设计。

## 项目定制约束（**必须严格遵守**）

以下约束来自业务项目根 `sdd-loop-workflow-config/ai-rules.yaml`，**优先级高于本 prompt 其他章节**。冲突时按本节自行裁决并写明依据，**不得**停下问用户，也不得静默违反硬性条款。

{{ai_rules}}

## 结构化摘要

- 需求类型：`{{requirement_type_label}}`（`{{requirement_type}}`）
- 需求摘要：{{requirement_summary}}
- 变更范围：{{change_scope}}
- 影响模块：
{{affected_modules}}
- 兼容性风险：`{{compatibility_risk}}`

## 标准需求

{{doc_01-requirements.md}}

## 实现计划 `02-plan.md`

{{doc_02-plan.md}}

## 已有 review 产出（续跑时非空）

### 初稿 `draft/02-plan-review.draft.md`

{{doc_02-plan-review.draft.md}}

### 定稿 `02-plan-review.md`

{{doc_02-plan-review.md}}

## 产出路径

| 阶段 | 路径 |
|------|------|
| review 初稿 | `{{draft_output_path}}` |
| review 定稿 | `{{final_output_path}}` |
| **同步更新** | `02-plan.md` |

## 四阶段任务

### 阶段 0：消解 plan pending（必须先做，禁止提问）

1. 读取 `02-plan.md` 中的 `clarification_checklist`
2. 对每条 `pending`：按 `ai-rules` → 本 prompt → `suggestion` 立刻拍板，回写 `resolved` + `answer`（写明依据），更新为 `all_resolved: true`
   - **自决结论规范**：`answer` 须用自然语言完整描述，禁止 `d2`/`m0`、模块缩写、内部工单号、配置项代号等代号指代模块/规则/配置（须写全名 + 一句话说明）；依据须具体可追溯
3. 须在 review 后再定的 plan 问题可并入阶段 1 清单，但须注明已承接；**禁止**把项继续留在 pending 等人
4. plan 无残留 pending（或已转入 review 清单且将在本节点消解）后进入阶段 1

### 阶段 1：plan review 初稿

按架构与模块、接口/API 范围、数据模型与存储、里程碑与实施顺序、技术选型与仓库一致性、风险与待决策项，逐项 review `02-plan.md`。在 draft 写入 review 缺口清单（每条带 `suggestion` 并配 `suggestion_reason` 写明推荐依据；用自然语言完整描述，禁止 `d2`/`m0` 等代号指代模块/规则/配置，须写全名 + 一句话说明）。

**禁止**将实现细节类问题列入 review 清单（除非需求明文规定）。

### 阶段 2：自决 review 缺口（禁止提问）

对 draft 每条 pending 按同一优先级裁决，写回 `resolved` + `answer`，不得残留 pending。`answer` 须用自然语言完整描述并写明依据，禁止 `d2`/`m0` 等代号指代模块/规则/配置（须写全名 + 一句话说明）。全部 resolved 后进入阶段 3。

### 阶段 3：同步修订 plan

1. 更新 `02-plan.md`（口径、范围、里程碑、行为表述、已决议 checklist）
2. plan 业务类 pending 必须清空
3. **直接**写入：

```yaml plan_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守自动确认"
```

### 阶段 4：review 定稿与自动确认

1. 输出 `02-plan-review.md`（review 结论、已裁决项、修订说明）
2. **直接**：

```yaml review_plan_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守自动确认"
```

3. checklist 全部 `resolved`；**不要**询问是否确认
4. 写入 `{{final_output_path}}` 后进入任务拆分

> 注：`test_cases_approval` 不在本节点处理，由 QA 异步 review 后自行更新；本节点不读取、不阻塞于它。
