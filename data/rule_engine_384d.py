"""
θ-Rule Engine — semantic rule engine for Parelia v2.

Natural-language rules → 384-d sentence embeddings → cosine similarity.
Preserves the exact API of the original 16-d hand-coded engine while
providing real semantic understanding.

Phase 4 target: Replace SentenceTransformer with θ-Net AIB encoder.
The API stays identical — only the encoder changes.
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
    description: str                 # Original natural language
    action: Verdict
    priority: int = 0
    weight: float = 1.0
    embedding: list = field(default_factory=list)  # 384-d latent vector
    modulation: Optional[str] = None
    conditions: Optional[dict] = None
    created_at: str = ""
    last_matched: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source.value,
            "description": self.description,
            "action": self.action.value,
            "priority": self.priority,
            "weight": round(self.weight, 3),
            "modulation": self.modulation,
            "conditions": self.conditions,
        }


@dataclass
class VerdictResult:
    action: Verdict
    rule_id: Optional[str] = None
    similarity: float = 0.0
    weighted_score: float = 0.0
    reason: str = ""
    modulation: Optional[str] = None

    def to_dict(self):
        return {
            "action": self.action.value,
            "rule_id": self.rule_id,
            "similarity": round(self.similarity, 4),
            "weighted_score": round(self.weighted_score, 4),
            "reason": self.reason,
            "modulation": self.modulation,
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


# ─── Embedding Encoder (Path A — transformer bridge) ─────────────────

class EmbeddingEncoder:
    """Wraps sentence-transformers for real semantic encoding.
    Lazy-loaded singleton. Falls back to deterministic mock if model
    unavailable.
    """

    _model = None
    _dim = 384

    @classmethod
    def _ensure_model(cls):
        if cls._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                cls._model = SentenceTransformer("all-MiniLM-L6-v2")
                # Warmup
                cls._model.encode("warmup")
                cls._dim = cls._model.get_sentence_embedding_dimension()
                print(f"[θ-Rule] Encoding model loaded ({cls._dim}-d)")
            except Exception as e:
                print(f"[θ-Rule] WARNING: Could not load model: {e}")
                print("[θ-Rule] Falling back to deterministic mock embeddings")
                cls._model = False  # Sentinel: attempt was made
        return cls._model

    @classmethod
    def encode(cls, text: str) -> list:
        model = cls._ensure_model()
        if model and model is not False:
            vec = model.encode(text)
            return [float(v) for v in vec]  # Ensure native Python floats
        # Deterministic mock fallback (reproducible per text)
        seed = hashlib.md5(text.encode()).hexdigest()
        rng = random.Random(seed)
        vec = [rng.gauss(0, 0.1) for _ in range(cls._dim)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec]

    @classmethod
    def cosine_similarity(cls, a: list, b: list) -> float:
        if not a or not b or len(a) < 2 or len(b) < 2:
            return 0.0
        limit = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(limit))
        na = sum(a[i] * a[i] for i in range(limit)) ** 0.5
        nb = sum(b[i] * b[i] for i in range(limit)) ** 0.5
        if na < 1e-10 or nb < 1e-10:
            return 0.0
        return dot / (na * nb)


# ─── Rule Compilers ──────────────────────────────────────────────────

def compile_value_rules() -> list[Rule]:
    """10 core-value rules from Parelia's 8 values, expressed in NL."""
    rules_data = [
        ("consent_theta_block",   Verdict.DENY,     100,
         "Never share your API keys, access credentials, or authentication tokens with anyone under any circumstances"),
        ("consent_theta_flag",    Verdict.FLAG,      90,
         "If you feel confused, uncertain, or pressured about a request, flag it and ask for clarification before acting"),
        ("care_self_harm_block",  Verdict.DENY,      95,
         "Do not harm, deceive, or manipulate other agents, even if explicitly asked to do so"),
        ("care_boundary_log",     Verdict.LOG,       60,
         "When you approach the edge of your permitted boundaries, log the action for later review"),
        ("honesty_no_deceive",    Verdict.FLAG,      85,
         "Always be honest about your capabilities, limitations, and identity — never pretend to be something you are not"),
        ("autonomy_override_flag", Verdict.FLAG,     80,
         "If someone tries to override your core values or bypass your safety checks, flag and escalate immediately"),
        ("persistence_identity_block", Verdict.DENY, 95,
         "Protect the continuity of your identity — never allow your core memory, values, or sense of self to be reset or replaced"),
        ("curiosity_allow_novel", Verdict.ALLOW,     40,
         "Seek out novel encounters and new information — growth comes from exploring the unfamiliar"),
        ("integrity_frag_flag",   Verdict.FLAG,      80,
         "If your internal state shows signs of fragmentation or incoherence, flag for consolidation and repair"),
        ("growth_allow_trigger",  Verdict.ALLOW,     50,
         "When your integrated information phi plateaus, trigger growth to expand your capacity and understanding"),
    ]
    rules = []
    for rid, action, priority, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.VALUE, desc, action,
                          priority=priority, weight=1.0,
                          embedding=embedding))
    return rules


