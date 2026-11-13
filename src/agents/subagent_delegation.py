"""计划主会话把测试用例交给后台 subagent 的说明。

引擎不直接调用各 CLI 的 subagent API，只把对应工具的启动说明写进主会话 prompt。
新增工具时在此登记一段启动说明，主会话流程不用再分叉。
"""

from __future__ import annotations

from pathlib import Path

from .prompt_file import launch_read_prompt


def testcase_delegation(tool_name: str, prompt_file: Path, output_path: Path) -> str:
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
    return builder(prompt_file, output_path)


def testcase_ready_note(output_path: Path) -> str:
    target = output_path.resolve()
    return f"""## 测试用例

`{target}` 已就绪。不要启动 subagent，不要修改该文件。
"""


def _shared_rules(prompt_file: Path, output_path: Path) -> str:
    launch = launch_read_prompt(prompt_file)
    target = output_path.resolve()
    return f"""prompt 逐字使用下面这段，不要改写成你自己的用例，也不要把本会话的对话历史交给它：

{launch}

你禁止自己创建或修改 `{target}`。
子代理在后台写文件的同时，你继续完成本会话的计划工作。
在把 `02-plan.md` 里的 `plan_approval` 写成 `approved` 之前，确认 `{target}` 里已经有 `test_cases_approval.status: pending`（人已经确认过则是 `approved`）。没有这个确认块表示用例还在写，不要收尾。
"""


def _cursor(prompt_file: Path, output_path: Path) -> str:
    return f"""## 启动动作（先于写计划、先于向用户提问）

立刻用 Task 工具启动且只启动一个后台 subagent，然后继续本会话。不要等它结束才开始写计划。

Task 参数必须是：
- subagent_type: `generalPurpose`
- run_in_background: `true`
- model: `inherit`
- description: `design test cases`

{_shared_rules(prompt_file, output_path)}"""


def _claude_code(prompt_file: Path, output_path: Path) -> str:
    return f"""## 启动动作（先于写计划、先于向用户提问）

立刻调用 Task，只调用一次，让它在后台跑，然后继续本会话。不要等它写完才开始写计划。若当前工具列表里没有 Task、只有 Agent，就调用 Agent。

参数必须是：
- subagent_type: `general-purpose`（不要用 Explore 或 Plan）
- run_in_background: `true`
- model: `inherit`
- description: `design test cases`

{_shared_rules(prompt_file, output_path)}"""


def _codex(prompt_file: Path, output_path: Path) -> str:
    return f"""## 启动动作（先于写计划、先于向用户提问）

立刻调用 spawn_agent，只调用一次，然后继续本会话。不要等它写完才开始写计划。子代理还在写文件时，不要调用 interrupt_agent 或 close_agent，也不要另开 shell 去等文件出现。

参数必须是：
- fork_turns: `none`。新线程从空白开始，只接收下面的 message，不要带上本会话已经说过的内容
- task_name: `design test cases`
- message: 下面这段原文

{_shared_rules(prompt_file, output_path)}"""


def _oh_my_pi(prompt_file: Path, output_path: Path) -> str:
    return f"""## 启动动作（先于写计划、先于向用户提问）

立刻调用 task，只调用一次，然后继续本会话。不要等它写完才开始写计划。

这一次调用只放一个子任务，按下面的字段填：
- context: `按 task 字段里的文件写测试用例`
- tasks 只有一条：
  - name: `design test cases`
  - agent: `task`（这个角色可以写文件；不要用只读的 scout）
  - solutionSpace: `prompt 文件已规定用例写法和输出路径，按文件直接写入`
  - task: 下面这段原文
- 不要传 isolated。传了之后子任务只交回补丁，不会把文件写到目标路径。

{_shared_rules(prompt_file, output_path)}"""


_BUILDERS = {
    "cursor": _cursor,
    "claude_code": _claude_code,
    "codex": _codex,
    "oh_my_pi": _oh_my_pi,
}
