import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from tool_helpers import _ok, _fail, _get


# From your message / deployment:
CHARITY_BASE_URL = "https://giverr-api.verior.co"
DEFAULT_AI_API_KEY = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"

# Postman collection base path:
# GET /api/v3/agent/charities/discovery?page=&limit=&search=
# GET /api/v3/agent/charities/{charityId}/detail
AGENT_BASE_PATH = "/api/v3/agent"


def _headers(api_key: str) -> dict:
    api_key = (api_key or "").strip()
    if not api_key:
        # Keep the error payload consistent with your other tools
        raise ValueError("X-API-KEY is required (api_key).")
    return {"X-API-KEY": api_key}


def build_charity_discovery_tool(
    base_url: str = CHARITY_BASE_URL,
    api_key: str = DEFAULT_AI_API_KEY,
) -> StructuredTool:
    """
    Coarse-grained endpoint:
      GET {baseUrl}/api/v3/agent/charities/discovery?page=1&limit=1000&search=...
    """

    def discover_charities(page: int = 1, limit: int = 1000, search: str = "") -> str:
        try:
            page_i = int(page)
            limit_i = int(limit)
            if page_i < 1:
                return _fail("page must be >= 1", provided=page)
            if limit_i < 1 or limit_i > 2000:
                return _fail("limit must be between 1 and 2000", provided=limit)

            params = {"page": page_i, "limit": limit_i}
            search = (search or "").strip()
            if search:
                params["search"] = search

            url = f"{base_url}{AGENT_BASE_PATH}/charities/discovery"
            # Using requests directly so headers are guaranteed to be sent
            resp = requests.get(url, params=params, headers=_headers(api_key), timeout=30)
            # Normalize success/error into your tool envelope
            if resp.status_code >= 400:
                return _fail(
                    f"HTTP {resp.status_code}",
                    endpoint="/api/v3/agent/charities/discovery",
                    http_status=resp.status_code,
                    response_text=resp.text[:2000],
                    params=params,
                )
            return _ok(
                resp.json(),
                endpoint="/api/v3/agent/charities/discovery",
                http_status=resp.status_code,
                params=params,
            )
        except ValueError as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/discovery")
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/discovery")

    class CharityDiscoveryInput(BaseModel):
        page: int = Field(1, description="1-based page index (default 1).")
        limit: int = Field(1000, description="Page size (default 1000, max 2000).")
        search: str = Field("", description="Optional search by name or registration number.")

    return StructuredTool.from_function(
        func=discover_charities,
        name="discover_charities",
        description=(
            "Retrieve a coarse-grained list of charities with their brief info.\n\n"
            "Use this tool when you need to:\n"
            "- list available charities\n"
            "- search charities by name or registration\n"
            "- compare charities (e.g., highest donor count)\n"
            "- obtain charity IDs for fetching detailed information\n\n"
            "Arguments:\n"
            "- page (int): page index starting from 1\n"
            "- limit (int): number of charities to return (recommended <= 1000)\n"
            "- search (str, optional): filter charities by name or registration number\n\n"
            "Response structure:\n"
            "result.data.items -> list of charities where each item contains:\n"
            "  _id: unique charity identifier\n"
            "  name: charity name\n"
            "  uniqueDonorCount: number of unique donors\n"
            "  isVerified: whether charity is verified\n"
            "  isActive: whether charity is active\n"
            "  countryCode: country code\n"
            "  city: city of charity\n\n"
            "result.data.pagination contains:\n"
            "  page, limit, total, hasMore\n\n"
            "If hasMore=true, additional pages exist and may need to be fetched "
            "to compute global rankings (e.g., highest donor count).\n\n"
            "Typical usage:\n"
            "1) Call this tool to retrieve charities.\n"
            "2) Extract the charity '_id'.\n"
            "3) Use 'charity_donation_stats_detail' to fetch full details."
        ),
        args_schema=CharityDiscoveryInput,
    )