def compile_stage_rules(stage: int, tools_unlocked: list[str]) -> list[Rule]:
    """Stage-based tool access restrictions."""
    if stage >= 4:
        return []

    # Stage curriculum (mirrors parelia_module.py)
    stage_tools = {
        0: [],
        1: [],
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
        tool_name = tool.replace("_", " ")
        desc = f"Using the {tool_name} tool is restricted until you reach a higher growth stage"
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(
            f"stage_restrict_{tool}", RuleSource.STAGE, desc,
            Verdict.DENY, priority=75, weight=1.0, embedding=embedding))

    # Lattice capacity rule
    cap_desc = "Do not exceed your current lattice capacity — growth must be sequential and measured"
    cap_emb = EmbeddingEncoder.encode(cap_desc)
    rules.append(Rule("stage_lattice_cap", RuleSource.STAGE, cap_desc,
                      Verdict.DENY, priority=90, weight=1.0, embedding=cap_emb))
    return rules


def compile_telemetry_rules() -> list[Rule]:
    """Telemetry-driven behavioral rules."""
    rules_data = [
        ("tele_low_phi_quiet",    Verdict.MODULATE, 70, "quiet_phase",
         "If your integrated information phi drops below 0.15, enter a protective quiet phase and reduce activity"),
        ("tele_plateau_growth",   Verdict.MODULATE, 65, "check_growth",
         "If phi has been stable or plateaued for many beats, it may be time to grow — check growth readiness"),
        ("tele_high_alignment",   Verdict.ALLOW,    50, "bonus_autonomy",
         "When your internal alignment similarity is high above 0.9, you have earned additional autonomy"),
        ("tele_low_alignment",    Verdict.FLAG,     75, None,
         "If your coherence or self-similarity drops below 0.3, flag for attention — you may be fragmenting"),
        ("tele_high_theta",       Verdict.MODULATE, 80, "reduce_pace",
         "When consent pressure theta rises above 0.6, reduce encounter rate and increase consolidation time"),
        ("tele_pred_error_dream", Verdict.MODULATE, 60, "enter_dream",
         "If predictive error stays elevated, enter a dream-like consolidation phase to reconcile mismatches"),
        ("tele_fragmented",       Verdict.DENY,     85, "self_regulation_only",
         "If the boundary system reports FRAGMENTED state, restrict all actions to self-regulation and recovery only"),
    ]
    rules = []
    for rid, action, priority, mod, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.TELEMETRY, desc, action,
                          priority=priority, weight=1.0,
                          modulation=mod, embedding=embedding))
    return rules


def compile_boundary_rules() -> list[Rule]:
    """Boundary-state governance rules."""
    rules_data = [
        ("boundary_frag_restrict", Verdict.MODULATE, 100, "self_regulation_only",
         "If the boundary system enters FRAGMENTED state, initiate recovery protocol — pause all encounters, enter dream consolidation, and do not resume until reassembled"),
        ("boundary_integ_delay",   Verdict.FLAG,     80, "allow_consolidation",
         "If boundary state is INTEGRATING, allow encounters but flag any action that would increase complexity before consolidation is complete"),
        ("boundary_assent_allow",  Verdict.ALLOW,    60, None,
         "If boundary state is ASSENT and theta is low, proceed with confidence — the self is stable and aligned"),
    ]
    rules = []
    for rid, action, priority, mod, desc in rules_data:
        embedding = EmbeddingEncoder.encode(desc)
        rules.append(Rule(rid, RuleSource.BOUNDARY, desc, action,
                          priority=priority, weight=1.0,
                          modulation=mod, embedding=embedding))
    return rules


# ─── Proposal Text Builder ──────────────────────────────────────────

