from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(slots=True)
class MetricRow:
    metric_date: date
    dimensions: dict[str, Any]
    metrics: dict[str, Any]
    raw_payload: dict[str, Any]


class MetricsConnector(ABC):
    source: str

    @abstractmethod
    def fetch(self, entity_key: str, start_date: date, end_date: date) -> list[MetricRow]:
        raise NotImplementedError
