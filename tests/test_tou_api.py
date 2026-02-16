"""Tests for TOU API client methods (convert_tou, update_tou)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.api_client import NavienAPIClient
from nwp500.models import ConvertedTOUPlan, TOUInfo

# Realistic fixture data from HAR captures
SAMPLE_OPENEI_RATE_PLAN = {
    "approved": True,
    "utility": "Pacific Gas & Electric Co",
    "eiaid": 14328,
    "name": "Electric Vehicle EV (Sch) Rate A",
    "label": "67576350c51426c5b80fdae5",
    "sector": "Residential",
    "energyratestructure": [
        [{"rate": 0.34761, "unit": "kWh"}],
        [{"rate": 0.46016, "unit": "kWh"}],
    ],
    "energyweekdayschedule": [[0] * 24] * 12,
}

SAMPLE_CONVERT_RESPONSE = {
    "code": 200,
    "msg": "SUCCESS",
    "data": {
        "touInfo": [
            {
                "utility": "Pacific Gas & Electric Co",
                "name": "Electric Vehicle EV (Sch) Rate A",
                "schedule": [
                    {
                        "season": 3087,
                        "interval": [
                            {
                                "week": 124,
                                "startHour": 0,
                                "startMinute": 0,
                                "endHour": 6,
                                "endMinute": 59,
                                "priceMin": 31794,
                                "priceMax": 31794,
                                "decimalPoint": 5,
                            },
                            {
                                "week": 124,
                                "startHour": 7,
                                "startMinute": 0,
                                "endHour": 13,
                                "endMinute": 59,
                                "priceMin": 38967,
                                "priceMax": 38967,
                                "decimalPoint": 5,
                            },
                        ],
                    },
                ],
            }
        ]
    },
}

SAMPLE_UPDATE_RESPONSE = {
    "code": 200,
    "msg": "SUCCESS",
    "data": {
        "sourceType": "openei",
        "touInfo": {
            "name": "Electric Vehicle EV (Sch) Rate A",
            "schedule": [
                {
                    "season": 3087,
                    "interval": [
                        {
                            "week": 124,
                            "startHour": 0,
                            "startMinute": 0,
                            "endHour": 6,
                            "endMinute": 59,
                            "priceMin": 31794,
                            "priceMax": 31794,
                            "decimalPoint": 5,
                        },
                    ],
                },
            ],
            "utility": "Pacific Gas & Electric Co",
            "zipCode": 94903,
        },
    },
}


def _make_api_client() -> tuple[NavienAPIClient, AsyncMock]:
    """Create a NavienAPIClient with mocked auth and request."""
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.user_email = "test@example.com"
    mock_auth.session = MagicMock()

    client = NavienAPIClient(auth_client=mock_auth)
    mock_request = AsyncMock()
    client._make_request = mock_request
    return client, mock_request


@pytest.mark.asyncio
async def test_convert_tou() -> None:
    """Test POST /device/tou/convert."""
    client, mock_request = _make_api_client()
    mock_request.return_value = SAMPLE_CONVERT_RESPONSE

    plans = await client.convert_tou([SAMPLE_OPENEI_RATE_PLAN])

    assert len(plans) == 1
    assert isinstance(plans[0], ConvertedTOUPlan)
    assert plans[0].name == "Electric Vehicle EV (Sch) Rate A"
    assert plans[0].utility == "Pacific Gas & Electric Co"
    assert len(plans[0].schedule) == 1
    assert plans[0].schedule[0].season == 3087
    assert len(plans[0].schedule[0].intervals) == 2

    mock_request.assert_awaited_once_with(
        "POST",
        "/device/tou/convert",
        json_data={
            "sourceData": [SAMPLE_OPENEI_RATE_PLAN],
            "sourceType": "openei",
            "sourceVersion": 7,
            "userId": "test@example.com",
            "userType": "O",
        },
    )


@pytest.mark.asyncio
async def test_convert_tou_empty_response() -> None:
    """Test convert_tou with empty response."""
    client, mock_request = _make_api_client()
    mock_request.return_value = {
        "code": 200,
        "msg": "SUCCESS",
        "data": {"touInfo": []},
    }

    plans = await client.convert_tou([])
    assert plans == []


@pytest.mark.asyncio
async def test_update_tou() -> None:
    """Test PUT /device/tou."""
    client, mock_request = _make_api_client()
    mock_request.return_value = SAMPLE_UPDATE_RESPONSE

    tou_info_dict = {
        "name": "Electric Vehicle EV (Sch) Rate A",
        "schedule": [{"season": 3087, "interval": []}],
        "utility": "Pacific Gas & Electric Co",
        "zipCode": "94903",
    }

    result = await client.update_tou(
        mac_address="04786332fca0",
        additional_value="5322",
        tou_info=tou_info_dict,
        source_data=SAMPLE_OPENEI_RATE_PLAN,
        zip_code="94903",
    )

    assert isinstance(result, TOUInfo)
    assert result.name == "Electric Vehicle EV (Sch) Rate A"
    assert result.utility == "Pacific Gas & Electric Co"
    assert result.zip_code == 94903
    assert result.source_type == "openei"

    mock_request.assert_awaited_once_with(
        "PUT",
        "/device/tou",
        json_data={
            "additionalValue": "5322",
            "macAddress": "04786332fca0",
            "registerPath": "wifi",
            "sourceData": SAMPLE_OPENEI_RATE_PLAN,
            "sourceType": "openei",
            "touInfo": tou_info_dict,
            "userId": "test@example.com",
            "userType": "O",
            "zipCode": "94903",
        },
    )


@pytest.mark.asyncio
async def test_convert_tou_unauthenticated() -> None:
    """Test convert_tou raises when not authenticated."""
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.user_email = None
    mock_auth.session = MagicMock()

    client = NavienAPIClient(auth_client=mock_auth)

    from nwp500.exceptions import AuthenticationError

    with pytest.raises(AuthenticationError):
        await client.convert_tou([SAMPLE_OPENEI_RATE_PLAN])


@pytest.mark.asyncio
async def test_update_tou_unauthenticated() -> None:
    """Test update_tou raises when not authenticated."""
    mock_auth = MagicMock()
    mock_auth.is_authenticated = True
    mock_auth.user_email = None
    mock_auth.session = MagicMock()

    client = NavienAPIClient(auth_client=mock_auth)

    from nwp500.exceptions import AuthenticationError

    with pytest.raises(AuthenticationError):
        await client.update_tou(
            mac_address="aa:bb:cc",
            additional_value="1234",
            tou_info={},
            source_data={},
            zip_code="94903",
        )


def test_converted_tou_plan_model() -> None:
    """Test ConvertedTOUPlan model validation."""
    data = {
        "utility": "Pacific Gas & Electric Co",
        "name": "EV Rate A",
        "schedule": [
            {
                "season": 3087,
                "interval": [
                    {
                        "week": 124,
                        "startHour": 0,
                        "startMinute": 0,
                        "endHour": 6,
                        "endMinute": 59,
                        "priceMin": 31794,
                        "priceMax": 31794,
                        "decimalPoint": 5,
                    }
                ],
            }
        ],
    }
    plan = ConvertedTOUPlan.model_validate(data)
    assert plan.utility == "Pacific Gas & Electric Co"
    assert plan.name == "EV Rate A"
    assert len(plan.schedule) == 1
    assert plan.schedule[0].season == 3087
    assert len(plan.schedule[0].intervals) == 1