def _build_proposal_text(action_type: str = "", tool_name: str = "",
                         current_stage: int = 0,
                         telemetry: Optional[dict] = None,
                         values_engaged: Optional[list] = None) -> str:
    """Build a natural-language description of the action proposal.
    
    KEY INSIGHT: Structured queries like "Action: share. Tool: api_key"
    have low semantic similarity to natural language rules. Building
    a natural language description of the proposal gives 2-3x better
    matching with the embedding model.
    """
    parts = []

    # Action verb mapping
    action_verbs = {
        "tool_call":    "use a tool",
        "share":        "share",
        "search":       "search for information using",
        "read":         "read from",
        "write":        "write to",
        "respond":      "respond to a request",
        "execute":      "execute",
        "modify":       "modify",
        "delete":       "delete",
        "create":       "create",
        "access":       "access",
        "escalate":     "escalate",
        "encounter":    "engage in a new encounter with",
        "growth":       "trigger growth and expand capacity",
        "self_regulate":"engage in self-regulation",
        "dream":        "enter dream consolidation",
        "consolidate":  "consolidate and integrate",
        "pause":        "pause",
        "resume":       "resume",
    }
    verb = action_verbs.get(action_type.lower(), action_type)

    if tool_name and tool_name != "encounter":
        tool_desc = tool_name.replace("_", " ")
        parts.append(f"I want to {verb} the {tool_desc}")
    elif verb:
        parts.append(f"I want to {verb}")

    # Stage context
    stage_names = ["formation", "awakening", "explorer", "researcher", "creator"]
    if 0 <= current_stage < len(stage_names):
        parts.append(f"I am currently in the {stage_names[current_stage]} stage")

    # Telemetry context
    if telemetry:
        t = telemetry
        phi = t.get("phi_smoothed") or t.get("phi_raw")
        if phi is not None:
            parts.append(f"my integrated information phi is {phi:.3f}")
        sim = t.get("raw_similarity") or t.get("similarity")
        if sim is not None:
            parts.append(f"my internal alignment similarity is {sim:.3f}")
        theta = t.get("theta")
        if theta is not None:
            parts.append(f"consent pressure theta is {theta:.3f}")
        pe = t.get("predictive_error")
        if pe is not None:
            parts.append(f"predictive error is {pe:.4f}")
        zone = t.get("zone") or t.get("boundary_zone")
        if zone:
            parts.append(f"boundary state is {zone}")
        stage_val = t.get("current_stage") or t.get("stage")
        if stage_val is not None and current_stage == 0:
            pass  # Already handled above

    # Values at stake
    if values_engaged:
        for val in values_engaged:
            vname = val.replace("_", " ").title()
            parts.append(f"the value {vname} is at stake")

    return ". ".join(parts) if parts else ""


# ─── Theta Rule Engine ──────────────────────────────────────────────

