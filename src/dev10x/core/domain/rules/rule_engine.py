"""RuleEngine — single entry point for all rule evaluation.

Replaces the procedural loops in edit_validator.validate_edit_write()
and SkillRedirectValidator.validate() with a unified collection class
that supports lazy iteration (stops at first blocking match).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.common.config_io import load_yaml
from dev10x.domain.documents.config_document import Config
from dev10x.domain.rules.validation_rule import MatchingRule


@dataclass(frozen=True)
class RuleMatch:
    rule_name: str
    message: str


@dataclass
class RuleEngine:
    edit_rules: list[MatchingRule] = field(default_factory=list)
    command_rules: list[MatchingRule] = field(default_factory=list)
    # Advisory Bash rules that opted into a live, non-blocking steer
    # (GH-1725). Every other advisory rule is still dropped here.
    hint_rules: list[MatchingRule] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, *, path: Path) -> RuleEngine:
        data = load_yaml(path, strict=True)
        # A file read here has always treated a missing `hook_block` as
        # advisory, unlike MatchingRule's own default of blocking.
        rules = [
            MatchingRule.from_yaml_entry(entry={"hook_block": False, **entry})
            for entry in data.get("rules", [])
        ]
        return cls._split_rules(rules=rules)

    @classmethod
    def from_config(cls, config: Config) -> RuleEngine:
        return cls._split_rules(rules=config.rules)

    @classmethod
    def _split_rules(cls, *, rules: list[MatchingRule]) -> RuleEngine:
        blocking = [r for r in rules if r.hook_block]
        return cls(
            edit_rules=[r for r in blocking if r.matcher == "Edit|Write"],
            command_rules=[r for r in blocking if r.matcher == "Bash"],
            hint_rules=[
                r for r in rules if not r.hook_block and r.live_hint and r.matcher == "Bash"
            ],
        )

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

    def matching_command_rules(self, *, command: str) -> Iterator[MatchingRule]:
        return (rule for rule in self.command_rules if rule.matches_command(command=command))

    def evaluate_command(self, *, command: str) -> MatchingRule | None:
        return next(self.matching_command_rules(command=command), None)

    def matching_hint_rule(self, *, command: str) -> MatchingRule | None:
        return next((r for r in self.hint_rules if r.matches_command(command=command)), None)
