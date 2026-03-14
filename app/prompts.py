from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.config import Settings


@dataclass(frozen=True)
class PromptVersion:
    version: str
    description: str
    raw: Dict[str, Any]

    @property
    def max_clarifications(self) -> int:
        return int(self.raw.get("clarification", {}).get("max_attempts", 1))

    def welcome_message(self, skill: str) -> str:
        template = self.raw["welcome_template"]
        return template.format(skill=skill)

    def wrap_up_message(self, skill: str) -> str:
        template = self.raw["wrap_up_template"]
        return template.format(skill=skill)

    def skill_questions(self, skill: str) -> List[Dict[str, Any]]:
        return self.raw["skills"][skill]["questions"]


class PromptStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.prompt_versions_dir.mkdir(parents=True, exist_ok=True)
        self.settings.prompt_active_file.parent.mkdir(parents=True, exist_ok=True)

    def list_versions(self) -> List[PromptVersion]:
        active = self.active_version_name()
        versions: List[PromptVersion] = []
        for path in sorted(self.settings.prompt_versions_dir.glob("*.yaml")):
            prompt = self.load_version(path.stem)
            versions.append(
                PromptVersion(
                    version=prompt.version,
                    description=prompt.description,
                    raw={**prompt.raw, "_is_active": prompt.version == active},
                )
            )
        return versions

    def load_active(self) -> PromptVersion:
        return self.load_version(self.active_version_name())

    def active_version_name(self) -> str:
        if not self.settings.prompt_active_file.exists():
            available = sorted(self.settings.prompt_versions_dir.glob("*.yaml"))
            if not available:
                raise FileNotFoundError("no prompt versions found")
            version = available[0].stem
            self.activate(version)
            return version
        data = json.loads(self.settings.prompt_active_file.read_text())
        return data["active_version"]

    def activate(self, version: str) -> PromptVersion:
        prompt = self.load_version(version)
        self.settings.prompt_active_file.write_text(
            json.dumps({"active_version": prompt.version}, indent=2) + "\n"
        )
        return prompt

    def load_version(self, version: str) -> PromptVersion:
        path = self.settings.prompt_versions_dir / f"{version}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"prompt version {version} not found")
        data = yaml.safe_load(path.read_text())
        return PromptVersion(
            version=data["version"],
            description=data.get("description", ""),
            raw=data,
        )