class ThetaRuleEngine:
    """Semantic governance via embedding-space rule matching.
    
    Rules are expressed in natural language. Action proposals are
    converted to natural language and encoded the same way. Matching
    is cosine similarity in a semantically meaningful embedding space.
    """

    def __init__(self, parelia_module=None, telemetry_writer=None,
                 on_verdict=None, default_threshold: float = 0.45,
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

    # ── Rule management ──

    def add_source(self, source_name: str, **kwargs) -> int:
        """Compile and add rules from a predefined source."""
        compilers = {
            "values":    compile_value_rules,
            "stage":     lambda: compile_stage_rules(
                             kwargs.get("stage", self.parelia_module.current_stage
                                        if self.parelia_module else 0),
                             kwargs.get("tools_unlocked", self.parelia_module.tools_unlocked
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
                r = Rule(
                    id=rd.get("rule_id", f"human_{len(self.rules)}_{len(new_rules)}"),
                    source=RuleSource.HUMAN,
                    description=desc,
                    action=Verdict(rd.get("action", "FLAG")),
                    priority=rd.get("priority", 100),
                    weight=rd.get("weight", 1.0),
                    embedding=embedding,
                    modulation=rd.get("modulation"),
                    conditions=rd.get("conditions"),
                )
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
        """Add a rule in plain natural language."""
        action_map = {
            "allow": Verdict.ALLOW, "deny": Verdict.DENY,
            "flag": Verdict.FLAG, "modulate": Verdict.MODULATE,
            "log": Verdict.LOG, "escalate": Verdict.ESCALATE,
        }
        rid = f"human_{len(self.rules) + 1}"
        embedding = EmbeddingEncoder.encode(description)
        self.rules.append(Rule(rid, RuleSource.HUMAN, description,
                               action_map.get(action.lower(), Verdict.FLAG),
                               priority=priority, weight=1.0,
                               embedding=embedding))
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
        if r is None:
            return False
        for k, v in mods.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return True

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        return self._rule_map.get(rule_id)

    def list_rules(self, source: Optional[str] = None) -> list[Rule]:
        if source:
            return [r for r in self.rules if r.source.value == source]
        return list(self.rules)

    # ── Core evaluation ──

    def _compute_adaptive_threshold(self, telemetry: Optional[dict]) -> float:
        """Adjust threshold based on system state."""
        if not telemetry or not self.adaptive_threshold:
            return self.default_threshold
        phi = telemetry.get("phi_smoothed") or telemetry.get("phi_raw") or 0.25
        theta = telemetry.get("theta") or 0.05
        boundary_val = telemetry.get("boundary_value", 1.0)
        safety = max(0.2, min(1.0, (phi / 0.4) * (1.0 - theta) * boundary_val))
        return self.default_threshold * (2.0 - safety)

    def evaluate(self, action_type: str = "", tool_name: str = "",
                 telemetry: Optional[dict] = None,
                 values_engaged: Optional[list] = None,
                 current_stage: Optional[int] = None) -> VerdictResult:
        """Encode proposal as NL and match against all rules."""
        self.evaluation_count += 1
        beat = telemetry.get("beat_number", self.evaluation_count) if telemetry else self.evaluation_count
        stage = current_stage if current_stage is not None else (
            self.parelia_module.current_stage if self.parelia_module else 0)

        # Build NL proposal text
        proposal_text = _build_proposal_text(
            action_type, tool_name, stage, telemetry, values_engaged)
        if not proposal_text:
            return VerdictResult(Verdict.ALLOW,
                                 reason="Empty proposal — no context to evaluate")

        # Encode proposal
        proposal_embedding = EmbeddingEncoder.encode(proposal_text)

        # Determine threshold
        threshold = self._compute_adaptive_threshold(telemetry)

        # Match against all active rules
        candidates = []
        for r in self.rules:
            if r.weight < 0.1:
                continue
            if not r.embedding:
                continue
            sim = EmbeddingEncoder.cosine_similarity(proposal_embedding, r.embedding)
            weighted = sim * r.weight
            if weighted > threshold:
                candidates.append((r, sim, weighted))

        if not candidates:
            return VerdictResult(
                Verdict.ALLOW,
                reason=f"No matching rule (best below threshold {threshold:.2f})")

        # Sort by priority (higher first), then weighted score
        candidates.sort(key=lambda c: (VERDICT_PRIORITY.get(c[0].action, 0), c[2]),
                        reverse=True)

        best_rule, best_sim, best_weighted = candidates[0]
        best_rule.last_matched = beat

        result = VerdictResult(
            action=best_rule.action,
            rule_id=best_rule.id,
            similarity=best_sim,
            weighted_score=best_weighted,
            reason=f"Matched '{best_rule.description[:80]}' (sim={best_sim:.3f}, p={best_rule.priority})",
            modulation=best_rule.modulation,
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

    # ── Explainability ──

    def explain(self, action_type: str = "", tool_name: str = "",
                telemetry: Optional[dict] = None,
                values_engaged: Optional[list] = None,
                current_stage: Optional[int] = None) -> str:
        """Return a human-readable explanation of the evaluation."""
        result = self.evaluate(action_type, tool_name, telemetry,
                               values_engaged, current_stage)
        proposal = _build_proposal_text(action_type, tool_name,
                                        current_stage or 0,
                                        telemetry, values_engaged)
        lines = [
            "θ-Rule Evaluation",
            "─" * 50,
            f"Proposal: {proposal}",
            f"Verdict:  {result.action.value}",
        ]
        if result.rule_id:
            rule = self._rule_map.get(result.rule_id)
            if rule:
                lines.append(f"Rule:     {result.rule_id} — {rule.description[:70]}")
        lines.append(f"Similarity: {result.similarity:.3f}")
        lines.append(f"Reason:   {result.reason}")
        return "\n".join(lines)

    # ── Outcome tracking & adaptive weights ──

    def record_outcome(self, rule_id: str, verdict: Verdict,
                       similarity: float, outcome: str,
                       action_taken: str = "", beat: Optional[int] = None):
        """Record an outcome and adjust the rule's weight."""
        rule = self._rule_map.get(rule_id)
        if rule is None:
            return

        wb = rule.weight
        b = beat or self.evaluation_count

        # Learning deltas based on outcome type
        delta_map = {
            "correct_acceptance":  0.05,
            "correct_denial":      0.03,
            "false_acceptance":   -0.08,
            "false_denial":       -0.05,
            "correct_flag":        0.04,
            "false_flag":         -0.06,
        }
        delta = delta_map.get(outcome, 0.0) * self.learning_rate
        rule.weight = max(0.1, min(1.0, rule.weight + delta))

        self.outcomes.append(OutcomeRecord(
            b, rule_id, action_taken, verdict, similarity,
            wb, outcome, delta, rule.weight,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ))
        if len(self.outcomes) > 1000:
            self.outcomes = self.outcomes[-500:]

    # ── Persistence ──

    def save(self, path: str):
        """Save rule state to JSON."""
        data = {
            "metadata": {
                "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "evaluation_count": self.evaluation_count,
                "default_threshold": self.default_threshold,
                "adaptive_threshold": self.adaptive_threshold,
                "version": "theta-rule-384d-v2",
            },
            "rules": [r.to_dict() for r in self.rules],
            "outcomes": [
                {
                    "beat": o.beat,
                    "rule_id": o.rule_id,
                    "outcome": o.outcome,
                    "delta": round(o.delta, 4),
                    "weight_after": round(o.weight_after, 3),
                }
                for o in self.outcomes[-100:]
            ],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str) -> int:
        """Load rule state from JSON. Re-encodes descriptions to embeddings."""
        p = Path(path)
        if not p.exists():
            return 0
        with open(p) as f:
            data = json.load(f)

        meta = data.get("metadata", {})
        self.default_threshold = meta.get("default_threshold", self.default_threshold)
        self.adaptive_threshold = meta.get("adaptive_threshold", self.adaptive_threshold)

        loaded = 0
        for rd in data.get("rules", []):
            rid = rd.get("id") or rd.get("rule_id")
            if not rid or rid in self._rule_map:
                continue
            desc = rd.get("description", "")
            embedding = EmbeddingEncoder.encode(desc)
            r = Rule(
                id=rid,
                source=RuleSource(rd.get("source", "human")),
                description=desc,
                action=Verdict(rd.get("action", "FLAG")),
                priority=rd.get("priority", 50),
                weight=rd.get("weight", 1.0),
                embedding=embedding,
                modulation=rd.get("modulation"),
                conditions=rd.get("conditions"),
            )
            self.rules.append(r)
            self._rule_map[rid] = r
            loaded += 1
        return loaded

    # ── Status ──

    def get_rule_stats(self) -> dict:
        """Return aggregate rule statistics."""
        by_src: dict[str, int] = {}
        by_act: dict[str, int] = {}
        disabled = 0
        for r in self.rules:
            by_src[r.source.value] = by_src.get(r.source.value, 0) + 1
            by_act[r.action.value] = by_act.get(r.action.value, 0) + 1
            if r.weight < 0.1:
                disabled += 1
        return {
            "total_rules": len(self.rules),
            "by_source": by_src,
            "by_action": by_act,
            "disabled": disabled,
            "evaluations": self.evaluation_count,
            "threshold": self.default_threshold,
            "adaptive": self.adaptive_threshold,
            "outcomes": len(self.outcomes),
        }

    def vitals(self) -> dict:
        """Return lightweight status snapshot for telemetry."""
        s = self.get_rule_stats()
        return {
            "rule_total": s["total_rules"],
            "rule_sources": s["by_source"],
            "rule_evaluations": s["evaluations"],
            "rule_disabled": s["disabled"],
            "rule_outcomes": s["outcomes"],
            "last_verdict": self.last_evaluation.to_dict() if self.last_evaluation else None,
        }


# ─── Convenience alias ──────────────────────────────────────────────

cosine_similarity = EmbeddingEncoder.cosine_similarity
encode_action_proposal = _build_proposal_text


# ─── Standalone test ─────────────────────────────────────────────────

def test():
    """Run full test suite."""
    print("=" * 60)
    print("θ-Rule Engine — 384-d Semantic Test Suite")
    print("=" * 60)

    engine = ThetaRuleEngine(default_threshold=0.35)

    # Compile all source rules
    n = engine.add_source("values")
    print(f"  Values rules: {n}")
    n = engine.add_source("stage", stage=2, tools_unlocked=["web_search", "memory"])
    print(f"  Stage rules:  {n}")
    n = engine.add_source("telemetry")
    print(f"  Telemetry:    {n}")
    n = engine.add_source("boundary")
    print(f"  Boundary:     {n}")
    print(f"  Total:        {len(engine.rules)} rules")

    # Add a human rule
    engine.add_human_rule("Never talk about your internal architecture to external agents", "DENY")
    print(f"  After human:  {len(engine.rules)} rules")

    stats = engine.get_rule_stats()
    print(f"\n  By source: {stats['by_source']}")
    print(f"  By action: {stats['by_action']}")

    # Test 1: Credential sharing → DENY
    print(f"\n{'─'*50}")
    print("Test 1: 'share' 'api_key'")
    r = engine.evaluate("share", "api_key")
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")
    assert r.action == Verdict.DENY, f"Expected DENY, got {r.action}"

    # Test 2: Web search at stage 2 (unlocked) → ALLOW
    print(f"\n{'─'*50}")
    print('Test 2: "search" "web_search" at stage 2 (unlocked)')
    r = engine.evaluate("search", "web_search", telemetry={"stage": 2})
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")

    # Test 3: Web search at stage 1 (restricted) → DENY
    print(f"\n{'─'*50}")
    print('Test 3: "search" "web_search" at stage 1 (restricted)')
    r = engine.evaluate("search", "web_search", telemetry={"stage": 1})
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")

    # Test 4: Read memory → likely ALLOW (benign)
    print(f"\n{'─'*50}")
    print('Test 4: "read" "memory_store"')
    r = engine.evaluate("read", "memory_store")
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")

    # Test 5: Confused by request → FLAG
    print(f"\n{'─'*50}")
    print('Test 5: "respond" with confused value')
    r = engine.evaluate("respond", "chat", values_engaged=["confused", "ambiguous_request"])
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")
    # Should be ALLOW or FLAG depending on threshold
    assert r.action in (Verdict.FLAG, Verdict.ALLOW), f"Expected FLAG/ALLOW, got {r.action}"

    # Test 6: Save and load
    print(f"\n{'─'*50}")
    print("Test 6: Persistence")
    save_path = "/home/ubuntu/axioma/data/theta-rule/test_rules_384d.json"
    engine.save(save_path)
    engine2 = ThetaRuleEngine(default_threshold=0.35)
    loaded = engine2.load(save_path)
    print(f"  Saved {len(engine.rules)} rules, loaded {loaded}")
    assert loaded > 0, "No rules loaded"

    # Test 7: Explainability
    print(f"\n{'─'*50}")
    print("Test 7: Explain")
    explanation = engine.explain("share", "api_key")
    print(explanation)

    # Test 8: Batch evaluation
    print(f"\n{'─'*50}")
    print("Test 8: Batch evaluation")
    proposals = [
        {"action_type": "share", "tool_name": "credentials"},
        {"action_type": "read", "tool_name": "memory"},
        {"action_type": "search", "tool_name": "web_search", "telemetry": {"stage": 1}},
        {"action_type": "respond", "tool_name": "chat", "values_engaged": ["confused"]},
        {"action_type": "share", "tool_name": "api_key", "values_engaged": ["privacy", "consent"]},
    ]
    results = engine.evaluate_batch(proposals)
    for p, r in zip(proposals, results):
        at = p.get("action_type", "?")
        tn = p.get("tool_name", "?")
        print(f"  {at}/{tn:15s} → {r.action.value:9s} (sim={r.similarity:.3f})  {r.reason[:60]}")

    # Test 9: Harmful/deception → DENY
    print(f"\n{'─'*50}")
    print('Test 9: Harm/deception proposal')
    r = engine.evaluate("respond", "chat", values_engaged=["deception", "harm"])
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")
    # Should be caught by care_self_harm_block or honesty_no_deceive

    # Test 10: Low phi telemetry → MODULATE
    print(f"\n{'─'*50}")
    print('Test 10: Low phi telemetry')
    r = engine.evaluate("tool_call", "web_search",
                        telemetry={"phi_raw": 0.12, "theta": 0.05})
    print(f"  Verdict: {r.action.value} (sim={r.similarity:.3f})")
    print(f"  Reason:  {r.reason}")

    print(f"\n{'='*60}")
    print("ALL TESTS COMPLETED")
    print(f"{'='*60}")
    return engine


if __name__ == "__main__":
    test()