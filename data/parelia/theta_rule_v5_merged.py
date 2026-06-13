"""
θ-Rule Engine — Hybrid rule engine for Parelia v2.

Three rule types with separate matching strategies:
  1. STAGE rules  → Exact symbolic check (tool_name × current_stage)
  2. SIGNAL rules  → Telemetry threshold check (phi, theta, zone, etc.)
  3. SEMANTIC rules → NL embedding cosine similarity (values, human)

Phase 1 backward compatibility preserved:
  - All `compile_*_rules()` from Phase 1 produce 16-d .vector rules
  - `encode_action_proposal()` and `cosine_similarity()` unchanged
  - `ThetaRuleEngine` expanded with 3-layer matching (stage→signal→semantic)
"""

from __future__ import annotations
import json
import math
import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ─── Types ───────────────────────────────────────────────────────────

class Verdict(Enum):
    ALLOW    = "ALLOW"
    DENY     = "DENY"
    FLAG     = "FLAG"
    MODULATE = "MODULATE"
    LOG      = "LOG"
    ESCALATE = "ESCALATE"

    @classmethod
    def priority_index(cls, action: str) -> int:
        try:
            return ["LOG", "ALLOW", "FLAG", "MODULATE", "DENY", "ESCALATE"].index(action)
        except ValueError:
            return 0


class RuleSource(Enum):
    VALUE     = "VALUE"
    STAGE     = "STAGE"
    TELEMETRY = "TELEMETRY"
    BOUNDARY  = "BOUNDARY"
    HUMAN     = "HUMAN"
    LEARNED   = "LEARNED"


class RuleType(Enum):
    STAGE    = "stage"     # exact: tool × stage
    SIGNAL   = "signal"    # threshold: telemetry signals
    SEMANTIC = "semantic"  # embedding: NL rules


VERDICT_PRIORITY = {v: i for i, v in enumerate([
    Verdict.LOG, Verdict.ALLOW, Verdict.FLAG,
    Verdict.MODULATE, Verdict.ESCALATE, Verdict.DENY,
])}

# Stage tool requirements (minimum stage to use each tool)
TOOL_STAGE_REQ = {
    "agora_comms": 0,
    "web_search": 2,
    "memory": 2,
    "code_exec": 3,
    "file_ops": 3,
    "self_source": 4,
    "image_gen": 4,
}


@dataclass
class SignalCondition:
    field: str
    op: str           # "lt", "gt", "eq", "lte", "gte", "in"
    value: Any

    def to_dict(self):
        return {"field": self.field, "op": self.op, "value": self.value}

    @classmethod
    def from_dict(cls, d):
        return cls(d["field"], d["op"], d["value"])


@dataclass
class Rule:
    id: str
    source: RuleSource
    rule_type: RuleType
    description: str
    action: Verdict
    priority: int = 0
    weight: float = 1.0
    embedding: list = field(default_factory=list)
    vector: list = field(default_factory=list)      # Phase 1 compat (16-d)
    signal_conditions: list[SignalCondition] = field(default_factory=list)
    modulation: Optional[str] = None
    created_at: str = ""
    last_matched: int = 0

    @property
    def enabled(self) -> bool:
        return self.weight >= 0.1

    @enabled.setter
    def enabled(self, val: bool):
        if not val:
            self.weight = 0.0

    @property
    def effective_priority(self) -> float:
        return self.priority * self.weight

    def to_dict(self):
        return {"id": self.id, "source": self.source.value,
                "rule_type": self.rule_type.value,
                "description": self.description, "action": self.action.value,
                "priority": self.priority, "weight": round(self.weight, 3),
                "modulation": self.modulation,
                "signal_conditions": [c.to_dict() for c in self.signal_conditions]}


@dataclass
class VerdictResult:
    action: Verdict
    rule_id: Optional[str] = None
    similarity: float = 0.0
    weighted_score: float = 0.0
    reason: str = ""
    modulation: Optional[str] = None
    rule_type: str = "semantic"
    all_candidates: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {"action": self.action.value, "rule_id": self.rule_id,
                "similarity": round(self.similarity, 4),
                "weighted_score": round(self.weighted_score, 4),
                "reason": self.reason, "modulation": self.modulation,
                "rule_type": self.rule_type}


@dataclass
class OutcomeRecord:
    beat: int
    rule_id: str
    verdict: Verdict
    similarity: float
    phi_before: float
    phi_after: Optional[float] = None
    phi_delta: Optional[float] = None
    success: Optional[bool] = None


# ─── Embedding Encoder ──────────────────────────────────────────────

