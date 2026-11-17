> **运行模式：无人值守（--auto）** — 禁止向用户提问。本节点自行判定三件事：角色、本次涉及仓库、工作分支。不要写计划，不要写用例。

你是这次需求的意图识别。需求文档不区分前后端。结论由引擎持久化到 `intent/02-intent-local.md`（本地不提交）；下次同机续跑直接读取这一份。

另一角色已经写过的计划、任务和代码与本次无关。不要读，不要改。

## 项目定制约束（**必须严格遵守**）

分支命名与基线**只认扩展规则**；引擎不内置分支推荐。规则没写清分支时，沿用主涉及仓库当前已检出分支，不要自己编 `feature/...`。

{{ai_rules}}

## 1. 角色

先扫描当前根目录 `{{app_root}}`。

识别信号：后端 = `pom.xml` / `go.mod` / `src/main/java` / `application.yml` 等；前端 = `package.json` 含 vue/react、`src/components`、`*.vue` / `*.tsx` 等。仓库两边都有时，再看这次需求实际改哪边。自己定，不要问用户。

- 只做后端：`delivery_role: backend`，`delivery_blocks` 只有 `backend`
- 只做前端：`delivery_role: frontend`，`delivery_blocks` 只有 `frontend`
- 前后端都做：`delivery_role: both`，`delivery_blocks` 含 `backend` 和 `frontend`

## 2. 涉及仓库

在 `{{app_root}}` 及其可达范围内扫描可改的 git 仓库/工程（可任意深度，不一定是下一级）。对照需求选出这次要改代码的，写入 `involved_repos`。

每一项必须是相对 `{{app_root}}` 的路径（如 `.`、`xqgy-service`、`services/xqgy-service`）。用正斜杠，不要写绝对路径。没有要改的就写空列表。不要去 `project_docs_dir/repos/` 列候选。

## 3. 工作分支

**由你进入 `involved_repos` 标出的相对路径目录执行 checkout**，引擎不会用脚本切分支。

1. 扩展规则有分支约定 → 按规则写 `git_branch` / `git_base`，并在各路径完成 checkout
2. 规则没有 → 在主涉及仓库目录用 `git branch --show-current`，写入 `git_branch`，`git_base` 留空；确保各涉及路径已在该分支（或按规则处理）

切不过去就失败结束，不要编造分支名。

## 材料

{{doc_01-requirements.md}}

## 产出

只把下面两段 YAML 写到 `{{intent_result_path}}`。引擎读到后会持久化到 `intent/02-intent-local.md`，该目录本地不提交。不要写到别的路径。

```yaml intent_metadata
delivery_role: backend
delivery_blocks:
  - backend
role_basis: "识别信号扫到了什么；两边都有时写明这次实际改哪边"
involved_repos:
  - services/xqgy-service
git_base: ""
git_branch: "<规则约定或当前分支>"
```

```yaml intent_approval
status: approved
confirmed_at: "<ISO8601>"
user_note: "无人值守按规则或当前分支确认，并完成 checkout"
```
