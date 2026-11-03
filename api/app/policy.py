"""Tools that require human approval before the agent may continue."""

GATED_TOOLS = frozenset(
    {
        "email.send",
        "shell.exec",
        "file.delete",
    }
)


def is_gated(tool_name: str) -> bool:
    return tool_name in GATED_TOOLS
