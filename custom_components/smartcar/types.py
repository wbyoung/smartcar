"""Smartcar dataclasses and typing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from .auth import AbstractAuth
    from .coordinator import SmartcarVehicleCoordinator


type APIVersion = Literal["v2", "v3"]


@dataclass(frozen=True, kw_only=True)
class SmartcarData:
    """The Smartcar coordinator runtime data."""

    auth: AbstractAuth
    coordinators: dict[str, SmartcarVehicleCoordinator]
    meta_coordinator: DataUpdateCoordinator


@dataclass
class SmartcarAPIError(Exception):
    """Error representing an issue via the Smartcar API."""

    code: int
    reason: str
