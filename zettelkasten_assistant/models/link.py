from dataclasses import dataclass
from datetime import datetime


@dataclass
class Link:
    source_id: str
    target_id: str
    type: str
    inverse_type: str
    description: str = ""
    created_at: datetime = datetime.utcnow()
