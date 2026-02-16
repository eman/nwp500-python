"""Tests for OpenEI client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nwp500.openei import OpenEIClient

# Sample OpenEI API response items (realistic data from HAR captures)
SAMPLE_OPENEI_ITEMS = [
    {
        "approved": True,
        "utility": "Pacific Gas & Electric Co",
        "eiaid": 14328,
        "name": "E-1 -Residential Service Baseline Region Y",
        "label": "67575942fe4f0b50f5027994",
        "sector": "Residential",
        "description": "Residential service baseline",
        "energyratestructure": [[{"rate": 0.40206, "unit": "kWh"}]],
        "energyweekdayschedule": [[1] * 24] * 12,
    },
    {
        "approved": True,
        "utility": "Pacific Gas & Electric Co",
        "eiaid": 14328,
        "name": "Electric Vehicle EV (Sch) Rate A",
        "label": "67576350c51426c5b80fdae5",
        "sector": "Residential",
        "description": "EV charging rate",
        "energyratestructure": [
            [{"rate": 0.34761, "unit": "kWh"}],
            [{"rate": 0.46016, "unit": "kWh"}],
        ],
        "energyweekdayschedule": [
            [
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                2,
                2,
                2,
                2,
                2,
                2,
                2,
                1,
                1,
                0,
            ]
        ]
        * 12,
    },
    {
        "approved": True,
        "utility": "SoCal Edison",
        "eiaid": 99999,
        "name": "TOU-D Residential",
        "label": "abc123",
        "sector": "Residential",
        "description": "SoCal TOU",
    },
]


def _make_mock_response(items: list) -> MagicMock:
    """Create a mock aiohttp response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value={"items": items})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


@pytest.mark.asyncio
async def test_fetch_rates() -> None:
    """Test fetching raw rate plan data."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        items = await client.fetch_rates("94903")

    assert len(items) == 3
    assert items[0]["utility"] == "Pacific Gas & Electric Co"


@pytest.mark.asyncio
async def test_list_utilities() -> None:
    """Test listing unique utilities."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        utilities = await client.list_utilities("94903")

    assert utilities == [
        "Pacific Gas & Electric Co",
        "SoCal Edison",
    ]


@pytest.mark.asyncio
async def test_list_rate_plans_unfiltered() -> None:
    """Test listing all rate plans."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        plans = await client.list_rate_plans("94903")

    assert len(plans) == 3
    assert plans[0]["name"] == "E-1 -Residential Service Baseline Region Y"
    assert plans[1]["name"] == "Electric Vehicle EV (Sch) Rate A"
    assert plans[1]["has_tou_schedule"] is True


@pytest.mark.asyncio
async def test_list_rate_plans_filtered_by_utility() -> None:
    """Test filtering rate plans by utility."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        plans = await client.list_rate_plans("94903", utility="SoCal")

    assert len(plans) == 1
    assert plans[0]["utility"] == "SoCal Edison"


@pytest.mark.asyncio
async def test_get_rate_plan_found() -> None:
    """Test getting a specific rate plan by name."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        plan = await client.get_rate_plan("94903", "EV (Sch) Rate A")

    assert plan is not None
    assert plan["name"] == "Electric Vehicle EV (Sch) Rate A"


@pytest.mark.asyncio
async def test_get_rate_plan_not_found() -> None:
    """Test getting a non-existent rate plan."""
    mock_resp = _make_mock_response(SAMPLE_OPENEI_ITEMS)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()

    client = OpenEIClient(api_key="test-key", session=mock_session)
    async with client:
        plan = await client.get_rate_plan("94903", "Nonexistent Plan")

    assert plan is None


@pytest.mark.asyncio
async def test_no_api_key_raises() -> None:
    """Test that missing API key raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        client = OpenEIClient(api_key=None)
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        client._session = mock_session
        client._owned_session = False

        with pytest.raises(ValueError, match="OpenEI API key required"):
            await client.fetch_rates("94903")


@pytest.mark.asyncio
async def test_env_var_api_key() -> None:
    """Test API key from environment variable."""
    with patch.dict("os.environ", {"OPENEI_API_KEY": "env-key"}):
        client = OpenEIClient()
        assert client._api_key == "env-key"


@pytest.mark.asyncio
async def test_context_manager_creates_session() -> None:
    """Test that context manager creates/closes session."""
    with patch("nwp500.openei.aiohttp.ClientSession") as mock_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_cls.return_value = mock_session

        async with OpenEIClient(api_key="test-key") as client:
            assert client._session is mock_session
            assert client._owned_session is True

        mock_session.close.assert_awaited_once()
