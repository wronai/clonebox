from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class NetworkPolicy(BaseModel):
    allowlist: List[str] = Field(default_factory=list)
    blocklist: List[str] = Field(default_factory=list)

    @field_validator("allowlist", "blocklist")
    @classmethod
    def _validate_patterns(cls, v: List[str]) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("must be a list")
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("patterns must be non-empty strings")
        return v


class OperationsPolicy(BaseModel):
    require_approval: List[str] = Field(default_factory=list)
    auto_approve: List[str] = Field(default_factory=list)

    @field_validator("require_approval", "auto_approve")
    @classmethod
    def _validate_ops(cls, v: List[str]) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("must be a list")
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("operation names must be non-empty strings")
        return v


class ResourcesPolicy(BaseModel):
    max_vms_per_user: Optional[int] = None
    max_disk_gb: Optional[int] = None


class PolicySet(BaseModel):
    network: Optional[NetworkPolicy] = None
    operations: Optional[OperationsPolicy] = None
    resources: Optional[ResourcesPolicy] = None


class PolicyFile(BaseModel):
    version: str
    policies: PolicySet
