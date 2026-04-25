from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Folder:
    id: Optional[int] = None
    path: str = ""
    parent_id: Optional[int] = None
    type: str = ""
    name: str = ""
    status: str = ""
    priority: str = ""
    tags: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    body: str = ""
    created: str = ""
    updated: str = ""
    closed: str = ""


@dataclass
class Activity:
    id: Optional[int] = None
    folder_id: Optional[int] = None
    action: str = ""
    from_value: str = ""
    to_value: str = ""
    actor: str = "manual"
    at: str = ""
    note: str = ""
