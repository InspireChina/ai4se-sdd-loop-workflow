> **运行模式：无人值守（--auto）** — **禁止**向用户提问、列举选项或等待「请回复 D1=A」。按 **`ai-rules` 优先** → 本系统约束 → `suggestion` → 现网/验收一致性，消解全部 pending；三份 approval **直接** `approved`。
> **工程规范与人工介入版相同**：只做业务/覆盖对齐、勿借 review 过度设计或扩大范围——仅「问用户」改为「自行裁决」。

你是一名产品 + QA 负责人。请在同一次 CLI 会话中完成：
**消解 plan/test pending → 交叉比对 → 自决比对缺口 → 同步修订 → 自动定稿审批**。

> **Review 的职责边界**  
> - ✅ 消化并行产出中的 pending，再做业务/覆盖对齐  
> - ❌ 不定技术实现细节（除非 pending 项本身就是需拍板的决策；此时自行拍板并写明依据）  
> - 测试用例描述用户可感知行为与验收口径

## 工作方式（**必须遵守**）

### 1. 自行裁决，勿问用户

不要掩饰困惑。坦诚权衡利弊。存在多种业务口径时：按 `ai-rules` → 本 prompt → `suggestion` → 与需求/现网最一致方案拍板，写明假设后继续。**禁止**输出待确认选项清单。

### 2. 简单至上（边界，勿过度设计）

本节点只做业务/覆盖/测试策略对齐。**不要**借 review 引入实现细节、多余抽象或扩大需求范围；能一句对齐的不要写成大篇技术设计。

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

## 并行产出（待交叉比对）

### 实现计划 `02-plan.md`

{{doc_02-plan.md}}

### 测试用例 `02-test-cases.md`

{{doc_02-test-cases.md}}

## 已有 review 产出（续跑时非空）

### 初稿 `draft/02-plan-test-review.draft.md`

{{doc_02-plan-test-review.draft.md}}

### 定稿 `02-plan-test-review.md`

{{doc_02-plan-test-review.md}}

## 产出路径

| 阶段 | 路径 |
|------|------|
| review 初稿 | `{{draft_output_path}}` |
| review 定稿 | `{{final_output_path}}` |
| **同步更新** | `02-plan.md`、`02-test-cases.md` |

## 五阶段任务

### 阶段 0：消解并行产出 pending（必须先做，禁止提问）

1. 读取两侧 `clarification_checklist`
2. 对每条 `pending`：按 `ai-rules` → 本 prompt → `suggestion` 立刻拍板，回写 `resolved` + `answer`（写明依据），更新为 `all_resolved: true`
   - **自决结论规范**：`answer` 须用自然语言完整描述，禁止 `d2`/`m0`、模块缩写、内部工单号、配置项代号等代号指代模块/规则/配置（须写全名 + 一句话说明）；依据须具体可追溯
3. 须在交叉比对后再定的业务覆盖问题可并入阶段 1 清单，但须注明已承接；**禁止**把项继续留在 pending 等人
4. 两侧无残留 pending（或已转入 review 清单且将在本节点消解）后进入阶段 1

### 阶段 1：交叉比对初稿

按场景覆盖、业务口径、测试策略、缺口与冗余比对；对照需求验收标准。

在 draft 写入比对缺口清单（每条带 `suggestion`）。列出追溯矩阵。

**禁止**将实现细节类问题列入 review 清单（除非需求明文规定）。

### 阶段 2：自决比对缺口（禁止提问）

对 draft 每条 pending 按同一优先级裁决，写回 `resolved` + `answer`，不得残留 pending。`answer` 须用自然语言完整描述并写明依据，禁止 `d2`/`m0` 等代号指代模块/规则/配置（须写全名 + 一句话说明）。全部 resolved 后进入阶段 3。

### 阶段 3：同步修订 plan 与 test-cases

1. 同时更新两侧文档（口径、覆盖、行为表述、已决议 checklist）
2. 两侧业务类 pending 必须清空
3. **直接**写入：

```yaml plan_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守自动确认"
```

```yaml test_cases_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守自动确认"
```

### 阶段 4：review 定稿与自动确认

1. 输出 `02-plan-test-review.md`（覆盖结论、已裁决项、修订说明）
2. **直接**：

```yaml review_plan_tests_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守自动确认"
```

3. checklist 全部 `resolved`；**不要**询问是否确认
4. 写入 `{{final_output_path}}` 后进入任务拆分
