"""axioma.config — pydantic config tree + YAML/env loader."""
from __future__ import annotations

from .loader import load_config
from .schema import (
    AxiomaConfig,
    CoherenceSchedulerConfig,
    ComposeConfig,
    GPUConfig,
    InfraConfig,
    InterfaceConfig,
    MeasurementConfig,
    MetaCognitionConfig,
    ObservabilityConfig,
    OllamaConfig,
    OrganSpec,
    PersistenceConfig,
    QdrantConfig,
    RecoveryConfig,
    RedisConfig,
    ReleaseConfig,
    RetentionConfig,
    RuntimeConfig,
    SubstrateConfig,
)

__all__ = [
    "AxiomaConfig",
    "CoherenceSchedulerConfig",
    "ComposeConfig",
    "GPUConfig",
    "InfraConfig",
    "InterfaceConfig",
    "MeasurementConfig",
    "MetaCognitionConfig",
    "ObservabilityConfig",
    "OllamaConfig",
    "OrganSpec",
    "PersistenceConfig",
    "QdrantConfig",
    "RecoveryConfig",
    "RedisConfig",
    "ReleaseConfig",
    "RetentionConfig",
    "RuntimeConfig",
    "SubstrateConfig",
    "load_config",
]
