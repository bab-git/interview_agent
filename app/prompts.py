from __future__ import annotations

import copy
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

    def create_version(self, request: Dict[str, Any]) -> PromptVersion:
        version = request["version"]
        path = self.settings.prompt_versions_dir / f"{version}.yaml"
        if path.exists():
            raise FileExistsError(f"prompt version {version} already exists")

        base_version = request.get("base_version") or self.active_version_name()
        base_prompt = copy.deepcopy(self.load_version(base_version).raw)

        base_prompt["version"] = version
        base_prompt["description"] = request["description"]

        if request.get("welcome_template") is not None:
            base_prompt["welcome_template"] = request["welcome_template"]
        if request.get("wrap_up_template") is not None:
            base_prompt["wrap_up_template"] = request["wrap_up_template"]
        if request.get("evaluation_system_prompt") is not None:
            base_prompt.setdefault("evaluation", {})
            base_prompt["evaluation"]["system_prompt"] = request["evaluation_system_prompt"]
        if request.get("max_clarifications") is not None:
            base_prompt.setdefault("clarification", {})
            base_prompt["clarification"]["max_attempts"] = request["max_clarifications"]

        overrides = request.get("skill_question_overrides", {})
        for skill, questions in overrides.items():
            if skill not in base_prompt["skills"]:
                raise KeyError(f"skill {skill} not found in prompt")
            questions_by_id = {
                question["id"]: question for question in base_prompt["skills"][skill]["questions"]
            }
            for patch in questions:
                question_id = patch["id"]
                if question_id not in questions_by_id:
                    raise KeyError(f"question {question_id} not found under skill {skill}")
                target = questions_by_id[question_id]
                if patch.get("prompt") is not None:
                    target["prompt"] = patch["prompt"]
                if patch.get("fallback_probe") is not None:
                    target["fallback_probe"] = patch["fallback_probe"]
                if patch.get("evaluation_focus") is not None:
                    target["evaluation_focus"] = patch["evaluation_focus"]

        path.write_text(yaml.safe_dump(base_prompt, sort_keys=False))
        prompt = self.load_version(version)
        if request.get("activate"):
            self.activate(version)
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
