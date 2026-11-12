from copy import deepcopy
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .ai import QwenClient


class ReviewState(TypedDict):
    minutes: dict[str, Any]
    transcript: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    score: float
    passed: bool
    current_round: int
    max_rounds: int


def rule_issues(minutes: dict[str, Any], valid_segment_ids: set[int]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for field in ("decisions", "action_items", "open_questions", "risks"):
        for index, item in enumerate(minutes.get(field) or []):
            evidence = [value for value in item.get("evidence_segment_ids", []) if value in valid_segment_ids]
            if not evidence:
                issues.append({"field": field, "index": index, "severity": "high", "message": "缺少可追溯的转写证据"})
    for index, item in enumerate(minutes.get("action_items") or []):
        if not item.get("owner"):
            issues.append({"field": "action_items", "index": index, "severity": "medium", "message": "行动项缺少负责人"})
        if not item.get("due"):
            issues.append({"field": "action_items", "index": index, "severity": "medium", "message": "行动项缺少截止时间"})
    if not minutes.get("summary"):
        issues.append({"field": "summary", "index": 0, "severity": "high", "message": "纪要摘要为空"})
    if not minutes.get("topics"):
        issues.append({"field": "topics", "index": 0, "severity": "high", "message": "纪要遗漏全部议题"})
    return issues


def safe_revision(minutes: dict[str, Any], valid_segment_ids: set[int]) -> dict[str, Any]:
    revised = deepcopy(minutes)
    for item in revised.get("action_items") or []:
        item["owner"] = item.get("owner") or "待确认"
        item["due"] = item.get("due") or "待确认"
    for field in ("topics", "decisions", "action_items", "open_questions", "risks"):
        for item in revised.get(field) or []:
            item["evidence_segment_ids"] = [value for value in item.get("evidence_segment_ids", []) if value in valid_segment_ids]
    return revised


def build_review_graph(ai: QwenClient):
    def audit(state: ReviewState) -> dict[str, Any]:
        valid_ids = {int(segment["id"]) for segment in state["transcript"]}
        issues = rule_issues(state["minutes"], valid_ids)
        issues.extend(issue for issue in ai.review_minutes(state["minutes"], state["transcript"]) if isinstance(issue, dict))
        deduped = list({(i.get("field"), i.get("index"), i.get("message")): i for i in issues}.values())
        score = max(0.0, 100.0 - sum(18 if i.get("severity") == "high" else 8 for i in deduped))
        return {
            "issues": deduped,
            "score": score,
            "passed": not deduped,
            "current_round": state["current_round"] + 1,
        }

    def route(state: ReviewState) -> str:
        if state["passed"] or state["current_round"] >= state["max_rounds"]:
            return "finish"
        return "revise"

    def revise(state: ReviewState) -> dict[str, Any]:
        valid_ids = {int(segment["id"]) for segment in state["transcript"]}
        candidate = ai.revise_minutes(state["minutes"], state["issues"], state["transcript"])
        revised = candidate if isinstance(candidate, dict) else safe_revision(state["minutes"], valid_ids)
        before_count = sum(len(state["minutes"].get(field) or []) for field in ("topics", "decisions", "action_items", "risks"))
        after_count = sum(len(revised.get(field) or []) for field in ("topics", "decisions", "action_items", "risks"))
        if before_count and after_count < max(1, before_count // 2):
            revised = safe_revision(state["minutes"], valid_ids)
        return {"minutes": revised}

    builder = StateGraph(ReviewState)
    builder.add_node("audit", audit)
    builder.add_node("revise", revise)
    builder.add_edge(START, "audit")
    builder.add_conditional_edges("audit", route, {"revise": "revise", "finish": END})
    builder.add_edge("revise", "audit")
    return builder.compile()
