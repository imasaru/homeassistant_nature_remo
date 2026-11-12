"""NatureRemoAPI uses the injected session."""

from custom_components.nature_remo.api import NatureRemoAPI


async def test_uses_injected_session() -> None:
    marker = object()
    api = NatureRemoAPI("tok", marker)  # type: ignore[arg-type]
    async with api._session() as session:
        assert session is marker
