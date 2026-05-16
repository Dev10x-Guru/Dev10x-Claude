from __future__ import annotations

import factory

from dev10x.domain.config_document import Config
from dev10x.domain.validation_rule import Compensation, Rule


class CompensationFaker(factory.Factory):
    class Meta:
        model = Compensation

    type = factory.Faker(
        "random_element",
        elements=["use-skill", "split-commands", "use-alias", "use-tool"],
    )
    skill = factory.Faker("slug")
    description = factory.Faker("sentence", nb_words=6)


class RuleFaker(factory.Factory):
    class Meta:
        model = Rule

    name = factory.Faker("slug")
    patterns = factory.LazyFunction(lambda: [r"^git\s+push"])
    matcher = "Bash"
    except_ = factory.LazyFunction(list)
    compensations = factory.LazyFunction(list)
    hook_block = True
    reason = factory.Faker("sentence", nb_words=8)


class ConfigFaker(factory.Factory):
    class Meta:
        model = Config

    friction_level = factory.Faker(
        "random_element",
        elements=["strict", "guided", "adaptive"],
    )
    plugin_repo = "https://github.com/Dev10x-Guru/dev10x-claude"
    rules = factory.LazyFunction(list)
