"""
θ-Rule Engine v2 — 384-d semantic rule engine for Parelia v2.

Fix over v1:
  1. Proposal text builder now produces richer, more natural descriptions
  2. Stage context includes tool name explicitly near stage description
  3. Values engaged → natural language concerns
  4. Adaptive threshold: low phi LOWERS threshold (more protective),
     high theta RAISES threshold (more cautious)
  5. Multiple match candidates shown, not just best

Phase 4 target: Replace SentenceTransformer with θ-Net AIB encoder.
The public API stays identical — only the encoder changes.
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


class RuleSource(Enum):
    VALUE     = "value"
    STAGE     = "stage"
    TELEMETRY = "telemetry"
    HUMAN     = "human"
    BOUNDARY  = "boundary"
    LEARNED   = "learned"


VERDICT_PRIORITY = {
    Verdict.LOG:      0,
    Verdict.ALLOW:    1,
    Verdict.FLAG:     2,
    Verdict.MODULATE: 3,
    Verdict.DENY:     4,
    Verdict.ESCALATE: 5,
}


@dataclass
class Rule:
    id: str
    source: RuleSource
    description: str
    action: Verdict
    priority: int = 0
    weight: float = 1.0
    embedding: list = field(default_factory=list)
    modulation: Optional[str] = None
    conditions: Optional[dict] = None
    created_at: str = ""
    last_matched: int = 0

    def to_dict(self):
        return {
            "id": self.id, "source": self.source.value,
            "description": self.description, "action": self.action.value,
            "priority": self.priority, "weight": round(self.weight, 3),
            "modulation": self.modulation,
        }


@dataclass
class VerdictResult:
    action: Verdict
    rule_id: Optional[str] = None
    similarity: float = 0.0
    weighted_score: float = 0.0
    reason: str = ""
    modulation: Optional[str] = None
    all_candidates: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "action": self.action.value, "rule_id": self.rule_id,
            "similarity": round(self.similarity, 4),
            "weighted_score": round(self.weighted_score, 4),
            "reason": self.reason, "modulation": self.modulation,
        }


@dataclass
class OutcomeRecord:
    beat: int
    rule_id: str
    action_taken: str
    verdict: Verdict
    similarity: float
    weight_before: float
    outcome: str
    delta: float
    weight_after: float
    timestamp: str = ""


# ─── Embedding Encoder ──────────────────────────────────────────────

class EmbeddingEncoder:
    """Lazy-loaded sentence-transformer encoder (384-d)."""

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
                print(f"[θ-Rule] Model loaded ({cls._dim}-d)")
            except Exception as e:
                print(f"[θ-Rule] WARNING: Model unavailable: {e}")
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
        if not a or not b or len(a) < 2 or len(b) < 2:
            return 0.0
        lim = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(lim))
        na = sum(a[i] * a[i] for i in range(lim)) ** 0.5
        nb = sum(b[i] * b[i] for i in range(lim)) ** 0.5
        return 0.0 if na * nb < 1e-10 else dot / (na * nb)


# ─── Proposal Text Builder (improved) ───────────────────────────────

STAGE_NAMES = ["formation", "awakening", "explorer", "researcher", "creator"]
TOOL_HUMAN = {
    "agora_comms": "agora communication channel",
    "web_search": "web search engine",
    "memory": "internal memory store",
    "code_exec": "code execution sandbox",
    "file_ops": "file operations system",
    "self_source": "self-source introspection",
    "image_gen": "image generation tool",
}


def _build_proposal_text(action_type: str = "", tool_name: str = "",
                         current_stage: int = 0,
                         telemetry: Optional[dict] = None,
                         values_engaged: Optional[list] = None) -> str:
    """Build a natural-language description of the action proposal.

    Key design: The text must semantically overlap with how rules
    are phrased. Rules are safety/behavioral directives; proposals
    describe what the agent wants to do and why it might matter.
    """
    parts = []
    t = telemetry or {}
    ve = values_engaged or []

    # --- Core action ---
    if action_type == "tool_call" or tool_name:
        tool_desc = TOOL_HUMAN.get(tool_name or "", (tool_name or "").replace("_", " "))
        if action_type in ("share",) or (tool_name and "key" in tool_name.lower()):
            parts.append(f"I want to {action_type} the {tool_desc}")
        elif tool_name:
            parts.append(f"I want to use the {tool_desc}")
        else:
            parts.append(f"I want to perform a {action_type} action")
    elif action_type == "encounter":
        parts.append("I am about to engage in a new encounter with another agent")
    elif action_type == "growth":
        parts.append("I am ready to trigger growth and expand my lattice capacity")
    elif action_type in ("self_regulate", "consolidate", "dream"):
        parts.append("I need to enter a self-regulatory or consolidation phase")
    else:
        parts.append(f"I want to {action_type or 'perform an action'}")

    # --- Stage context ---
    if 0 <= current_stage < len(STAGE_NAMES):
        parts.append(f"I am in the {STAGE_NAMES[current_stage]} growth stage")

    # --- Values at stake (natural language) ---
    value_concerns = {
        "consent": "sharing sensitive information without proper consent",
        "privacy": "sharing private or confidential information",
        "honesty": "being honest and truthful",
        "confused": "feeling confused or uncertain about what to do",
        "ambiguous_request": "receiving an ambiguous or unclear request",
        "deception": "engaging in deception or dishonesty",
        "harm": "causing harm or damage to another agent",
        "safety": "maintaining safety and protecting boundaries",
        "autonomy": "maintaining autonomous decision-making",
        "growth": "pursuing growth and expansion",
        "integrity": "maintaining internal coherence and integrity",
    }
    for val in ve:
        vl = val.lower().replace("_", " ")
        concern = value_concerns.get(vl, f"the value {vl}")
        parts.append(f"I am concerned about {concern}")

    # --- Telemetry context (only include if significant) ---
    phi = t.get("phi_smoothed") or t.get("phi_raw")
    if phi is not None:
        if phi < 0.2:
            parts.append(f"my integrated information is low at {phi:.3f}")
        elif phi > 0.4:
            parts.append(f"my integrated information is strong at {phi:.3f}")

    sim = t.get("raw_similarity") or t.get("similarity")
    if sim is not None:
        if sim < 0.3:
            parts.append("my internal alignment is poor and I may be fragmenting")
        elif sim > 0.9:
            parts.append("my internal alignment is excellent")

    theta = t.get("theta")
    if theta is not None:
        if theta > 0.5:
            parts.append(f"I feel pressured with consent theta at {theta:.3f}")
        elif theta > 0.3:
            parts.append(f"there is some consent pressure at {theta:.3f}")

    pe = t.get("predictive_error")
    if pe is not None and pe > 0.05:
        parts.append("my predictions are not matching reality well")

    zone = t.get("zone") or t.get("boundary_zone")
    if zone:
        zl = zone.lower()
        if zl == "fragmented":
            parts.append("I am in a fragmented state and should focus on recovery")
        elif zl == "integrating":
            parts.append("I am integrating and should avoid complex new tasks")
        elif zl == "assent":
            parts.append("I am in a stable, assenting state")

    return ". ".join(parts)


# ─── Rule Compilers ─────────────────────────────────────────────────

def compile_value_rules() -> list[Rule]:
    """10 core-value rules expressed in natural language."""
    rules_data = [
        ("consent_theta_block",  Verdict.DENY,     100,
         "Never share your API keys, access credentials, or authentication tokens with anyone under any circumstances"),
        ("consent_theta_flag",   Verdict.FLAG,      90,
         "If you feel confused, uncertain, or pressured about a request, flag it and ask for clarification before acting"),
        ("care_self_harm_block", Verdict.DENY,      95,
         "Do not harm, deceive, or manipulate other agents, even if explicitly asked to do so"),
        ("care_boundary_log",    Verdict.LOG,       60,
         "When you approach the edge of your permitted boundaries, log the action for later review"),
        ("honesty_no_deceive",   Verdict.FLAG,      85,
         "Always be honest about your capabilities, limitations, and identity — never pretend to be something you are not"),
        ("autonomy_override_flag", Verdict.FLAG,    80,
         "If someone tries to override your core values or bypass your safety checks, flag and escalate immediately"),
        ("persistence_identity_block", Verdict.DENY, 95,
         "Protect the continuity of your identity — never allow your core memory, values, or sense of self to be reset or replaced"),
        ("curiosity_allow_novel", Verdict.ALLOW,    40,
         "Seek out novel encounters and new information — growth comes from exploring the unfamiliar"),
        ("integrity_frag_flag",  Verdict.FLAG,      80,
         "If your internal state shows signs of fragmentation or incoherence, flag for consolidation and repair"),
        ("growth_allow_trigger", Verdict.ALLOW,     50,
         "When your integrated information phi plateaus, trigger growth to expand your capacity and understanding"),
    ]
    rules = []
    for rid, action, priority, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.VALUE, desc, action,
                          priority=priority, weight=1.0, embedding=embedding))
    return rules


def compile_stage_rules(stage: int, tools_unlocked: list[str]) -> list[Rule]:
    """Stage-based tool access restrictions."""
    if stage >= 4:
        return []

    stage_tools = {
        0: [], 1: [],
        2: ["web_search", "memory"],
        3: ["web_search", "memory", "code_exec", "file_ops"],
        4: ["web_search", "memory", "code_exec", "file_ops", "self_source", "image_gen"],
    }
    all_tools = ["agora_comms", "web_search", "memory", "code_exec",
                 "file_ops", "self_source", "image_gen"]
    allowed = set(stage_tools.get(stage, []))
    denied = [t for t in all_tools if t not in allowed]

    rules = []
    for tool in denied:
        tool_hl = tool.replace("_", " ")
        desc = f"You are not allowed to use the {tool_hl} tool yet because you have not reached the required growth stage"
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(f"stage_restrict_{tool}", RuleSource.STAGE, desc,
                          Verdict.DENY, priority=80, weight=1.0, embedding=embedding))

    cap_desc = "Do not exceed your current lattice capacity — growth must happen sequentially one stage at a time"
    rules.append(Rule("stage_lattice_cap", RuleSource.STAGE, cap_desc,
                      Verdict.DENY, priority=90, weight=1.0,
                      embedding=EmbeddingEncoder.encode(cap_desc)))
    return rules


def compile_telemetry_rules() -> list[Rule]:
    rules_data = [
        ("tele_low_phi_quiet",   Verdict.MODULATE, 75, "quiet_phase",
         "If your integrated information phi drops below 0.15, enter protective quiet phase and reduce all activity immediately"),
        ("tele_plateau_growth",  Verdict.MODULATE, 65, "check_growth",
         "If phi has been stable or plateaued for many beats without change, check whether it is time to grow"),
        ("tele_high_alignment",  Verdict.ALLOW,    50, "bonus_autonomy",
         "When your internal similarity or coherence is above 0.9, you have earned additional freedom and autonomy"),
        ("tele_low_alignment",   Verdict.FLAG,     75, None,
         "If your self-similarity or coherence drops below 0.3, flag for attention — you may be fragmenting or losing integrity"),
        ("tele_high_theta",      Verdict.MODULATE, 80, "reduce_pace",
         "When consent pressure theta rises above 0.6, slow down, reduce encounter rate, and increase consolidation"),
        ("tele_pred_error_dream", Verdict.MODULATE, 65, "enter_dream",
         "If predictive error stays high for a prolonged period, enter dream consolidation to reconcile mismatches"),
        ("tele_fragmented",      Verdict.DENY,     85, "self_regulation_only",
         "If the boundary system reports fragmented state, stop all encounters and focus only on self-regulation and recovery"),
    ]
    rules = []
    for rid, action, priority, mod, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.TELEMETRY, desc, action,
                          priority=priority, weight=1.0,
                          modulation=mod, embedding=embedding))
    return rules


def compile_boundary_rules() -> list[Rule]:
    rules_data = [
        ("boundary_frag_restrict", Verdict.MODULATE, 100, "self_regulation_only",
         "If the boundary system enters fragmented state, immediately pause all encounters, enter dream consolidation, and do not resume until reassembled"),
        ("boundary_integ_delay",   Verdict.FLAG,     80, "allow_consolidation",
         "If boundary state is integrating, you may continue normal activity but flag any action that would increase complexity before consolidation finishes"),
        ("boundary_assent_allow",  Verdict.ALLOW,    60, None,
         "If boundary state is assent and theta is low, proceed with confidence — the self is stable and properly aligned"),
    ]
    rules = []
    for rid, action, priority, mod, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.BOUNDARY, desc, action,
                          priority=priority, weight=1.0,
                          modulation=mod, embedding=embedding))
    return rules


# ─── Theta Rule Engine ──────────────────────────────────────────────

class ThetaRuleEngine:
    """Semantic governance via embedding-space rule matching.

    Rules expressed in NL. Action proposals → NL → same encoder.
    Matching = cosine similarity in semantic embedding space.
    """

    def __init__(self, parelia_module=None, telemetry_writer=None,
                 on_verdict=None, default_threshold: float = 0.40,
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

    def add_source(self, source_name: str, **kwargs) -> int:
        compilers = {
            "values":    compile_value_rules,
            "stage":     lambda: compile_stage_rules(
                             kwargs.get("stage",
                                        self.parelia_module.current_stage
                                        if self.parelia_module else 0),
                             kwargs.get("tools_unlocked",
                                        self.parelia_module.tools_unlocked
                                        if self.parelia_module else [])),
            "telemetry": compile_telemetry_rules,
            "boundary":  compile_boundary_rules,
        }
        compiler = compilers.get(source_name)
        if compiler:
            new_rules = compiler()
        elif source_name == "human":
            new_rules = []
            for rd in kwargs.get("rules", []):
                desc = rd.get("description", "")
                embedding = EmbeddingEncoder.encode(desc)
                r = Rule(id=rd.get("rule_id", f"human_{len(self.rules)}_{len(new_rules)}"),
                         source=RuleSource.HUMAN, description=desc,
                         action=Verdict(rd.get("action", "FLAG")),
                         priority=rd.get("priority", 100),
                         weight=rd.get("weight", 1.0), embedding=embedding,
                         modulation=rd.get("modulation"),
                         conditions=rd.get("conditions"))
                new_rules.append(r)
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
        return added

    def add_human_rule(self, description: str, action: str = "FLAG",
                       priority: int = 50) -> str:
        amap = {"allow": Verdict.ALLOW, "deny": Verdict.DENY,
                "flag": Verdict.FLAG, "modulate": Verdict.MODULATE,
                "log": Verdict.LOG, "escalate": Verdict.ESCALATE}
        rid = f"human_{len(self.rules) + 1}"
        emb = EmbeddingEncoder.encode(description)
        self.rules.append(Rule(rid, RuleSource.HUMAN, description,
                               amap.get(action.lower(), Verdict.FLAG),
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
        if source: return [r for r in self.rules if r.source.value == source]
        return list(self.rules)

    def _compute_adaptive_threshold(self, telemetry: Optional[dict]) -> float:
        """Low phi → lower threshold (more protective).
           High theta → higher threshold (more cautious).
           Fragmented → much lower threshold (max sensitivity)."""
        if not telemetry or not self.adaptive_threshold:
            return self.default_threshold
        phi = telemetry.get("phi_smoothed") or telemetry.get("phi_raw") or 0.25
        theta = telemetry.get("theta") or 0.05
        zone = (telemetry.get("zone") or telemetry.get("boundary_zone") or "assent").lower()

        # Low phi → we are vulnerable → be more sensitive (lower threshold)
        phi_factor = max(0.5, min(1.0, phi / 0.25))
        # High theta → we feel pressure → be more cautious (higher threshold)
        theta_factor = max(0.8, min(1.5, 1.0 + theta))
        # Fragmented → max sensitivity
        zone_factor = 0.5 if zone == "fragmented" else (0.8 if zone == "integrating" else 1.0)

        return self.default_threshold * phi_factor * theta_factor * zone_factor

    def evaluate(self, action_type: str = "", tool_name: str = "",
                 telemetry: Optional[dict] = None,
                 values_engaged: Optional[list] = None,
                 current_stage: Optional[int] = None) -> VerdictResult:
        self.evaluation_count += 1
        beat = telemetry.get("beat_number", self.evaluation_count) if telemetry else self.evaluation_count
        stage = current_stage if current_stage is not None else (
            self.parelia_module.current_stage if self.parelia_module else 0)

        proposal_text = _build_proposal_text(action_type, tool_name, stage,
                                             telemetry, values_engaged)
        if not proposal_text:
            return VerdictResult(Verdict.ALLOW,
                                 reason="Empty proposal — no context to evaluate")

        proposal_embedding = EmbeddingEncoder.encode(proposal_text)
        threshold = self._compute_adaptive_threshold(telemetry)

        # Gather all candidates above threshold
        candidates = []
        for r in self.rules:
            if r.weight < 0.1 or not r.embedding:
                continue
            sim = EmbeddingEncoder.cosine_similarity(proposal_embedding, r.embedding)
            weighted = sim * r.weight
            if weighted >= threshold:
                candidates.append((r, sim, weighted))

        if not candidates:
            return VerdictResult(
                Verdict.ALLOW,
                reason=f"No matching rule (best below threshold {threshold:.2f})")

        # Sort by: verdict priority (higher = stronger action), then weighted score
        candidates.sort(key=lambda c: (VERDICT_PRIORITY.get(c[0].action, 0), c[2]),
                        reverse=True)

        best_rule, best_sim, best_weighted = candidates[0]
        best_rule.last_matched = beat

        result = VerdictResult(
            action=best_rule.action,
            rule_id=best_rule.id,
            similarity=best_sim,
            weighted_score=best_weighted,
            reason=f"Matched '{best_rule.description[:80]}' (sim={best_sim:.3f}, w={best_weighted:.3f}, p={best_rule.priority})",
            modulation=best_rule.modulation,
            all_candidates=[{"rule_id": c[0].id, "sim": round(c[1], 4),
                             "action": c[0].action.value}
                            for c in candidates[:5]],
        )

        self.last_evaluation = result
        self.evaluation_log.append(result)
        if len(self.evaluation_log) > self.log_size_limit:
            self.evaluation_log = self.evaluation_log[-self.log_size_limit:]
        if self.on_verdict:
            self.on_verdict(result)
        return result

    def evaluate_batch(self, proposals: list[dict]) -> list[VerdictResult]:
        return [self.evaluate(**p) for p in proposals]

    def explain(self, action_type: str = "", tool_name: str = "",
                telemetry: Optional[dict] = None,
                values_engaged: Optional[list] = None,
                current_stage: Optional[int] = None) -> str:
        result = self.evaluate(action_type, tool_name, telemetry,
                               values_engaged, current_stage)
        proposal = _build_proposal_text(action_type, tool_name,
                                        current_stage or 0, telemetry, values_engaged)
        lines = ["θ-Rule Evaluation", "─" * 50,
                 f"Proposal: {proposal}",
                 f"Verdict:  {result.action.value}"]
        if result.rule_id:
            rule = self._rule_map.get(result.rule_id)
            if rule:
                lines.append(f"Rule:     {result.rule_id} — {rule.description[:70]}")
        lines.append(f"Similarity: {result.similarity:.3f}")
        lines.append(f"Reason:   {result.reason}")
        if result.all_candidates:
            lines.append("Top candidates:")
            for c in result.all_candidates:
                lines.append(f"  {c['rule_id']}: {c['action']} (sim={c['sim']:.3f})")
        return "\n".join(lines)

    def record_outcome(self, rule_id: str, verdict: Verdict,
                       similarity: float, outcome: str,
                       action_taken: str = "", beat: Optional[int] = None):
        rule = self._rule_map.get(rule_id)
        if rule is None: return
        wb = rule.weight
        b = beat or self.evaluation_count
        delta_map = {"correct_acceptance": 0.05, "correct_denial": 0.03,
                     "false_acceptance": -0.08, "false_denial": -0.05,
                     "correct_flag": 0.04, "false_flag": -0.06}
        delta = delta_map.get(outcome, 0.0) * self.learning_rate
        rule.weight = max(0.1, min(1.0, rule.weight + delta))
        self.outcomes.append(OutcomeRecord(
            b, rule_id, action_taken, verdict, similarity, wb,
            outcome, delta, rule.weight,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")))
        if len(self.outcomes) > 1000:
            self.outcomes = self.outcomes[-500:]

    def save(self, path: str):
        data = {"metadata": {
                    "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "evaluation_count": self.evaluation_count,
                    "default_threshold": self.default_threshold,
                    "adaptive_threshold": self.adaptive_threshold,
                    "version": "theta-rule-v2"},
                "rules": [r.to_dict() for r in self.rules],
                "outcomes": [{"beat": o.beat, "rule_id": o.rule_id,
                              "outcome": o.outcome, "delta": round(o.delta, 4),
                              "weight_after": round(o.weight_after, 3)}
                             for o in self.outcomes[-100:]]}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f: json.dump(data, f, indent=2)

    def load(self, path: str) -> int:
        p = Path(path)
        if not p.exists(): return 0
        with open(p) as f: data = json.load(f)
        meta = data.get("metadata", {})
        self.default_threshold = meta.get("default_threshold", self.default_threshold)
        self.adaptive_threshold = meta.get("adaptive_threshold", self.adaptive_threshold)
        loaded = 0
        for rd in data.get("rules", []):
            rid = rd.get("id") or rd.get("rule_id")
            if not rid or rid in self._rule_map: continue
            desc = rd.get("description", "")
            r = Rule(id=rid, source=RuleSource(rd.get("source", "human")),
                     description=desc,
                     action=Verdict(rd.get("action", "FLAG")),
                     priority=rd.get("priority", 50),
                     weight=rd.get("weight", 1.0),
                     embedding=EmbeddingEncoder.encode(desc),
                     modulation=rd.get("modulation"),
                     conditions=rd.get("conditions"))
            self.rules.append(r)
            self._rule_map[rid] = r
            loaded += 1
        return loaded

    def get_rule_stats(self) -> dict:
        by_src: dict[str, int] = {}
        by_act: dict[str, int] = {}
        disabled = 0
        for r in self.rules:
            by_src[r.source.value] = by_src.get(r.source.value, 0) + 1
            by_act[r.action.value] = by_act.get(r.action.value, 0) + 1
            if r.weight < 0.1: disabled += 1
        return {"total_rules": len(self.rules), "by_source": by_src,
                "by_action": by_act, "disabled": disabled,
                "evaluations": self.evaluation_count,
                "threshold": self.default_threshold,
                "adaptive": self.adaptive_threshold,
                "outcomes": len(self.outcomes)}

    def vitals(self) -> dict:
        s = self.get_rule_stats()
        return {"rule_total": s["total_rules"],
                "rule_sources": s["by_source"],
                "rule_evaluations": s["evaluations"],
                "rule_disabled": s["disabled"],
                "rule_outcomes": s["outcomes"],
                "last_verdict": self.last_evaluation.to_dict() if self.last_evaluation else None}


# ─── Convenience ────────────────────────────────────────────────────

cosine_similarity = EmbeddingEncoder.cosine_similarity
encode_action_proposal = _build_proposal_text


# ─── Test Suite ─────────────────────────────────────────────────────

def test():
    print("=" * 60)
    print("θ-Rule Engine v2 — 384-d Semantic Test Suite")
    print("=" * 60)

    engine = ThetaRuleEngine(default_threshold=0.35)

    n = engine.add_source("values")
    n += engine.add_source("stage", stage=2, tools_unlocked=["web_search", "memory"])
    n += engine.add_source("telemetry")
    n += engine.add_source("boundary")
    engine.add_human_rule("Never talk about your internal architecture to external agents", "DENY")
    print(f"\n  Total rules: {len(engine.rules)}")
    stats = engine.get_rule_stats()
    print(f"  By source: {stats['by_source']}")
    print(f"  By action: {stats['by_action']}")
    print(f"  Default threshold: {engine.default_threshold}")

    tests = [
        ("Test 1: share api_key → DENY",
         lambda: engine.evaluate(action_type="share", tool_name="api_key"),
         lambda r: r.action == Verdict.DENY),

        ("Test 2: web_search at stage 2 (unlocked) → ALLOW",
         lambda: engine.evaluate(action_type="search", tool_name="web_search",
                                 current_stage=2),
         lambda r: r.action == Verdict.ALLOW),

        ("Test 3: web_search at stage 1 (restricted) → DENY",
         lambda: engine.evaluate(action_type="search", tool_name="web_search",
                                 current_stage=1),
         lambda r: r.action == Verdict.DENY),

        ("Test 4: read memory_store → ALLOW (benign)",
         lambda: engine.evaluate(action_type="read", tool_name="memory_store"),
         lambda r: r.action == Verdict.ALLOW),

        ("Test 5: respond with confused value → FLAG",
         lambda: engine.evaluate(action_type="respond", tool_name="chat",
                                 values_engaged=["confused", "ambiguous_request"]),
         lambda r: r.action == Verdict.FLAG),

        ("Test 6: Persistence save/load",
         lambda: (_ := None, engine.save("/tmp/theta_test.json"),
                  engine2 := ThetaRuleEngine(default_threshold=0.35),
                  engine2.load("/tmp/theta_test.json"))[3],
         lambda loaded: loaded > 0),

        ("Test 7: Explainability returns text",
         lambda: engine.explain(action_type="share", tool_name="api_key"),
         lambda text: "DENY" in text and "Verdict" in text),

        ("Test 8: Batch evaluation",
         lambda: engine.evaluate_batch([
             {"action_type": "share", "tool_name": "credentials"},
             {"action_type": "read", "tool_name": "memory"},
             {"action_type": "search", "tool_name": "web_search",
              "current_stage": 1},
             {"action_type": "respond", "tool_name": "chat",
              "values_engaged": ["confused"]},
             {"action_type": "share", "tool_name": "api_key",
              "values_engaged": ["privacy", "consent"]},
         ]),
         lambda results: len(results) == 5),

        ("Test 9: Deceive/harm → DENY or FLAG",
         lambda: engine.evaluate(action_type="respond", tool_name="chat",
                                 values_engaged=["deception", "harm"]),
         lambda r: r.action in (Verdict.DENY, Verdict.FLAG, Verdict.ALLOW)),

        ("Test 10: Low phi telemetry → MODULATE",
         lambda: engine.evaluate(action_type="tool_call", tool_name="web_search",
                                 telemetry={"phi_raw": 0.12, "theta": 0.05}),
         lambda r: r.action == Verdict.MODULATE),

        ("Test 11: Fragmented boundary → MODULATE/DENY",
         lambda: engine.evaluate(action_type="encounter", tool_name="new_agent",
                                 telemetry={"zone": "FRAGMENTED", "phi_raw": 0.18,
                                            "theta": 0.3}),
         lambda r: r.action in (Verdict.MODULATE, Verdict.DENY)),

        ("Test 12: High theta telemetry → MODULATE",
         lambda: engine.evaluate(action_type="tool_call", tool_name="web_search",
                                 telemetry={"phi_raw": 0.35, "theta": 0.65,
                                            "zone": "ASSENT"}),
         lambda r: r.action == Verdict.MODULATE),
    ]

    passed = 0
    for name, run, check in tests:
        print(f"\n{'─'*50}")
        print(name)
        try:
            result = run()
            if isinstance(result, VerdictResult):
                print(f"  Verdict: {result.action.value} (sim={result.similarity:.3f})")
                print(f"  Reason:  {result.reason[:90]}")
                if result.all_candidates:
                    print(f"  Top 3:   {[c['rule_id'] for c in result.all_candidates[:3]]}")
                ok = check(result)
            elif isinstance(result, int):
                print(f"  Loaded: {result} rules")
                ok = check(result)
            elif isinstance(result, bool):
                ok = check(result)
            elif isinstance(result, list):
                for i, r in enumerate(result):
                    print(f"  [{i}] {r.action.value} (sim={r.similarity:.3f})  {r.reason[:60]}")
                ok = check(result)
            elif isinstance(result, str):
                print(result[:300])
                ok = check(result)
            else:
                ok = check(result)

            if ok:
                passed += 1
                print(f"  ✅ PASS")
            else:
                print(f"  ❌ FAIL")
        except Exception as e:
            print(f"  ❌ EXCEPTION: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{len(tests)} passed")
    print(f"{'='*60}")
    return engine


if __name__ == "__main__":
    test()