def build_charity_detail_tool(
    base_url: str = CHARITY_BASE_URL,
    api_key: str = DEFAULT_AI_API_KEY,
) -> StructuredTool:
    """
    Fine-grained endpoint:
      GET {baseUrl}/api/v3/agent/charities/{charityId}/detail
    """

    def charity_details(charity_id: str) -> str:
        charity_id = (charity_id or "").strip()
        if not charity_id:
            return _fail("charity_id is required.", endpoint="/api/v3/agent/charities/{charityId}/detail")

        try:
            url = f"{base_url}{AGENT_BASE_PATH}/charities/{charity_id}/detail"
            resp = requests.get(url, headers=_headers(api_key), timeout=30)
            if resp.status_code >= 400:
                return _fail(
                    f"HTTP {resp.status_code}",
                    endpoint="/api/v3/agent/charities/{charityId}/detail",
                    http_status=resp.status_code,
                    charity_id=charity_id,
                    response_text=resp.text[:2000],
                )
            return _ok(
                resp.json(),
                endpoint="/api/v3/agent/charities/{charityId}/detail",
                http_status=resp.status_code,
                charity_id=charity_id,
            )
        except ValueError as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/{charityId}/detail", charity_id=charity_id)
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/{charityId}/detail", charity_id=charity_id)

    class CharityDetailInput(BaseModel):
        charity_id: str = Field(..., description="MongoDB ObjectId (_id) of the charity to fetch detail for.")

    return StructuredTool.from_function(
        func=charity_details,
        name="charity_details",
        description=(
            "Retrieve detailed information and donation statistics for a specific charity.\n\n"
            "Use this tool when the user asks about:\n"
            "- donation statistics\n"
            "- products or product categories\n"
            "- blogs or updates from the charity\n"
            "- address or contact information\n"
            "- detailed charity profile\n\n"
            "Argument:\n"
            "- charity_id (str): the unique charity identifier obtained from "
            "'charity_discovery_list'.\n\n"
            "Response structure:\n"
            "result.data contains:\n"
            "  impactLife (bool): whether the charity supports impact-life donations\n"
            "  donationAmount (number): total donation amount received\n"
            "  totalDonationByProduct (number): donation amount linked to products\n"
            "  productCategories (list[str]): categories of products offered\n"
            "  products (list): each product includes:\n"
            "      productName, pricePerUnit, description, category,\n"
            "      totalDonated, isActive, status\n"
            "  blogs (list): blog posts with title, description, hashtags, and media\n"
            "  address: charity location (street, city, state, country, postalCode)\n"
            "  contact: charity contact information (email, phone, website)\n\n"
            "Use this tool after identifying the charity using 'charity_discovery_list'."
        ),
        args_schema=CharityDetailInput,
    )


if __name__ == "__main__":
    import json

    print("\n==============================")
    print("Testing charity tools")
    print("==============================\n")

    discovery_tool = build_charity_discovery_tool()
    detail_tool = build_charity_detail_tool()

    # -------------------------------------------------
    # Test 1: Discovery Endpoint (Coarse-grained)
    # -------------------------------------------------
    print("TEST 1: charity_discovery_list\n")

    discovery_result = discovery_tool.invoke({
        "page": 1,
        "limit": 7,
        "search": ""
    })

    print("Discovery Output:\n")
    print(json.dumps(discovery_result, indent=2) if isinstance(discovery_result, dict) else discovery_result)

    charity_id = None

    # Try extracting a charity_id for next test
    try:
        parsed = discovery_result
        if isinstance(discovery_result, str):
            parsed = json.loads(discovery_result)

        items = (
            parsed.get("result", {})
            .get("data", {})
            .get("items", [])
        )

        if items:
            charity_id = items[0].get("_id")
    except Exception:
        pass

    # -------------------------------------------------
    # Test 2: Detail Endpoint (Fine-grained)
    # -------------------------------------------------
    if charity_id:
        print("\nTEST 2: charity_donation_stats_detail\n")
        print(f"Using charity_id: {charity_id}\n")

        detail_result = detail_tool.invoke({
            "charity_id": charity_id
        })

        print("Detail Output:\n")
        print(json.dumps(detail_result, indent=2) if isinstance(detail_result, dict) else detail_result)

    else:
        print("\nSkipping detail test — no charity_id extracted from discovery response.\n")

    print("\n==============================")
    print("Tool Tests Finished")
    print("==============================\n")