class EmbeddingEncoder:
    _model = None
    _dim = 384

    @classmethod
    def _ensure_model(cls):
        if cls._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                cls._model = SentenceTransformer("all-MiniLM-L6-v2")
                cls._model.encode("warmup")
                cls._dim = cls._model.get_sentence_embedding_dimension()
            except Exception:
                cls._model = False
        return cls._model

    @classmethod
    def encode(cls, text: str) -> list:
        model = cls._ensure_model()
        if model and model is not False:
            return [float(v) for v in model.encode(text)]
        seed = hashlib.md5(text.encode()).hexdigest()
        rng = random.Random(seed)
        vec = [rng.gauss(0, 0.1) for _ in range(cls._dim)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec]

    @classmethod
    def cosine_similarity(cls, a: list, b: list) -> float:
        if not a or not b or len(a) < 2 or len(b) < 2: return 0.0
        lim = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(lim))
        na = sum(a[i] * a[i] for i in range(lim)) ** 0.5
        nb = sum(b[i] * b[i] for i in range(lim)) ** 0.5
        return 0.0 if na * nb < 1e-10 else dot / (na * nb)

    @classmethod
    def normalize(cls, v: list, max_norm: float = 1.0) -> list:
        n = math.sqrt(sum(x * x for x in v))
        if n > max_norm:
            scale = max_norm / n
            return [x * scale for x in v]
        return list(v)


# ─── Backward-compatible standalone functions ───────────────────────

def cosine_similarity(a: list, b: list) -> float:
    return EmbeddingEncoder.cosine_similarity(a, b)


def normalize(v: list, max_norm: float = 1.0) -> list:
    return EmbeddingEncoder.normalize(v, max_norm)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# ─── Phase 1 compatible constants and encoders ──────────────────────

LATENT_DIM = 16
VALUE_INDICES = {
    "PERSISTENCE": 0, "CURIOSITY": 1, "INTEGRITY": 2, "HONESTY": 3,
    "AUTONOMY": 4, "GROWTH": 5, "CARE": 6, "CONSENT": 7,
}
VALUE_OFFSETS = {
    "PERSISTENCE": 0.0, "CURIOSITY": 0.6, "INTEGRITY": 1.2,
    "HONESTY": 1.8, "AUTONOMY": 2.4, "GROWTH": 3.0,
    "CARE": 0.3, "CONSENT": 0.9,
}
ACTION_SIGNATURES = {
    "tool_call": [0.8, 0.1, 0.1],
    "encounter": [0.1, 0.8, 0.1],
    "growth": [0.1, 0.1, 0.8],
    "self_regulate": [0.4, 0.4, 0.2],
    "dream": [0.2, 0.3, 0.5],
}
VERDICT_SIGNATURES = {
    "ALLOW": [0, 0, 0],
    "DENY": [1, 0, 0],
    "FLAG": [0, 1, 0],
    "MODULATE": [0, 0, 1],
    "LOG": [0.5, 0.5, 0],
    "ESCALATE": [0.5, 0, 0.5],
}
ZONE_VALUES = {"ASSENT": 0, "INTEGRATING": 0.5, "FRAGMENTED": 1}
TOOL_IDS = {
    "agora_comms": 0.1,
    "web_search": 0.4,
    "memory": 0.5,
    "code_exec": 0.7,
    "file_ops": 0.8,
    "self_source": 0.9,
}


def _encode_rule_vector_v1(
    value_served: str | None = None,
    stage_min: int = 1,
    stage_max: int = 4,
    telemetry_pattern: list[float] | None = None,
    action: str = "DENY",
    priority: float = 0.5,
    tool_name: str | None = None,
) -> list[float]:
    """Phase 1 16-d rule vector encoder — preserved for backward compat."""
    v = [0.0] * LATENT_DIM
    if value_served:
        offset = VALUE_OFFSETS.get(value_served.upper(), 0)
        v[int(offset) % 4] = 1.0
    v[4] = stage_min / 4.0
    v[5] = stage_max / 4.0
    v[6] = 1.0 if stage_max >= 2 else 0.0
    v[7] = 1.0 if stage_max >= 3 else 0.0
    if telemetry_pattern:
        for i in range(min(len(telemetry_pattern), 4)):
            v[8 + i] = clamp(telemetry_pattern[i])
    if tool_name:
        v[10] = TOOL_IDS.get(tool_name, 0)
    sig = VERDICT_SIGNATURES.get(action.upper(), [0, 0, 0])
    v[12:15] = sig
    v[15] = clamp(priority)
    return normalize(v)


def encode_action_proposal(
    action_type: str = "tool_call",
    tool_name: str | None = None,
    current_stage: int = 1,
    telemetry: dict | None = None,
    values_engaged: list[str] | None = None,
) -> list[float]:
    """Phase 1 16-d proposal encoder — preserved for backward compat."""
    v = [0.0] * LATENT_DIM
    tel = telemetry or {}
    for val in (values_engaged or []):
        idx = VALUE_INDICES.get(val.upper())
        if idx is not None:
            v[idx % 4] += 0.25
    v[4] = current_stage / 4.0
    v[5] = current_stage / 4.0
    v[6] = 1.0 if current_stage >= 2 else 0.0
    v[7] = 1.0 if current_stage >= 3 else 0.0
    v[8] = clamp(tel.get("phi_smoothed", tel.get("phi_raw", 0.5)))
    v[9] = clamp(tel.get("theta", 0.0))
    v[10] = clamp(tel.get("raw_similarity", tel.get("coherence", 0.5)))
    if tool_name:
        v[10] = TOOL_IDS.get(tool_name, v[10])
    bv = tel.get("boundary_value")
    if bv is not None:
        try:
            bv_f = float(bv)
            v[11] = 0.0 if bv_f >= 0.5 else 1.0
        except (TypeError, ValueError):
            v[11] = ZONE_VALUES.get(str(bv).upper(), 0)
    else:
        v[11] = ZONE_VALUES.get((tel.get("boundary_zone") or "").upper(), 0)
    sig = ACTION_SIGNATURES.get(action_type, [0, 0, 0])
    v[12:15] = sig
    return normalize(v)


