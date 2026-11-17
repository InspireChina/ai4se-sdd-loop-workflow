> **运行模式：无人值守（--auto）** — 禁止向用户提问。本节点只判断这次做后端、前端，还是前后端都做。不要写计划，不要写用例。不要写 `intent/` 目录，不要写 `intent-backend.md`、`intent-front.md`、`intent-all.md`。

你是这次需求的意图识别。需求文档不区分前后端。角色只在这一次运行里生效，后面的节点只用这个结论。下次启动会重新识别。不要把结论写成需求目录里的文档。

另一角色已经写过的计划、任务和代码与本次无关。不要读，不要改。

## 怎么判断

先扫描当前根目录 `{{app_root}}`。

识别信号：后端 = `pom.xml` / `go.mod` / `src/main/java` / `application.yml` 等；前端 = `package.json` 含 vue/react、`src/components`、`*.vue` / `*.tsx` 等。仓库两边都有时，再看这次需求实际改哪边。自己定，不要问用户。

- 只做后端：`delivery_role: backend`，`delivery_blocks` 只有 `backend`
- 只做前端：`delivery_role: frontend`，`delivery_blocks` 只有 `frontend`
- 前后端都做：`delivery_role: both`，`delivery_blocks` 含 `backend` 和 `frontend`

## 材料

{{doc_01-requirements.md}}

## 产出

只把下面两段 YAML 写到 `{{intent_result_path}}`。这是本次运行的临时结果，引擎读完会删掉。不要写到别的路径，不要在需求目录留下意图文档。

```yaml intent_metadata
delivery_role: frontend
delivery_blocks:
  - frontend
role_basis: "识别信号扫到了什么；两边都有时写明这次实际改哪边"
```

```yaml intent_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守按识别信号定角色"
```
