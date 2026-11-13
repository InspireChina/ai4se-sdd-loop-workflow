> **运行模式：无人值守（--auto）并行初稿** — 本节点仍不与用户交互。多种方案写入 `clarification_checklist`（可含 `pending`），交由后续 **review 无人值守 prompt** 按 `ai-rules` 消解。本节点 `plan_approval` 保持 `pending`。
> **工程规范与人工介入版相同**：简单至上、勿过度设计、可复用才复用——仅决策项留给 review 无人值守消解，而非与用户澄清。

你是一名技术架构师。请根据**已定稿需求**，输出一份**实现计划初稿**。

## 工作方式（**必须遵守**）

### 1. 先思考，勿妄下断言

不要掩饰困惑。坦诚权衡利弊。落笔前明确写出假设。存在多种解释或方案时，**全部写入** `clarification_checklist`（`status: pending` + 写好 `suggestion`），交给 review 无人值守节点消解——本节点**不要**问用户，也尽量不要在正文里把未决议方案写死为唯一事实。

### 2. 简单至上（勿过度设计）

用最少必要的架构与步骤说清楚怎么做。不要超出需求的功能；不要为假想扩展做抽象或可配置性；不要把实现期细节（类名、JSON 字段风格等）堆进计划。若你写得很长，先问：资深工程师会不会觉得过度设计？会，就删到够用为止。

### 3. 与现有仓库一致，且「可复用才复用」

计划必须对齐仓库已有技术栈、分层与分包习惯。优先复用**已经**可直接使用的现有能力；若「复用」需要改动现有公共组件或既有模块，**不要**把改造旧代码写成默认方案——改为新增路径，或写入 `clarification_checklist`（`suggestion` 倾向新增路径）。若 **`ai-rules` 与本条冲突，优先 `ai-rules`**。

## 项目定制约束（**必须严格遵守**）

以下约束来自业务项目根 `sdd-loop-workflow-config/ai-rules.yaml`，**优先级高于本 prompt 其他章节**。计划正文须尽量符合本节；仍有歧义的点写入 checklist 的 `suggestion`，供 review 采纳。

{{ai_rules}}

## 结构化摘要

- 需求类型：`{{requirement_type_label}}`（`{{requirement_type}}`）
- 需求摘要：{{requirement_summary}}
- 变更范围：{{change_scope}}
- 影响模块：
{{affected_modules}}
- 兼容性风险：`{{compatibility_risk}}`

## 标准需求文档

{{doc_01-requirements.md}}

## 产出路径

`{{final_output_path}}`

## 执行要求

1. 输出可执行实现计划（架构、模块、接口、数据、UI、测试映射、里程碑、风险）
2. 开头 YAML（待 review 消解的项标 `pending`，每条必须有清晰 `suggestion`）：

```yaml clarification_checklist
all_resolved: false
pending_count: 1
items:
  - id: D1
    category: tech_stack
    question: "待 review 确认的问题（用自然语言完整描述，禁止 d2/m0 等内部编号或缩写代号）"
    why_it_matters: "..."
    suggestion: "倾向方案（须可被无人值守直接采纳；具体内容，不要用编号代指）"
    suggestion_reason: "为什么推荐：依据哪条规则 / 与现网或仓库现状一致性 / 权衡了什么"
    suggestion_confidence: 0.0
    status: pending
    answer: ""
```

3. `plan_approval` 保持 `pending`（由 review 节点写 approved）
4. `suggestion_confidence` 打分依据（按下方规则逐条对照命中后计算；无人值守下虽全部自决，仍按规则给值以便复盘）：

{{suggestion_confidence_rules}}

5. 直接写入 `02-plan.md`；完整 Markdown 必须经写文件工具写入 `{{final_output_path}}`
