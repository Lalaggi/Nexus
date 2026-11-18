"""The nexus's own lightweight goal and task system."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, register

STATUSES = ["pending", "in_progress", "done", "blocked"]


async def task_create(ctx: ToolContext, args: dict) -> ToolResult:
    title = str(args.get("title", "")).strip()
    if not title:
        return ToolResult(content="A task title is required.", ok=False)
    current = await ctx.db.list_tasks(ctx.chat_id)
    if len(current) >= 25:
        return ToolResult(content="This conversation already has 25 tasks. Finish or reuse existing ones.", ok=False)
    status = str(args.get("status") or "pending")
    if status not in STATUSES:
        status = "pending"
    task = await ctx.db.create_task(ctx.chat_id, title, str(args.get("detail", "")), status)
    await ctx.notify_tasks()
    return ToolResult(
        content=f"Created task {task['id']}: {task['title']} [{task['status']}]",
        summary=f"Task: {task['title'][:60]}",
        data={"task": task},
    )


async def task_update(ctx: ToolContext, args: dict) -> ToolResult:
    task_id = str(args.get("task_id", "")).strip()
    if not task_id:
        return ToolResult(content="task_id is required. Use task_list to see task IDs.", ok=False)
    task = await ctx.db.get_task(task_id)
    if task is None or task["chat_id"] != ctx.chat_id:
        return ToolResult(content=f"No task with id {task_id} in this conversation.", ok=False)
    fields = {}
    if "title" in args:
        fields["title"] = str(args["title"]).strip()[:300]
    if "detail" in args:
        fields["detail"] = str(args["detail"]).strip()[:2000]
    if "status" in args:
        status = str(args["status"])
        if status not in STATUSES:
            return ToolResult(content=f"status must be one of: {', '.join(STATUSES)}", ok=False)
        fields["status"] = status
    updated = await ctx.db.update_task(task_id, **fields)
    await ctx.notify_tasks()
    return ToolResult(
        content=f"Updated task {task_id}: {updated['title']} [{updated['status']}]" if updated else "Task updated.",
        summary=f"Task → {fields.get('status', 'updated')}",
        data={"task": updated},
    )


async def task_list(ctx: ToolContext, args: dict) -> ToolResult:
    tasks = await ctx.db.list_tasks(ctx.chat_id)
    if not tasks:
        return ToolResult(content="No tasks yet in this conversation.", data={"tasks": []})
    lines = ["Current tasks:"]
    for task in tasks:
        detail = f" — {task['detail']}" if task["detail"] else ""
        lines.append(f"- {task['id']} [{task['status']}] {task['title']}{detail}")
    return ToolResult(content="\n".join(lines), data={"tasks": tasks})


async def set_goal(ctx: ToolContext, args: dict) -> ToolResult:
    goal = str(args.get("goal", "")).strip()
    if not goal:
        return ToolResult(content="A goal is required.", ok=False)
    await ctx.db.update_chat(ctx.chat_id, goal=goal[:1000])
    await ctx.notify_tasks()
    return ToolResult(
        content=f"Goal set: {goal[:1000]}",
        summary="Goal updated",
        data={"goal": goal[:1000]},
    )


register(
    Tool(
        name="task_create",
        description=(
            "Add a task to this conversation's visible task list. Use for multi-step work so the "
            "user can watch progress. Break the work into 2-6 concrete tasks before you start."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short imperative task title."},
                "detail": {"type": "string", "description": "Optional acceptance criteria or notes."},
                "status": {"type": "string", "enum": STATUSES},
            },
            "required": ["title"],
        },
        handler=task_create,
    )
)
register(
    Tool(
        name="task_update",
        description=(
            "Change a task's status, title, or detail. Set exactly one task to in_progress while "
            "working on it and mark it done as soon as it is complete."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID shown by task_create/task_list."},
                "status": {"type": "string", "enum": STATUSES},
                "title": {"type": "string"},
                "detail": {"type": "string"},
            },
            "required": ["task_id"],
        },
        handler=task_update,
    )
)
register(
    Tool(
        name="task_list",
        description="List the tasks and their statuses for this conversation.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=task_list,
    )
)
register(
    Tool(
        name="set_goal",
        description=(
            "Record the single overarching goal for this conversation. Useful for long or "
            "multi-part requests; it appears above the task list."
        ),
        parameters={
            "type": "object",
            "properties": {"goal": {"type": "string"}},
            "required": ["goal"],
        },
        handler=set_goal,
    )
)
