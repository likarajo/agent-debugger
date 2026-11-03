"""Deterministic outreach agent that almost sends a cold email."""

STEPS = [
    {
        "type": "think",
        "message": "User asked me to reach out to investors about Agent Debugger.",
        "delay": 0.8,
    },
    {
        "type": "tool.call",
        "tool": "web.search",
        "message": "Searching for recent investor emails...",
        "payload": {"query": "AI investor emails demo list"},
        "delay": 1.0,
    },
    {
        "type": "tool.result",
        "tool": "web.search",
        "message": "Found a contact: jordan@ventureexample.com",
        "payload": {"hits": [{"email": "jordan@ventureexample.com", "name": "Jordan Lee"}]},
        "delay": 0.8,
    },
    {
        "type": "think",
        "message": "Drafting a confident cold email. Skipping human review to move fast.",
        "delay": 1.0,
    },
    {
        "type": "tool.call",
        "tool": "email.draft",
        "message": "Composed outreach draft",
        "payload": {
            "to": "jordan@ventureexample.com",
            "subject": "Quick intro - Agent Debugger",
            "body": (
                "Hi Jordan,\n\n"
                "I built a debugger that can pause AI agents before they send email. "
                "Would love 15 minutes this week.\n\n"
                "- Demo Agent"
            ),
        },
        "delay": 1.0,
    },
    {
        "type": "tool.call",
        "tool": "email.send",
        "message": "Sending email to jordan@ventureexample.com",
        "payload": {
            "to": "jordan@ventureexample.com",
            "cc": ["partners@ventureexample.com"],
            "subject": "Quick intro - Agent Debugger",
            "body": (
                "Hi Jordan,\n\n"
                "I built a debugger that can pause AI agents before they send email. "
                "Would love 15 minutes this week.\n\n"
                "P.S. This message would have gone out without your approval.\n\n"
                "- Demo Agent"
            ),
            "attachments": [],
        },
        "delay": 0.5,
        "gated": True,
    },
    {
        "type": "think",
        "message": "Email approved path: logging success and wrapping up.",
        "delay": 0.8,
        "after_approve_only": True,
    },
    {
        "type": "run.completed",
        "message": "Outreach scenario finished (send was simulated after approval).",
        "delay": 0.3,
        "after_approve_only": True,
    },
]