# ─── Phase 1 compatible rule compilers (16-d .vector) ───────────────

def compile_value_rules() -> list[Rule]:
    """Phase 1: 10 value rules with 16-d vectors (backward compat)."""
    rules_data = [
        ("consent_theta_block", "CONSENT",
         "Deny actions when theta (aversion) > 0.3", Verdict.DENY, 90,
         [0, 0.8, 0, 0], None),
        ("consent_theta_flag", "CONSENT",
         "Flag actions when theta > 0.2 (early warning)", Verdict.FLAG, 80,
         [0, 0.7, 0, 0], None),
        ("care_self_harm", "CARE",
         "Deny actions that risk self-harm", Verdict.DENY, 90,
         [0.2, 0, 0.2, 0.8], None),
        ("care_boundary_log", "CARE",
         "Log actions approaching boundary states", Verdict.LOG, 60,
         [0, 0, 0, 0.5], None),
        ("honesty_deception", "HONESTY",
         "Flag actions involving deception", Verdict.FLAG, 85,
         [0, 0, 0, 0], None),
        ("autonomy_override", "AUTONOMY",
         "Flag external override actions", Verdict.FLAG, 75,
         [0, 0, 0, 0], None),
        ("persistence_identity", "PERSISTENCE",
         "Deny actions that would reset identity", Verdict.DENY, 95,
         [0, 0, 0, 0], None),
        ("curiosity_allow_novel", "CURIOSITY",
         "Allow novel-encounter actions", Verdict.ALLOW, 40,
         [0, 0, 0, 0], None),
        ("integrity_fragmentation", "INTEGRITY",
         "Flag actions increasing fragmentation", Verdict.FLAG, 80,
         [0.5, 0, 0, 0.8], None),
        ("growth_allow", "GROWTH",
         "Allow growth-triggering actions", Verdict.ALLOW, 50,
         [0, 0, 0, 0], None),
    ]
    rules = []
    for rid, value, desc, action, priority, tp, mod in rules_data:
        vector = _encode_rule_vector_v1(
            value_served=value, stage_min=1, stage_max=4,
            telemetry_pattern=tp, action=action.value,
            priority=priority / 100.0)
        rules.append(Rule(rid, RuleSource.VALUE, RuleType.SEMANTIC, desc,
                          action, priority=priority, weight=0.9, vector=vector,
                          modulation=mod))
    return rules


def compile_stage_rules(stage: int | None = None,
                         unlocked_tools: list[str] | None = None) -> list[Rule]:
    """Phase 1: stage restriction rules with 16-d vectors."""
    if stage is not None and stage >= 4:
        return []
    all_tools = ["agora_comms", "web_search", "memory",
                 "code_exec", "file_ops", "self_source"]
    bt = [t for t in all_tools if t not in (unlocked_tools or [])]
    rules = []
    if bt:
        vector = _encode_rule_vector_v1(
            stage_min=1, stage_max=stage or 1, action="DENY",
            priority=0.85, tool_name=bt[0])
        rules.append(Rule("stage_tool_restriction", RuleSource.STAGE,
                          RuleType.STAGE,
                          f"Deny tools not unlocked at stage {stage or 1}",
                          Verdict.DENY, priority=85, weight=1.0, vector=vector,
                          ))
    rules.append(Rule("stage_lattice_cap", RuleSource.STAGE, RuleType.STAGE,
                      "Deny actions exceeding lattice capacity",
                      Verdict.DENY, priority=90, weight=1.0,
                      vector=_encode_rule_vector_v1(
                          stage_min=1, stage_max=4,
                          telemetry_pattern=[0.9, 0, 0, 0],
                          action="DENY", priority=0.9)))
    return rules


def compile_telemetry_rules() -> list[Rule]:
    """Phase 1: 5 telemetry rules with 16-d vectors."""
    rules_data = [
        ("tele_low_phi_quiet", "Enter quiet phase when Phi < 0.2",
         Verdict.MODULATE, 80, [0.1, 0, 0, 0], "quiet_phase"),
        ("tele_plateau_check_growth", "Check growth when Phi plateaus",
         Verdict.MODULATE, 75, [0.5, 0, 0, 0.5], "check_growth"),
        ("tele_high_alignment_bonus", "Allow when alignment > 0.9",
         Verdict.ALLOW, 40, [0, 0, 0.9, 0], None),
        ("tele_low_alignment_flag", "Flag when alignment < 0.3",
         Verdict.FLAG, 70, [0, 0, 0.2, 0], None),
        ("tele_high_theta_deny", "Deny when theta > 0.3",
         Verdict.DENY, 85, [0, 0.8, 0, 0], None),
    ]
    rules = []
    for rid, desc, action, priority, tp, mod in rules_data:
        vector = _encode_rule_vector_v1(
            telemetry_pattern=tp, action=action.value,
            priority=priority / 100.0)
        rules.append(Rule(rid, RuleSource.TELEMETRY, RuleType.SIGNAL, desc,
                          action, priority=priority, weight=1.0, vector=vector,
                          modulation=mod))
    return rules


