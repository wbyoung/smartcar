"""Customizations for Syrupy."""

from typing import Any

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.syrupy import (
    HomeAssistantSnapshotExtension,
    HomeAssistantSnapshotSerializer,
)
from syrupy.extensions.amber import AmberDataSerializer
from syrupy.filters import props
from syrupy.types import (
    PropertyFilter,
    PropertyMatcher,
    PropertyName,
    PropertyPath,
    SerializableData,
)


class SmartcarSnapshotSerializer(HomeAssistantSnapshotSerializer):
    @classmethod
    def _serialize(
        cls,
        data: SerializableData,
        *,
        depth: int = 0,
        exclude: PropertyFilter | None = None,
        include: PropertyFilter | None = None,
        matcher: PropertyMatcher | None = None,
        path: PropertyPath = (),
        visited: set[Any] | None = None,
    ) -> str:
        serializable_data = data

        if isinstance(data, er.RegistryEntry):
            base_exclude = exclude
            exclude_props = props(
                # compat for HA DeviceRegistryEntrySnapshot <2025.9.0 and >=2026.2.0
                "object_id_base",
            )

            def combined_exclude(*, prop: PropertyName, path: PropertyPath) -> bool:
                if base_exclude and base_exclude(prop=prop, path=path):
                    return True
                return bool(exclude_props(prop=prop, path=path))

            exclude = combined_exclude

        serialized: str = super()._serialize(
            serializable_data,
            depth=depth,
            exclude=exclude,
            include=include,
            matcher=matcher,
            path=path,
            visited=visited,
        )

        return serialized


class SmartcarSnapshotExtension(HomeAssistantSnapshotExtension):
    serializer_class: type[AmberDataSerializer] = SmartcarSnapshotSerializer
