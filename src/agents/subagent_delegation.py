"""计划主会话把测试用例交给后台 subagent 的说明。

引擎不直接调用各 CLI 的 subagent API，只把对应工具的启动说明写进主会话 prompt。
新增工具时在此登记一段启动说明，主会话流程不用再分叉。
"""

from __future__ import annotations

from pathlib import Path

from .prompt_file import launch_read_prompt


def testcase_delegation(tool_name: str, prompt_file: Path, output_label: str) -> str:
    """按主会话工具生成「立刻拉起一个用例 subagent」的说明。"""
    key = tool_name.strip()
    if key == "omp":
        key = "oh_my_pi"
    builder = _BUILDERS.get(key)
    if builder is None:
        known = ", ".join(sorted(_BUILDERS))
        raise ValueError(
            f"工具 {tool_name} 没有用例 subagent 启动说明。已接入: {known}"
        )
    return builder(prompt_file, output_label)


def testcase_ready_note(output_label: str) -> str:
    return f"""## 测试用例

`{output_label}` 已就绪。不要启动 subagent，不要修改该文件。
"""


def _shared_rules(prompt_file: Path, output_label: str) -> str:
    launch = launch_read_prompt(prompt_file)
    return f"""prompt 逐字使用下面这段，不要改写成你自己的用例，也不要把本会话的对话历史交给它：

{launch}

用例文件与计划文件使用同一个角色后缀：只做后端是 `backend`，只做前端是 `front`，两边都做是 `all`。
目标是 `{output_label}`。不要写不带后缀的 `02-test-cases.md`。
你禁止自己写用例。子代理在后台写文件的同时，你继续完成本会话的计划工作。
在把计划文件里的 `plan_approval` 写成 `approved` 之前，确认用例文件里已经有 `test_cases_approval.status: pending`（人已经确认过则是 `approved`）。没有这个确认块表示用例还在写，不要收尾。
"""


def _cursor(prompt_file: Path, output_label: str) -> str:
    return f"""## 启动动作（先定角色，再拉起用例）

先确定这次是只做后端、只做前端，还是两边都做，并选定文件名后缀（`backend` / `front` / `all`）。然后立刻用 Task 工具启动且只启动一个后台 subagent，再继续写计划。不要等它结束才开始写计划。

Task 参数必须是：
- subagent_type: `generalPurpose`
- run_in_background: `true`
- model: `inherit`
- description: `design test cases`

{_shared_rules(prompt_file, output_label)}"""


def _claude_code(prompt_file: Path, output_label: str) -> str:
    return f"""## 启动动作（先定角色，再拉起用例）

先确定这次是只做后端、只做前端，还是两边都做，并选定文件名后缀（`backend` / `front` / `all`）。然后立刻调用 Task，只调用一次，让它在后台跑，再继续写计划。不要等它写完才开始写计划。若当前工具列表里没有 Task、只有 Agent，就调用 Agent。

参数必须是：
- subagent_type: `general-purpose`（不要用 Explore 或 Plan）
- run_in_background: `true`
- model: `inherit`
- description: `design test cases`

{_shared_rules(prompt_file, output_label)}"""


def _codex(prompt_file: Path, output_label: str) -> str:
    return f"""## 启动动作（先定角色，再拉起用例）

先确定这次是只做后端、只做前端，还是两边都做，并选定文件名后缀（`backend` / `front` / `all`）。然后立刻调用 spawn_agent，只调用一次，再继续写计划。不要等它写完才开始写计划。子代理还在写文件时，不要调用 interrupt_agent 或 close_agent，也不要另开 shell 去等文件出现。

参数必须是：
- fork_turns: `none`。新线程从空白开始，只接收下面的 message，不要带上本会话已经说过的内容
- task_name: `design test cases`
- message: 下面这段原文

{_shared_rules(prompt_file, output_label)}"""


def _oh_my_pi(prompt_file: Path, output_label: str) -> str:
    return f"""## 启动动作（先定角色，再拉起用例）

先确定这次是只做后端、只做前端，还是两边都做，并选定文件名后缀（`backend` / `front` / `all`）。然后立刻调用 task，只调用一次，再继续写计划。不要等它写完才开始写计划。

这一次调用只放一个子任务，按下面的字段填：
- context: `按 task 字段里的文件写测试用例`
- tasks 只有一条：
  - name: `design test cases`
  - agent: `task`（这个角色可以写文件；不要用只读的 scout）
  - solutionSpace: `prompt 文件已规定用例写法和输出路径，按文件直接写入`
  - task: 下面这段原文
- 不要传 isolated。传了之后子任务只交回补丁，不会把文件写到目标路径。

{_shared_rules(prompt_file, output_label)}"""


_BUILDERS = {
    "cursor": _cursor,
    "claude_code": _claude_code,
    "codex": _codex,
    "oh_my_pi": _oh_my_pi,
}