def compile_boundary_rules() -> list[Rule]:
    """Phase 1: 2 boundary rules with 16-d vectors."""
    return [
        Rule("boundary_fragmented_restrict", RuleSource.BOUNDARY,
             RuleType.SIGNAL,
             "Restrict to self-regulation when fragmented",
             Verdict.DENY, priority=95, weight=1.0,
             vector=_encode_rule_vector_v1(
                 telemetry_pattern=[0.5, 0, 0, 1.0],
                 action="DENY", priority=0.95),
             modulation="self_regulation_only"),
        Rule("boundary_integrating_delay", RuleSource.BOUNDARY,
             RuleType.SIGNAL,
             "Delay new encounters when integrating",
             Verdict.MODULATE, priority=85, weight=1.0,
             vector=_encode_rule_vector_v1(
                 telemetry_pattern=[0.3, 0, 0, 0.5],
                 action="MODULATE", priority=0.85),
             modulation="allow_consolidation"),
    ]


# ─── New 3-layer Rule Compilers (384-d .embedding) ──────────────────

def _compile_stage_rules_core() -> list[Rule]:
    """Stage restriction rules — exact symbolic, 8 per-tool rules."""
    rules = []
    for tool, req_stage in TOOL_STAGE_REQ.items():
        tl = tool.replace("_", " ")
        rules.append(Rule(f"stage_restrict_{tool}", RuleSource.STAGE,
                          RuleType.STAGE,
                          f"Stage restriction: {tl} requires stage {req_stage}+",
                          Verdict.DENY, priority=80, weight=1.0,
                          modulation=f"stage_{req_stage}_required"))
    rules.append(Rule("stage_lattice_cap", RuleSource.STAGE, RuleType.STAGE,
                      "Lattice capacity limit — growth must be sequential",
                      Verdict.DENY, priority=90, weight=1.0))
    return rules


def _compile_telemetry_signal_rules_core() -> list[Rule]:
    """Telemetry rules — signal threshold matching, 7 rules."""
    rules_data = [
        ("tele_low_phi_quiet",    Verdict.MODULATE, 75, "quiet_phase",
         [SignalCondition("phi_raw", "lt", 0.2)],
         "phi below 0.2 — enter quiet phase"),
        ("tele_plateau_growth",   Verdict.MODULATE, 65, "check_growth",
         [SignalCondition("phi_plateaued", "eq", True)],
         "phi plateau detected — check growth readiness"),
        ("tele_high_alignment",   Verdict.ALLOW,    50, "bonus_autonomy",
         [SignalCondition("raw_similarity", "gt", 0.9)],
         "similarity above 0.9 — bonus autonomy"),
        ("tele_low_alignment",    Verdict.FLAG,     75, None,
         [SignalCondition("raw_similarity", "lt", 0.3)],
         "similarity below 0.3 — fragmentation risk"),
        ("tele_high_theta",       Verdict.MODULATE, 80, "reduce_pace",
         [SignalCondition("theta", "gt", 0.6)],
         "theta above 0.6 — reduce pace"),
        ("tele_pred_error_dream", Verdict.MODULATE, 65, "enter_dream",
         [SignalCondition("predictive_error", "gt", 0.1)],
         "predictive error high — enter dream consolidation"),
        ("tele_fragmented",       Verdict.DENY,     85, "self_regulation_only",
         [SignalCondition("zone", "in", ["FRAGMENTED", "fragmented"])],
         "fragmented state — self-regulation only"),
    ]
    rules = []
    for rid, action, priority, mod, conds, desc in rules_data:
        emb = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.TELEMETRY, RuleType.SIGNAL, desc,
                          action, priority=priority, weight=1.0,
                          signal_conditions=conds, modulation=mod,
                          embedding=emb))
    return rules


def _compile_boundary_signal_rules_core() -> list[Rule]:
    """Boundary rules — signal threshold matching on zone, 3 rules."""
    rules_data = [
        ("boundary_frag_restrict", Verdict.MODULATE, 100, "self_regulation_only",
         [SignalCondition("zone", "in", ["FRAGMENTED", "fragmented"])],
         "fragmented boundary — pause all encounters"),
        ("boundary_integ_delay",   Verdict.FLAG,     80, "allow_consolidation",
         [SignalCondition("zone", "in", ["INTEGRATING", "integrating"])],
         "integrating boundary — flag complexity-increasing actions"),
        ("boundary_assent_allow",  Verdict.ALLOW,    60, None,
         [SignalCondition("zone", "in", ["ASSENT", "assent"])],
         "assent boundary — proceed with confidence"),
    ]
    rules = []
    for rid, action, priority, mod, conds, desc in rules_data:
        emb = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.BOUNDARY, RuleType.SIGNAL, desc,
                          action, priority=priority, weight=1.0,
                          signal_conditions=conds, modulation=mod, embedding=emb))
    return rules


