from __future__ import annotations

import factory

from dev10x.domain.events.hook_input import HookInput


class HookInputFaker(factory.Factory):
    class Meta:
        model = HookInput

    tool_name = factory.Faker("random_element", elements=["Bash", "Edit", "Write", "Read"])
    command = factory.Faker("sentence", nb_words=4)
    raw = factory.LazyAttribute(
        lambda o: {
            "tool_name": o.tool_name,
            "tool_input": {"command": o.command},
        }
    )
    cwd = factory.Faker("file_path", depth=3)


class BashHookInputFaker(HookInputFaker):
    tool_name = "Bash"
    command = factory.Faker(
        "random_element",
        elements=[
            "git commit -m 'test'",
            "git push origin main",
            "pytest --tb=short",
            "ruff check .",
        ],
    )


class EditHookInputFaker(HookInputFaker):
    tool_name = "Edit"
    command = ""
    raw = factory.LazyAttribute(
        lambda o: {
            "tool_name": o.tool_name,
            "tool_input": {
                "file_path": o.cwd,
                "old_string": "original",
                "new_string": "replacement",
            },
        }
    )
