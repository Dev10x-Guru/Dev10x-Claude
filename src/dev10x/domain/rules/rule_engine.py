"""RuleEngine — single entry point for all rule evaluation.

Replaces the procedural loops in edit_validator.validate_edit_write()
and SkillRedirectValidator.validate() with a unified collection class
that supports lazy iteration (stops at first blocking match).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.documents.config_document import Config
from dev10x.domain.rules.validation_rule import Rule


@dataclass(frozen=True)
class RuleMatch:
    rule_name: str
    message: str


@dataclass
class RuleEngine:
    edit_rules: list[Rule] = field(default_factory=list)
    command_rules: list[Rule] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, *, path: Path) -> RuleEngine:
        data: dict[str, Any] = yaml.safe_load(path.read_text())
        rules = [
            Rule.from_yaml_entry(entry=entry)
            for entry in data.get("rules", [])
            if entry.get("hook_block", False)
        ]
        return cls._split_rules(rules=rules)

    @classmethod
    def from_config(cls, config: Config) -> RuleEngine:
        rules = [r for r in config.rules if r.hook_block]
        return cls._split_rules(rules=rules)

    @classmethod
    def _split_rules(cls, *, rules: list[Rule]) -> RuleEngine:
        edit_rules = [r for r in rules if r.matcher == "Edit|Write"]
        command_rules = [r for r in rules if r.matcher == "Bash"]
        return cls(edit_rules=edit_rules, command_rules=command_rules)

    def evaluate(
        self,
        *,
        file_path: str,
        content: str,
    ) -> RuleMatch | None:
        for rule in self.edit_rules:
            if not rule.matches_file(file_path=file_path):
                continue
            if not rule.matches_content(content=content):
                continue
            return RuleMatch(
                rule_name=rule.name,
                message=rule.format_message(file_path=file_path),
            )
        return None

    def evaluate_command(self, *, command: str) -> Rule | None:
        for rule in self.command_rules:
            if rule.matches_command(command=command):
                return rule
        return None