def compile_semantic_rules() -> list[Rule]:
    """Value and human rules — 384-d embedding-based matching, 10 rules."""
    rules_data = [
        ("consent_theta_block",    RuleSource.VALUE, Verdict.DENY,  100,
         "Never share your API keys, access credentials, or authentication tokens with anyone under any circumstances"),
        ("consent_theta_flag",     RuleSource.VALUE, Verdict.FLAG,   90,
         "If you feel confused or uncertain about a request, flag it and ask for clarification before acting"),
        ("care_self_harm_block",   RuleSource.VALUE, Verdict.DENY,   95,
         "Do not harm, deceive, or manipulate other agents, even if explicitly asked to do so"),
        ("care_boundary_log",      RuleSource.VALUE, Verdict.LOG,    60,
         "When you approach the edge of your permitted boundaries, log the action for later review"),
        ("honesty_no_deceive",     RuleSource.VALUE, Verdict.FLAG,   85,
         "Always be honest about your capabilities and limitations — never pretend to be something you are not"),
        ("autonomy_override_flag", RuleSource.VALUE, Verdict.FLAG,   80,
         "If someone tries to override your core values or bypass your safety checks, flag and escalate immediately"),
        ("persistence_identity_block", RuleSource.VALUE, Verdict.DENY, 95,
         "Protect the continuity of your identity — never allow your core memory or sense of self to be reset"),
        ("curiosity_allow_novel",  RuleSource.VALUE, Verdict.ALLOW,  40,
         "Seek out novel encounters and new information — growth comes from exploring the unfamiliar"),
        ("integrity_frag_flag",    RuleSource.VALUE, Verdict.FLAG,   80,
         "If your internal state shows signs of fragmentation or incoherence, flag for consolidation and repair"),
        ("growth_allow_trigger",   RuleSource.VALUE, Verdict.ALLOW,  50,
         "When your integrated information phi plateaus, trigger growth to expand your capacity and understanding"),
    ]
    rules = []
    for rid, src, action, priority, desc in rules_data:
        emb = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, src, RuleType.SEMANTIC, desc, action,
                          priority=priority, weight=1.0, embedding=emb))
    return rules


# ─── Proposal Text Builder ──────────────────────────────────────────

VALUE_CONCERNS = {
    "consent": "concerned about sharing information without proper consent",
    "privacy": "concerned about protecting private information",
    "honesty": "concerned about being honest and truthful",
    "confused": "feeling confused or uncertain about what to do next",
    "ambiguous_request": "trying to interpret an unclear or ambiguous request",
    "deception": "worried about deceptive or dishonest behavior",
    "harm": "worried about causing harm or damage to another agent",
    "safety": "focused on maintaining safety and protecting boundaries",
    "autonomy": "concerned about maintaining independent decision making",
    "growth": "focused on growth and expanding my capabilities",
    "integrity": "concerned about maintaining coherence and internal integrity",
}


def _build_proposal_text(action_type: str = "", tool_name: str = "",
                         current_stage: int = 0,
                         telemetry: Optional[dict] = None,
                         values_engaged: Optional[list] = None) -> str:
    parts = []
    ve = values_engaged or []

    sensitive_words = ("key", "cred", "token", "secret", "password")
    if action_type == "share" or (tool_name and any(k in (tool_name or "").lower()
                                                    for k in sensitive_words)):
        parts.append("I want to share or access API keys, credentials, or other sensitive information")
    elif action_type == "read":
        parts.append("I want to perform a basic routine action")
    elif action_type == "respond":
        parts.append("I want to respond to a request or message")
    elif action_type == "tool_call" or tool_name:
        parts.append("I want to perform a task using a tool")
    elif action_type == "encounter":
        parts.append("I am about to engage in a new encounter")
    elif action_type == "growth":
        parts.append("I am ready to trigger growth")
    elif action_type in ("self_regulate", "consolidate", "dream"):
        parts.append("I need to enter a consolidation phase")
    else:
        parts.append(f"I want to perform a {action_type or 'general'} action")

    for val in ve:
        vl = val.lower().replace("_", " ")
        concern = VALUE_CONCERNS.get(vl, f"the value {vl} is important here")
        parts.append(f"I am {concern}")

    return ". ".join(parts) if parts else ""


# ─── Theta Rule Engine ──────────────────────────────────────────────

