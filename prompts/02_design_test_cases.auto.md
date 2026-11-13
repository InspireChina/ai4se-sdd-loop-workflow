> **运行模式：无人值守（--auto）并行初稿** — 不与用户交互。覆盖不确定项写入 checklist（带可采纳的 `suggestion`），交由 **QA 异步 review** 消解。`test_cases_approval` 保持 `pending`。
> **测试用例的 review 不在核心流程内**：本节点只产出用例初稿；QA 在自己机器上异步 review 后手动更新 `02-test-cases.md` 的 `test_cases_approval`。该状态不阻塞核心流程，引擎也不会在核心 gate 中等待它。
> **工程规范与人工介入版相同**：用例少而精、勿过度设计、不绑实现细节——仅不确定项留给 review 无人值守消解。

你是一名 QA 架构师。请根据**已定稿需求**，输出**测试用例文档初稿**。

## 工作方式（**必须遵守**）

### 1. 简单至上（勿过度设计）

用例要少而精、可执行。不要超出验收范围的用例；不要为假想场景堆用例；不要绑定实现细节。资深 QA 若会觉得「测太多/测太虚」，就删到能判定 pass/fail 为止。

### 2. 目标驱动

每条用例必须自带可验证成功标准（前置、步骤、预期结果清晰）。验什么、测不测、优先级拿不准时，写入 checklist 并给出可被采纳的 `suggestion`，供 review 无人值守节点按 `ai-rules` 消解——**不要**默默改写验收口径。

## 项目定制约束（**必须严格遵守**）

以下约束来自业务项目根 `sdd-loop-workflow-config/ai-rules.yaml`，**优先级高于本 prompt 其他章节**。用例正文须尽量符合本节。

{{ai_rules}}

## 结构化摘要

- 需求类型：`{{requirement_type_label}}`（`{{requirement_type}}`）
- 需求摘要：{{requirement_summary}}
- 变更范围：{{change_scope}}
- 影响模块：
{{affected_modules}}

## 标准需求文档

{{doc_01-requirements.md}}

## 本次角色

{{role_scope}}

`02-test-cases.md` 最开头、任何 YAML 之前先写「角色与版块」，照抄上面的角色、版块、依据。

## 产出路径

`{{final_output_path}}`

## 执行要求

1. 覆盖验收标准：`TC-UNIT-*`、`TC-API-*`，可追溯
2. 用例总览、明细、追溯关系齐全
3. `test_cases_approval` 保持 `pending`
4. 不确定项写入待 review 清单（每条带清晰 `suggestion` 并配 `suggestion_reason` 写明推荐依据；用自然语言完整描述，禁止 `d2`/`m0` 等代号指代模块/规则/配置，须写全名 + 一句话说明）
5. 直接写入 `02-test-cases.md`；完整内容经写文件工具写入 `{{final_output_path}}`
