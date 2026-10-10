from __future__ import annotations
import asyncio
from collections import Counter
import json
from pathlib import Path
from paperseek_community.composition import execute_fixture_search
from paperseek_community.settings import CommunityDeploymentSettings


def review_settings():
    return CommunityDeploymentSettings(llm_api_type="openai_chat", llm_base_url="https://model.example/v1",
        llm_model="test-writing", llm_api_key="", openalex_api_key="", semantic_scholar_api_key="",
        pubmed_api_key="", wos_api_key="", google_scholar_api_key="", contact_email="")

ROUTE = {"provider": "custom", "api_type": "openai_chat", "base_url": "https://model.example/v1", "model": "test-writing"}


class ReviewLLM:
    def __init__(self):
        self.calls = Counter()
        self.block = ""
        self.entered = asyncio.Event()

    async def chat_json(self, messages, **_):
        if messages[0]["content"].startswith("You are a strict JSON formatter"):
            # The formatting pass may only re-encode content; a fixture cannot invent structure.
            self.calls["format"] += 1
            return messages[1]["content"]
        task = messages[0]["content"].split("TASK: ", 1)[1].split("\n", 1)[0]
        self.calls[task] += 1
        if self.block == task:
            self.entered.set()
            await asyncio.Event().wait()
        data = json.loads(messages[1]["content"])
        if task == "evidence":
            result = {"cards": [{"paper_id": paper["id"], "evidence": [
                {"category": "finding", "text": "Evidence described in the abstract.", "quote": paper["abstract"][:200]}]
            } for paper in data["papers"]]}
        elif task == "outline":
            ids = [paper["id"] for paper in data["papers"]]
            count = data["section_count"]
            result = {"focus": "Compare methods and their study settings.", "sections": [
                {"id": "theme" if i == 0 else "summary" if count >= 5 and i == count - 1 else f"theme_{i + 1}",
                 "title": "Summary" if count >= 5 and i == count - 1 else f"Common findings {i + 1}",
                 "kind": "conclusion" if count >= 5 and i == count - 1 else "theme",
                 "goal": "Compare the selected evidence.", "paper_ids": ids,
                 "paragraphs": [{"goal": "Compare findings across study settings.", "paper_ids": ids}]
                 * data.get("paragraphs_per_section", 1)}
                for i in range(count)]}
        elif task in {"section", "section_repair", "section_edit"}:
            result = {"paragraphs": [{"text": "The selected abstracts describe related research with differing scopes.",
                                       "evidence_ids": [item["id"] for item in data["abstract_evidence"]]}
                                      for _ in data["section"].get("paragraphs") or [None]]}
        elif task == "section_condense":
            result = {"text": "Condensed synthesis of the planned argument.",
                      "evidence_ids": data["paragraph"]["evidence_ids"]}
        elif task == "support_check":
            result = {"findings": [{"paragraph": p["index"], "status": "supported", "reason": "Fixture evidence check."}
                                    for p in data["paragraphs"]]}
        elif task == "consistency_check":
            result = {"has_material_issue": False, "findings": []}
        else:
            raise AssertionError(task)
        return json.dumps(result)


def create_source(directory: Path, count: int = 2):
    fixture_data = json.loads((Path(__file__).parent / "m1_fixed_source.json").read_text(encoding="utf-8"))
    template = fixture_data["records"][0]
    fixture_data["records"] = []
    for index in range(1, count + 1):
        paper = json.loads(json.dumps(template))
        paper.update(uid=f"fixed-{index:03}", title=f"Synthetic review study {index}",
                     abstract=f"Study {index} compares durable workflows and recovery boundaries under setting {index}.")
        fixture_data["records"].append(paper)
    fixture_data["llm_responses"][-2] = json.dumps({"scores": [[i, 9] for i in range(1, count + 1)]})
    fixture_data["llm_responses"][-1] = json.dumps({"reasons": [[i, "Relevant fixture."] for i in range(1, count + 1)]})
    fixture = directory / "review-source.json"
    fixture.write_text(json.dumps(fixture_data), encoding="utf-8")
    return execute_fixture_search(directory / "paperseek.db", fixture, fixture_data["question"], owner_id="fixture")