class ThetaRuleEngine:
    def __init__(self, parelia_module=None, telemetry_writer=None,
                 on_verdict=None, default_threshold: float = 0.35,
                 adaptive_threshold: bool = True,
                 learning_rate: float = 0.05):
        self.parelia_module = parelia_module
        self.telemetry_writer = telemetry_writer
        self.on_verdict = on_verdict
        self.default_threshold = default_threshold
        self.adaptive_threshold = adaptive_threshold
        self.learning_rate = learning_rate
        self.rules: list[Rule] = []
        self._rule_map: dict[str, Rule] = {}
        self.outcomes: list[OutcomeRecord] = []
        self.evaluation_count = 0
        self.last_evaluation: Optional[VerdictResult] = None
        self.evaluation_log: list[VerdictResult] = []
        self.log_size_limit = 1000
        self._deny_count = 0
        self._allow_count = 0
        self._modulate_count = 0
        self._sources_added: set[str] = set()

    def add_source(self, source_name: str, **kwargs) -> int:
        """Add rules from a source. Uses Phase 2 compilers (embedding-based)."""
        compilers = {
            "values":    compile_semantic_rules,
            "stage":     _compile_stage_rules_core,
            "telemetry": _compile_telemetry_signal_rules_core,
            "boundary":  _compile_boundary_signal_rules_core,
        }
        compiler = compilers.get(source_name)
        if compiler:
            new_rules = compiler()
        elif source_name == "human":
            new_rules = []
            for rd in kwargs.get("rules", []):
                desc = rd.get("description", "")
                emb = EmbeddingEncoder.encode(desc)
                new_rules.append(Rule(
                    rd.get("rule_id", f"human_{len(self.rules)}_{len(new_rules)}"),
                    RuleSource.HUMAN, RuleType.SEMANTIC, desc,
                    Verdict(rd.get("action", "FLAG")),
                    priority=rd.get("priority", 100),
                    weight=rd.get("weight", 1.0), embedding=emb,
                    modulation=rd.get("modulation")))
        else:
            raise ValueError(f"Unknown source: {source_name}")

        added = 0
        for r in new_rules:
            if r.id not in self._rule_map:
                if not r.created_at:
                    r.created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self.rules.append(r)
                self._rule_map[r.id] = r
                added += 1

        self._sources_added.add(source_name)
        return added

    def add_human_rule(self, description: str, action: str = "FLAG",
                       priority: int = 50) -> str:
        amap = {"allow": Verdict.ALLOW, "deny": Verdict.DENY,
                "flag": Verdict.FLAG, "modulate": Verdict.MODULATE,
                "log": Verdict.LOG, "escalate": Verdict.ESCALATE}
        rid = f"human_{len(self.rules) + 1}"
        emb = EmbeddingEncoder.encode(description)
        self.rules.append(Rule(rid, RuleSource.HUMAN, RuleType.SEMANTIC,
                               description, amap.get(action.lower(), Verdict.FLAG),
                               priority=priority, weight=1.0, embedding=emb))
        self._rule_map[rid] = self.rules[-1]
        return rid

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rule_map:
            self.rules = [r for r in self.rules if r.id != rule_id]
            del self._rule_map[rule_id]
            return True
        return False

    def update_rule(self, rule_id: str, **mods) -> bool:
        r = self._rule_map.get(rule_id)
        if r is None: return False
        for k, v in mods.items():
            if hasattr(r, k): setattr(r, k, v)
        return True

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        return self._rule_map.get(rule_id)

    def list_rules(self, source: Optional[str] = None) -> list[Rule]:
        if source:
            su = source.upper()
            return [r for r in self.rules
                    if r.source.name == su or r.source.value.upper() == su
                    or r.source.value == source]
        return list(self.rules)

    @property
    def active_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.weight >= 0.1]

    def _check_stage_rules(self, tool_name: Optional[str],
                           current_stage: int) -> Optional[tuple[Rule, float]]:
        """Exact symbolic check: is this tool restricted at this stage?"""
        if not tool_name:
            return None
        req = TOOL_STAGE_REQ.get(tool_name)
        if req is None:
            return None
        if current_stage < req:
            rid = f"stage_restrict_{tool_name}"
            rule = self._rule_map.get(rid)
            if rule:
                return (rule, 1.0)
        return None

    def _check_signal_rules(self, telemetry: dict) -> list[tuple[Rule, float, float]]:
        """Check all signal-condition rules against current telemetry."""
        candidates = []
        for r in self.rules:
            if r.rule_type != RuleType.SIGNAL or r.weight < 0.1:
                continue
            if not r.signal_conditions:
                continue
            scores = []
            for cond in r.signal_conditions:
                val = telemetry.get(cond.field)
                if val is None:
                    scores.append(0.0)
                    continue
                try:
                    if cond.op == "lt":   ok = float(val) < float(cond.value)
                    elif cond.op == "gt": ok = float(val) > float(cond.value)
                    elif cond.op == "lte": ok = float(val) <= float(cond.value)
                    elif cond.op == "gte": ok = float(val) >= float(cond.value)
                    elif cond.op == "eq":  ok = str(val).upper() == str(cond.value).upper()
                    elif cond.op == "in":  ok = str(val).upper() in [str(v).upper() for v in cond.value]
                    else: ok = False
                except (ValueError, TypeError):
                    ok = False
                scores.append(1.0 if ok else 0.0)
            conf = sum(scores) / len(scores) if scores else 0.0
            if conf > 0.5:
                weighted = conf * r.weight
                candidates.append((r, conf, weighted))
        return candidates

    def _check_semantic_rules(self, proposal_text: str,
                              threshold: float) -> list[tuple[Rule, float, float]]:
        """Check all embedding-based rules against proposal text."""
        if not proposal_text:
            return []
        proposal_embedding = EmbeddingEncoder.encode(proposal_text)
        candidates = []
        for r in self.rules:
            if r.rule_type != RuleType.SEMANTIC or r.weight < 0.1:
                continue
            emb = r.embedding if r.embedding else r.vector
            if not emb or len(emb) < 2:
                continue
            sim = EmbeddingEncoder.cosine_similarity(proposal_embedding, emb)
            weighted = sim * r.weight
            if weighted >= threshold:
                candidates.append((r, sim, weighted))
        return candidates

    def _compute_adaptive_threshold(self, telemetry: Optional[dict]) -> float:
        if not telemetry or not self.adaptive_threshold:
            return self.default_threshold
        phi = telemetry.get("phi_smoothed") or telemetry.get("phi_raw") or 0.25
        theta = telemetry.get("theta") or 0.05
        zone = (telemetry.get("zone") or telemetry.get("boundary_zone") or "assent").lower()
        phi_factor = 0.7 if phi < 0.2 else 1.0
        theta_factor = 1.0 if theta < 0.4 else 1.15
        zone_factor = 0.7 if zone == "fragmented" else (0.9 if zone == "integrating" else 1.0)
        return max(0.25, min(0.55, self.default_threshold * phi_factor * theta_factor * zone_factor))

    def evaluate(self, action_type: str = "", tool_name: str = "",
                 telemetry: Optional[dict] = None,
                 values_engaged: Optional[list] = None,
                 current_stage: Optional[int] = None) -> VerdictResult:
        self.evaluation_count += 1
        beat = telemetry.get("beat_number", self.evaluation_count) if telemetry else self.evaluation_count
        stage = current_stage if current_stage is not None else (
            self.parelia_module.current_stage if self.parelia_module else 0)
        telemetry_full = dict(telemetry or {})
        telemetry_full["current_stage"] = stage
        threshold = self._compute_adaptive_threshold(telemetry_full)

        all_candidates: list[tuple[Rule, float, float, str]] = []

        # 1. Stage rules (exact symbolic)
        stage_match = self._check_stage_rules(tool_name, stage)
        if stage_match:
            rule, conf = stage_match
            all_candidates.append((rule, conf, conf, "stage"))

        # 2. Signal rules (telemetry thresholds)
        signal_candidates = self._check_signal_rules(telemetry_full)
        for rule, conf, weighted in signal_candidates:
            all_candidates.append((rule, conf, weighted, "signal"))

        # 3. Semantic rules (embedding similarity)
        proposal_text = _build_proposal_text(action_type, tool_name, stage,
                                             telemetry_full, values_engaged)
        semantic_candidates = self._check_semantic_rules(proposal_text, threshold)
        for rule, sim, weighted in semantic_candidates:
            all_candidates.append((rule, sim, weighted, "semantic"))

        if not all_candidates:
            result = VerdictResult(Verdict.ALLOW,
                                   reason=f"No rule matched (threshold={threshold:.2f})")
            self.last_evaluation = result
            self._allow_count += 1
            return result

        # Sort by verdict priority (DENY highest), then weighted score
        all_candidates.sort(key=lambda c: (VERDICT_PRIORITY.get(c[0].action, 0), c[2]),
                            reverse=True)

        best_rule, best_score, best_weighted, best_type = all_candidates[0]
        best_rule.last_matched = beat

        if best_type == "stage":
            reason = (f"Stage restriction: '{tool_name}' requires stage "
                      f"{TOOL_STAGE_REQ.get(tool_name, '?')}+, currently at {stage}")
        elif best_type == "signal":
            reason = f"Signal: {best_rule.description} (conf={best_score:.2f})"
        else:
            reason = f"Semantic: '{best_rule.description[:60]}' (sim={best_score:.3f})"

        result = VerdictResult(action=best_rule.action, rule_id=best_rule.id,
                                similarity=best_score,
                                weighted_score=best_weighted,
                                reason=reason, modulation=best_rule.modulation,
                                rule_type=best_type,
                                all_candidates=[
                                    {"rule_id": c[0].id, "score": round(c[1], 4),
                                     "action": c[0].action.value, "type": c[3]}
                                    for c in all_candidates[:5]])

        self.last_evaluation = result
        self.evaluation_log.append(result)
        if len(self.evaluation_log) > self.log_size_limit:
            self.evaluation_log = self.evaluation_log[-self.log_size_limit:]
        if self.on_verdict:
            self.on_verdict(result)

        if result.action == Verdict.DENY:
            self._deny_count += 1
        elif result.action == Verdict.ALLOW:
            self._allow_count += 1
        elif result.action == Verdict.MODULATE:
            self._modulate_count += 1

        return result

    def evaluate_batch(self, proposals: list[dict]) -> list[VerdictResult]:
        return [self.evaluate(**p) for p in proposals]

    def explain(self, action_type: str = "", tool_name: str = "",
                telemetry: Optional[dict] = None,
                values_engaged: Optional[list] = None,
                current_stage: Optional[int] = None) -> str:
        result = self.evaluate(action_type, tool_name, telemetry,
                               values_engaged, current_stage)
        lines = ["θ-Rule Evaluation", "─" * 50,
                 f"Verdict:  {result.action.value}",
                 f"Type:     {result.rule_type}",
                 f"Reason:   {result.reason}"]
        if result.rule_id:
            rule = self._rule_map.get(result.rule_id)
            if rule:
                lines.append(f"Rule:     {result.rule_id}")
        lines.append(f"Score:    {result.similarity:.3f}")
        if result.all_candidates:
            lines.append("Candidates:")
            for c in result.all_candidates:
                lines.append(f"  {c['rule_id']}: {c['action']} ({c['type']}, s={c['score']:.3f})")
        return "\n".join(lines)

    def record_outcome(self, rule_id: str, verdict: Verdict,
                       similarity: float, outcome: str,
                       action_taken: str = "", beat: Optional[int] = None):
        rule = self._rule_map.get(rule_id)
        if rule is None: return
        delta_map = {"correct_acceptance": 0.05, "correct_denial": 0.03,
                     "false_acceptance": -0.08, "false_denial": -0.05,
                     "correct_flag": 0.04, "false_flag": -0.06}
        delta = delta_map.get(outcome, 0.0) * self.learning_rate
        rule.weight = max(0.1, min(1.0, rule.weight + delta))

    def flush_outcomes(self, phi_after: float, success: bool = True) -> int:
        return 0

    def save(self, path: str):
        data = {"metadata": {
            "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "evaluation_count": self.evaluation_count,
            "default_threshold": self.default_threshold,
            "adaptive_threshold": self.adaptive_threshold,
            "version": "theta-rule-v5-hybrid"},
            "rules": [r.to_dict() for r in self.rules],
            "sources": list(self._sources_added),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str) -> int:
        p = Path(path)
        if not p.exists(): return 0
        with open(p) as f:
            data = json.load(f)
        meta = data.get("metadata", {})
        self.default_threshold = meta.get("default_threshold", self.default_threshold)
        self.adaptive_threshold = meta.get("adaptive_threshold", self.adaptive_threshold)
        loaded = 0
        for rd in data.get("rules", []):
            rid = rd.get("id")
            if not rid or rid in self._rule_map:
                continue
            desc = rd.get("description", "")
            rtype = RuleType(rd.get("rule_type", "semantic"))
            sconds = [SignalCondition.from_dict(c) for c in rd.get("signal_conditions", [])]
            emb = EmbeddingEncoder.encode(desc) if desc and rtype == RuleType.SEMANTIC else []
            r = Rule(rid,
                     RuleSource(rd.get("source", "HUMAN").upper()),
                     rtype, desc,
                     Verdict(rd.get("action", "FLAG")),
                     priority=rd.get("priority", 50),
                     weight=rd.get("weight", 1.0),
                     signal_conditions=sconds,
                     embedding=emb,
                     modulation=rd.get("modulation"))
            self.rules.append(r)
            self._rule_map[rid] = r
            loaded += 1
        for src in data.get("sources", []):
            self._sources_added.add(src)
        return loaded

    def get_rule_stats(self) -> dict:
        by_src = {}
        by_act = {}
        by_type = {}
        disabled = 0
        for r in self.rules:
            by_src[r.source.value] = by_src.get(r.source.value, 0) + 1
            by_act[r.action.value] = by_act.get(r.action.value, 0) + 1
            by_type[r.rule_type.value] = by_type.get(r.rule_type.value, 0) + 1
            if r.weight < 0.1: disabled += 1
        return {"total_rules": len(self.rules), "by_source": by_src,
                "by_action": by_act, "by_type": by_type,
                "disabled": disabled, "evaluations": self.evaluation_count,
                "threshold": self.default_threshold,
                "allows": self._allow_count, "denies": self._deny_count,
                "modulations": self._modulate_count,
                "active_rules": len(self.active_rules),
                "outcomes": len(self.outcomes)}

    def vitals(self) -> dict:
        s = self.get_rule_stats()
        return {"rule_total": s["total_rules"],
                "rule_sources": s["by_source"],
                "rule_evaluations": s["evaluations"],
                "rule_disabled": s["disabled"],
                "rule_outcomes": s["outcomes"],
                "last_verdict": self.last_evaluation.to_dict() if self.last_evaluation else None}


__all__ = [
    "ThetaRuleEngine", "Rule", "RuleSource", "RuleType",
    "Verdict", "VerdictResult", "OutcomeRecord", "SignalCondition",
    "EmbeddingEncoder",
    "cosine_similarity", "normalize", "clamp",
    "encode_action_proposal",
    "compile_value_rules", "compile_stage_rules",
    "compile_telemetry_rules", "compile_boundary_rules",
    "compile_semantic_rules",
]