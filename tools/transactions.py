import requests
from langchain_core.tools import tool
from tools.tool_helpers import _ok, _fail, _get
import difflib 

BASE_URL = "https://giverr-api.verior.co"
DONATION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"
headers = {
    "Authorization": f"Bearer {DONATION_TOKEN}"
}
xApiKey = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"

def verify_user_password(password: str = None):
    import bcrypt
    # Dummy stored bcrypt hash for "Google@123"
    STORED_HASH = b"$2b$12$IRTl/UIdKOTPYUeBPiolH.d01DxSKXcokA/k70yed926lYovhkFq6"
    try:
        if bcrypt.checkpw(password.encode("utf-8"), STORED_HASH):
            return {"success": True}
        return {"success": False, "message": "Invalid password."}
    except Exception as e:
        return {"success": False, "message": str(e)}

PASSWORD = "Google@123"

@tool
def check_wallet_balance():
    """
        PURPOSE:
        Retrieve the current wallet balance of the authenticated user.

        MUST_CALL_FIRST:
        - when user asks about their wallet balance or available funds
        - before performing financial actions if balance verification is required

        DEFAULT_CHAIN:
        - check_wallet_balance -> donation_or_transaction_tool

        WHEN TO USE:
        - user asks for their wallet balance
        - user wants to check available funds
        - user asks whether they have enough balance to donate
        - balance verification is needed before a financial transaction

        REQUIRES (Intuitive Schema):
        - no arguments required (uses authenticated user context)

        REQUIRES (Detailed Schema):
            - none (wallet is resolved from authenticated session)

        RETURNS (Intuitive Schema):
        - user's wallet balance and locked balance

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the request succeeded
            - balance (float | None): available wallet balance
            - lockedBalance (float | None): amount currently locked and not available
            - message (str): status or informational message
 
        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - balance can be used to verify whether user has enough funds before donation or transaction
        - planner may compare donation amount with balance before proceeding

        DO NOT STOP HERE WHEN:
        - user intends to perform a donation or transaction
        - further financial actions are requested
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/wallet/balance",
            headers=headers
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            return {
                "success": False,
                "balance": None,
                "lockedBalance": None,
                "message": "Unable to fetch wallet balance."
            }

        wallet = data.get("data", {})

        return {
            "success": True,
            "balance": wallet.get("balance"),
            "lockedBalance": wallet.get("lockedBalance"),
            "message": "Wallet balance retrieved successfully."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "balance": None,
            "lockedBalance": None,
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "balance": None,
            "lockedBalance": None,
            "message": f"Unexpected error: {str(e)}"
        }


@tool
def list_saved_payment_methods():
    """
        PURPOSE:
        Retrieve the authenticated user's saved payment methods (e.g., stored cards) for use in transactions.

        MUST_CALL_FIRST:
        - before asking the user to choose a stored payment method for funding the wallet.
        - when verifying whether the user has any saved payment options

        DEFAULT_CHAIN:
        - list_saved_payment_methods -> select_payment_method -> funds_wallet

        WHEN TO USE:
        - user asks to see their saved cards
        - user wants to choose a payment method for funding the wallet
        - user asks if they have any stored payment methods
        - a payment method is required for completing a transaction

        REQUIRES (Intuitive Schema):
        - no arguments required (uses authenticated user context)

        REQUIRES (Detailed Schema):
            - none (payment methods are retrieved from the authenticated user profile)

        RETURNS (Intuitive Schema):
        - list of user's saved payment methods including card brand and masked number

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the request was successful
            - payment_methods (list) -> each item contains:
                uid (str): payment method identifier
                brand (str): card brand (e.g., Visa, Mastercard)
                last4 (str): last four digits of the card
                expiryDate (str): card expiration date
                country (str): issuing country
            - count (int): total number of saved payment methods
            - message (str): status or informational message

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - uid should be used as the payment_method_id for payment or donation tools
        - if planning before execution, planner should use placeholder:
        "<SELECTED_PAYMENT_METHOD_UID_FROM_LIST_SAVED_PAYMENT_METHODS>"

        DO NOT STOP HERE WHEN:
        - user intends to complete a donation or financial transaction
        - a payment method selection is required for the next step
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/payment-apis/get-payment-methods",
            headers=headers
        )

        response.raise_for_status()
        data = response.json()

        methods = data.get("data", {}).get("data", [])

        cleaned_methods = []
        for m in methods:
            cleaned_methods.append({
                "uid": m.get("uid"),
                "brand": m.get("brand"),
                "last4": m.get("last4"),
                "expiryDate": m.get("expiryDate"),
                "country": m.get("country")
            })

        return {
            "success": True,
            "payment_methods": cleaned_methods,
            "count": len(cleaned_methods),
            "message": "Saved payment methods retrieved successfully."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "payment_methods": [],
            "count": 0,
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "payment_methods": [],
            "count": 0,
            "message": f"Unexpected error: {str(e)}"
        }

@tool
def create_payment_method_url():
    """
        PURPOSE:
        Generate a hosted URL that allows the authenticated user to securely add a new payment method.

        MUST_CALL_FIRST:
        - after confirming that the user has no suitable saved payment methods
        - when the user explicitly wants to add or save a new payment method

        DEFAULT_CHAIN:
        - list_saved_payment_methods -> create_payment_method_url -> user_adds_payment_method -> list_saved_payment_methods

        WHEN TO USE:
        - user wants to add a new card or payment method
        - user asks how to save a payment method
        - user cannot find an existing payment method to use for wallet funding
        - user needs to register a new card before completing a transaction

        REQUIRES (Intuitive Schema):
        - no arguments required (uses authenticated user context)

        REQUIRES (Detailed Schema):
            - none (URL is generated for the authenticated user session)

        RETURNS (Intuitive Schema):
        - secure hosted URL where the user can add a new payment method

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the request was successful
            - url (str | None): hosted URL for adding a new payment method
            - message (str): status or informational message

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - after the user adds a payment method via the URL, list_saved_payment_methods should be called again to retrieve the newly added method
        - planner placeholder if needed:
        "<USER_ADDS_PAYMENT_METHOD_VIA_HOSTED_URL>"

        DO NOT STOP HERE WHEN:
        - user still needs to fund the wallet or complete a donation
        - newly added payment methods must be fetched before proceeding
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/payment-apis/add-method",
            headers=headers
        )

        response.raise_for_status()
        data = response.json()
        return data

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "url": None,
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "url": None,
            "message": f"Unexpected error: {str(e)}"
        }
@tool
def list_charities_in_country(country_code: str):
    """
        PURPOSE:
        Retrieve a list of charities operating in a specified country.

        MUST_CALL_FIRST:
        - when the user wants to discover charities within a specific country
        - before selecting a charity for donation when the charity_id is not known

        DEFAULT_CHAIN:
        - list_charities_in_country -> charity_details -> donation_products / grants / campaigns

        WHEN TO USE:
        - user asks to see charities in a specific country
        - user wants donation options available in a country
        - user wants to select a charity for donation
        - charity_id is not yet known but country context is provided

        REQUIRES (Intuitive Schema):
        - country_code (str): 2-letter ISO country code (e.g., PK)

        REQUIRES (Detailed Schema):
            - country_code (str): ISO 3166-1 alpha-2 country code identifying the country
              where charities operate

        RETURNS (Intuitive Schema):
        - list of charities operating in the specified country including id and name

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the request was successful
            - charities (list) -> each item contains:
                _id (str): charity identifier
                name (str): charity name
                email (str): contact email
                phone (str): contact phone
                description (str)
                address (dict):
                    street (str)
                    city (str)
                    state (str)
                    country (str)
                    postalCode (str)
                verificationStatus (str)
                website (str)
            - message (str): status or informational message

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - _id should be used as charity_id for subsequent tools such as:
          get_charity_donation_products, list_charity_grants, or get_charity_campaigns
        - if planning before execution, planner should use placeholder:
        "<SELECTED_CHARITY_ID_FROM_LIST_CHARITIES_IN_COUNTRY>"

        DO NOT STOP HERE WHEN:
        - user wants details about a specific charity
        - user intends to view donation options such as products, grants, or campaigns
    """
    params = {
        "page": 1,
        "limit": 10,
    }

    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/donations/charities/{country_code}",
            headers=headers,
            params=params
        )

        response.raise_for_status()
        data = response.json()
        charities = data.get("charities", [])

        cleaned_charities = []
        for c in charities:
            cleaned_charities.append({
                "_id": c.get("_id"),
                "name": c.get("name"),
                "email": c.get("email"),
                "phone": c.get("phone"),
                "description": c.get("description"),
                "address": {
                    "street": c.get("address", {}).get("street"),
                    "city": c.get("address", {}).get("city"),
                    "state": c.get("address", {}).get("state"),
                    "country": c.get("address", {}).get("country"),
                    "postalCode": c.get("address", {}).get("postalCode"),
                },
                "verificationStatus": c.get("verificationStatus"),
                "website": c.get("website")
            })

        return {
            "success": True,
            "charities": cleaned_charities,
            "message": f"{len(cleaned_charities)} charities found in {country_code}."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "charities": [],
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "charities": [],
            "message": f"Unexpected error: {str(e)}"
        }
    
@tool
def list_charity_products(charity_id: str):
    """
    PURPOSE:
    Retrieve donation products for a specific charity directly from the donors API 
    and return the full response including detailed product information and pagination.

    MUST_CALL_FIRST:
    - After obtaining a valid charity_id from list_charities_in_country or discover_charities.

    DEFAULT_CHAIN:
    - discover_charities -> charity_details -> get_charity_donation_products

    WHEN TO USE:
    - User wants to see all donation products for a selected charity.
    - User asks what they can donate to a charity.
    - User wants full product details including price, quantity, impact, images, category, charity info, partner info, and location.

    REQUIRES:
    - charity_id (str): unique identifier of the charity.

    RETURNS:
    - Full API response from /api/v1/donors/get-charity-products/{{charityId}}, including:
        - success (bool): indicates if the request was successful.
        - data (list): each item contains all product details as provided by the API, including:
            _id, partnerProd, name, description, pricePerUnit, images, category, charity, partner, 
            minimumDonationQuantity, maximumDonationQuantity, availableQuantity, remainingQuantity, 
            impactLife, location, createdAt, updatedAt.
        - pagination (dict): contains currentPage, totalPages, totalItems, hasNext, hasPrev.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - Each product in the data list provides:
        - _id: charity product identifier
        - parentID: partner product identifier
        - categoryId: category identifier
    These can be used for tools requiring donation product selection or checkout.
    - Planner can use placeholders:
        - "<SELECTED_CHARITY_PROD_ID_FROM_LIST_CHARITY_PRODUCTS>"
        - "<SELECTED_PARTNER_PROD_ID_FROM_LIST_CHARITY_PRODUCTS>"
        - "<SELECTED_CATEGORY_ID_FROM_GET_LIST_CHARITY_PRODUCTS>"

    DO NOT STOP HERE WHEN:
    - User wants further charity or campaign context.
    - Additional product details are needed beyond what the API returns.
    """
    if not charity_id:
            return {
                "success": False,
                "data": [],
                "pagination": {},
                "message": "No charity specified."
            }
    headers = {
        'X-API-KEY':xApiKey
    }
    try:
        response = requests.get(f"{BASE_URL}/api/v3/agent/charities/{charity_id}/donation-products", headers=headers)
        response.raise_for_status()
        return response.json()  

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "data": [],
            "pagination": {},
            "message": f"Request failed: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "data": [],
            "pagination": {},
            "message": f"Unexpected error: {str(e)}"
        }
    
@tool
def list_charity_grants(charity_id: str):
    """
        PURPOSE:
        Retrieve all grants for a specific charity and return detailed grant information.

        MUST_CALL_FIRST:
        - after obtaining a valid charity_id from list_charities_in_country or discover_charities

        DEFAULT_CHAIN:
        - discover_charities -> charity_details -> list_charity_grants

        WHEN TO USE:
        - user wants to see grants available for a selected charity
        - user asks what grants they can donate to
        - user wants details like raised amount, title, status, and location

        REQUIRES (Intuitive Schema):
        - charity_id (str): unique identifier of the charity

        REQUIRES (Detailed Schema):
        - charity_id (str): ID of the charity, obtained from list_charities_in_country or discover_charities

        RETURNS (Intuitive Schema):
        - list of grants for the charity including id, title, and status

        RETURNS (Detailed Schema):
            - success (bool): indicates if the request was successful
            - grants (list) -> each item contains:
                _id (str): grant identifier
                title (str)
                description (str)
                expectedAmount (float)
                raisedAmount (float)
                status (str)
                location (dict):
                    city (str)
                    state (str)
                    country (str)
                    countryCode (str)
                    latitude (float)
                    longitude (float)
                charityId (str): reference to the charity
                createdAt (str)
                updatedAt (str)
            - totalGrants (int): total number of grants returned
            - message (str): any status or informational message

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - grant _id can be used for tools requiring grant selection or checkout
        - if planning before execution, planner should use placeholder:
        "<SELECTED_GRANT_ID_FROM_list_charity_grants>"

        DO NOT STOP HERE WHEN:
        - user wants further charity information or donation product context
        - additional grant details are needed
    """
    if charity_id is None:
        return {
        "success": False,
        "campaigns": [],
        "pagination": {},
        "message": f"No charity specified."
        }
    headers = {
        'X-API-KEY':xApiKey
    }
    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/agent/grants",
            headers=headers,
            params={"charityId": charity_id}
        )
        response.raise_for_status()
        data = response.json()

        grants_list = data.get("data", {}).get("items", [])
        cleaned_grants = []

        for g in grants_list:
            location = g.get("location", {})
            cleaned_grants.append({
                "_id": g.get("_id"),
                "title": g.get("title"),
                "description": g.get("description"),
                "expectedAmount": g.get("expectedAmount"),
                "raisedAmount": g.get("raisedAmount"),
                "status": g.get("status"),
                "location": {
                    "city": location.get("city"),
                    "state": location.get("state"),
                    "country": location.get("country"),
                    "countryCode": location.get("countryCode"),
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude")
                },
                "charityId": g.get("profile"),
                "createdAt": g.get("createdAt"),
                "updatedAt": g.get("updatedAt")
            })

        return {
            "success": True,
            "grants": cleaned_grants,
            "totalGrants": len(cleaned_grants),
            "message": f"{len(cleaned_grants)} grants found for charity {charity_id}."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "grants": [],
            "totalGrants": 0,
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "grants": [],
            "totalGrants": 0,
            "message": f"Unexpected error: {str(e)}"
        }

@tool
def list_charity_active_campaigns(charity_id: str):
    """
    PURPOSE:
    Retrieve all active campaigns for a specific charity and return campaign details
    including the valid donation types allowed for each campaign.

    MUST_CALL_FIRST:
    - after obtaining a valid charity_id from list_charities_in_country or discover_charities
    - before making a campaign donation

    DEFAULT_CHAIN:
    - list_charities_in_country -> list_charity_active_campaigns -> campaign_donation

    WHEN TO USE:
    - user wants to see active campaigns for a charity
    - user asks what campaigns they can donate to
    - user wants to know which donation types are valid for each campaign
    - user intends to donate to a campaign but has not selected a donation type yet

    REQUIRES (Intuitive Schema):
    - charity_id (str): unique identifier of the charity

    REQUIRES (Detailed Schema):
    - charity_id (str): ID of the charity obtained from list_charities_in_country

    RETURNS (Intuitive Schema):
    - list of active campaigns with their allowed donation types (names)
    - Always show the allowed donation types to the user in bullet format

    RETURNS (Detailed Schema):
    - success (bool)
    - campaigns (list) -> each item contains:
        _id (str): campaign identifier
        title (str)
        expectedAmount (float)
        raisedAmount (float)
        status (str)
        donationTypes (list):
            - donationTypeId (str)
            - name (str)
        startDate (str)
        endDate (str)
        charityId (str)
    - pagination (dict):
        page (int)
        limit (int)
        total (int)
        hasMore (bool)
    - message (str)

    AGENT FORMAT RULE:
    - For every campaign returned, ALWAYS display the allowed donation types under the campaign title.
    - Never display donationTypeId to the user.
    - Always show donation type **names** (e.g., 'chanda', 'fitra', 'saqdah' and 'hadya').

    AGENT INSTRUCTION (STRICT):
    1. Show campaigns.
    2. Show allowed donationTypes for the selected campaign.
    3. STOP and ask the user:
    "Please choose a donation type for this campaign."

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - campaign _id -> campaignId for campaign_donation
    - donationTypeId -> mapped internally after user selects donation type name

    PLANNER PLACEHOLDERS:
    "<SELECTED_CAMPAIGN_ID>"

    USER INTERACTION RULE (STRICT):
    1. Show campaigns.
    2. Show allowed donation types (names) for the selected campaign.
    3. Always Ask the user:
       "Which donation type would you like to use?
       • Hadya
       • Sadqah
       • Fitra
       • Chanda"

    4. Wait for user input.
    5. Only after the user explicitly selects a donation type name,
       map it internally to donationTypeId before calling campaign_donation.
    6. If the input is invalid or misspelled, agent should re-prompt the user
       until a valid donation type is selected.
    7. Always show the donation types.
    """
    try:
        headers = {
            "X-API-KEY": xApiKey
        }

        if not charity_id:
            return {
                "success": False,
                "campaigns": [],
                "pagination": {},
                "message": "No charity specified."
            }

        params = {"charityId": charity_id, "page": 1, "limit": 25}

        response = requests.get(
            f"{BASE_URL}/api/v3/agent/campaigns/active",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        data = response.json().get("data", {})

        campaigns_list = data.get("items", [])
        cleaned_campaigns = []

        for c in campaigns_list:
            # Map milestones
            milestones = [
                {
                    "_id": m.get("_id"),
                    "title": m.get("title"),
                    "description": m.get("description"),
                    "checked": m.get("checked", False)
                }
                for m in c.get("milestones", [])
            ]

            # Map donationTypes correctly
            donation_types = [
                {
                    "donationTypeId": dt.get("_id"),
                    "name": dt.get("name")
                }
                for dt in c.get("donationTypes", [])
            ]

            charity = c.get("charity", {})
            charity_info = {
                "_id": charity.get("_id"),
                "name": charity.get("name"),
                "logo": charity.get("logo"),
                "country": charity.get("country"),
                "countryCode": charity.get("countryCode")
            } if charity else None

            cleaned_campaigns.append({
                "_id": c.get("_id"),
                "title": c.get("title"),
                "goalAmount": c.get("goalAmount"),
                "receivedAmount": c.get("receivedAmount"),
                "status": "active" if c.get("isEnabled") else "inactive",
                "milestones": milestones,
                "donationTypes": donation_types,
                "displayDonationTypes": ", ".join(dt["name"] for dt in donation_types),
                "startDate": c.get("startDate"),
                "endDate": c.get("endDate"),
                "charityId": charity_info["_id"] if charity_info else None,
                "charity": charity_info,
            })

        pagination = data.get("pagination", {})

        return {
            "success": True,
            "campaigns": cleaned_campaigns,
            "pagination": pagination,
            "message": f"{len(cleaned_campaigns)} active campaigns retrieved."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "campaigns": [],
            "pagination": {},
            "message": f"Request failed: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "campaigns": [],
            "pagination": {},
            "message": f"Unexpected error: {str(e)}"
        }

def get_campaign_donation_types():
    """
    Helper function to fetch available campaign donation types.
    Used internally by the agent to map donation type name → donationTypeId.
    """

    params = {
        "page": 1,
        "limit": 50
    }

    headers = {
        "X-API-KEY": xApiKey
    }

    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/agent/campaign/donation-types",
            headers=headers,
            params=params
        )
        response.raise_for_status()

        data = response.json().get("data", {})
        categories = data.get("categories", [])

        donation_map = {d["name"].lower(): d["_id"] for d in categories}

        return {
            "success": True,
            "donation_map": donation_map,
            "donation_types": categories
        }

    except Exception as e:
        return {
            "success": False,
            "donation_map": {},
            "donation_types": [],
            "message": str(e)
        }

@tool
def get_transaction_history():
    """
        PURPOSE:
        Retrieve the most recent wallet transaction history for the authenticated user.

        MUST_CALL_FIRST:
        - when the user asks about their wallet activity or past transactions
        - when transaction history is required for verification or support

        DEFAULT_CHAIN:
        - get_transaction_history -> transaction_details_or_support_action

        WHEN TO USE:
        - user wants to see their recent wallet activity
        - user asks for donation, withdrawal, deposit, or refund history
        - user needs transaction details like amount, type, or status
        - user wants to track a previous financial action

        REQUIRES (Intuitive Schema):
        - no arguments required (uses authenticated user context)

        REQUIRES (Detailed Schema):
            - none (transactions are retrieved from the authenticated user's wallet)

        RETURNS (Intuitive Schema):
        - recent wallet transactions including amount, type, and status

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the request was successful
            - transactions (list) -> each item contains:
                _id (str): transaction identifier
                wallet (str): wallet identifier associated with the transaction
                amount (float): transaction amount
                description (str): description of the transaction
                type (str): transaction type (e.g., "deposit", "withdrawal", "donation")
                status (str): transaction status (e.g., "pending", "completed", "refunded", "failed")
                isDeleted (bool): indicates whether the transaction has been deleted
                createdAt (str): timestamp when the transaction was created
                updatedAt (str): timestamp when the transaction was last updated
            - pagination (dict):
                currentPage (int)
                totalPages (int)
                totalItems (int)
                itemsPerPage (int)
                hasNextPage (bool)
                hasPrevPage (bool)
            - message (str): status or informational message

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - transaction _id can be used for support, dispute, or transaction detail tools
        - if planning before execution, planner should use placeholder: 
        "<SELECTED_TRANSACTION_ID_FROM_TRANSACTION_HISTORY>"

        DO NOT STOP HERE WHEN:
        - user requests deeper details about a specific transaction
        - follow-up actions such as refunds, support, or verification are required
    """
    params = {
        "page": 1,
        "limit": 30,
        "sortBy": "createdAt",
        "order": "desc"
    }
    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/donors/transactions",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "message": data.get("message", "Transaction history fetched successfully"),
            "transactions": data.get("data", []),
            "pagination": data.get("pagination", {})
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Request failed: {str(e)}",
            "transactions": [],
            "pagination": {}
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}",
            "transactions": [],
            "pagination": {}
        }
# ----------------------------
# POST APIs
# ----------------------------
@tool
def fund_wallet(amount: float, paymentMethodId: str, password: str):
    """
        PURPOSE:
        Fund the authenticated user's wallet using a selected payment method and confirm the updated balance.

        MUST_CALL_FIRST:
        - after obtaining a valid paymentMethodId from list_saved_payment_methods
        - after verifying the user's password for transaction authorization

        DEFAULT_CHAIN:
        - list_saved_payment_methods -> fund_wallet -> check_wallet_balance

        WHEN TO USE:
        - user wants to add money to their wallet
        - user asks for wallet top-up
        - user needs confirmation of successful funding and updated balance

        REQUIRES (Intuitive Schema):
        - amount (float): amount to add to wallet
        - paymentMethodId (str): selected payment method identifier
        - password (str): user password for authorization

        REQUIRES (Detailed Schema):
            - amount (float): must be greater than 0, obtained from user input
            - paymentMethodId (str): ID of the selected payment method (from list_saved_payment_methods)
            - password (str): authenticated user's account password for transaction authorization

        RETURNS (Intuitive Schema):
        - success status and updated wallet balance

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the funding succeeded
            - message (str): confirmation or error message
            - data (dict):
                paymentRequestUid (str): unique identifier for the payment request
                customerId (str): customer identifier
                walletUid (str): wallet identifier
                newBalance (float): wallet balance after funding

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - newBalance can be used for verifying whether the user has sufficient funds for donations
        - paymentRequestUid may be used for transaction tracking
        - planner placeholder if needed:
        "<PAYMENT_REQUEST_UID_FROM_FUND_WALLET>"

        DO NOT STOP HERE WHEN:
        - user wants to perform a donation or other transaction immediately after funding
        - wallet balance verification is required before the next financial action
    """
    # Verify password before initiating transaction
    auth = verify_user_password(password)
    if not auth["success"]:
        return {
            "success": False,
            "message": f"Transaction Denied: {auth['message']}",
            "data": {}
        }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/payment-apis/fund-wallet",
            headers=headers,
            json={
                "amount": amount,
                "paymentMethodId": paymentMethodId
            }
        )
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "message": data.get("message", "Wallet funded successfully"),
            "data": data.get("data", {})
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Request failed: {str(e)}",
            "data": {}
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}",
            "data": {}
        }

@tool
def product_donation(
    charityId: str, 
    partners: list, 
    categories: list, 
    country: str, 
    countryCode: str, 
    products: list, 
    password: str
):
    """
        PURPOSE:
        Create a product donation for a specific charity using selected products and partners.

        MUST_CALL_FIRST:
        - after obtaining charityId from list_charities_in_country or discover_charities
        - after selecting products and verifying user password for transaction authorization

        DEFAULT_CHAIN:
        - discover_charities -> list_charity_donation_products -> product_donation -> get_transaction_history

        WHEN TO USE:
        - user wants to donate products to a specific charity
        - user has selected products, partners, and categories for donation
        - user requires confirmation of the donation transaction

        REQUIRES (Intuitive Schema):
        - charityId (str): selected charity identifier
        - partners (list): partner IDs involved in donation
        - categories (list): category IDs related to the donation
        - country (str): delivery country name
        - countryCode (str): 2-letter ISO country code
        - products (list): products to donate including quantity and price
        - password (str): user password for authorization

        REQUIRES (Detailed Schema):
            - charityId (str): unique identifier of the charity
            - partners (list[str]): list of partner IDs participating in the donation
            - categories (list[str]): list of category IDs for the donation
            - country (str): name of the country for product delivery
            - countryCode (str): ISO 3166-1 alpha-2 country code
            - products (list[dict]) -> each item must contain:
                partner (str): partner ID
                charityProd (str): charity product ID (it is the _id received from LIST_CHARITY_DONATION_PRODUCTS)
                partnerProd (str): partner product ID (it is the parentID received from LIST_CHARITY_DONATION_PRODUCTS)
                category (str): category ID
                charityProdPrice (float): price per product
                quantity (int): number of units to donate
            - password (str): authenticated user's password for transaction authorization

        RETURNS (Intuitive Schema):
        - success status and confirmation of the product donation

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the donation was successfully created
            - message (str): confirmation or error message
            - data (dict): donation details returned by the backend

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - transaction details in data can be used to track the donation
        - planner placeholder if needed:
        "<PRODUCT_DONATION_TRANSACTION_ID>"

        DO NOT STOP HERE WHEN:
        - user wants to donate additional products or verify donation history
        - follow-up actions such as receipts or notifications are required
    """
    # Verify password before donation
    auth = verify_user_password(password)
    if not auth['success']:
        return {
            "success": False,
            "message": f'Transaction Denied: {auth["message"]}',
            "data": {}
        }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/donations/donate",
            headers=headers,
            json={
                "charityId": charityId,
                "partners": partners,
                "categories": categories,
                "address": {
                    "country": country,
                    "countryCode": countryCode
                },
                "products": products
            }
        )
        response.raise_for_status()
        data = response.json()
        return data

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Request failed: {str(e)}",
            "data": {}
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}",
            "data": {}
        }
@tool
def campaign_donation(
    campaignId: str,
    amount: float,
    donation_type: str,
    password: str,
    campaignType: str = 'CharityOrganization'
):
    """
    PURPOSE:
    Make a monetary donation to a specific campaign and confirm the donation details,
    using a human-readable donation type name. The tool internally maps the donation type
    name to the required donationTypeId, handling minor spelling variations.

    MUST_CALL_FIRST:
    - after obtaining campaignId from list_charity_active_campaigns
    - after obtaining donation_type from the user (human-readable name)
    - after verifying the user's password for transaction authorization

    CRITICAL RULE:
    - The agent MUST NEVER guess or auto-select donationTypeId.
    - The agent MUST ask the user to select one of the allowed donationTypes returned
      by list_charity_active_campaigns.
    - If the user-provided donation_type does not match any available type (even via fuzzy match),
      DO NOT call this tool and instead prompt the user to select again.
    - Always show the allowed donation types (e.g., 'chanda', 'fitra', 'saqdah' and 'hadya') for the selected campaign.

    USER INTERACTION RULE (STRICT):
    1. Show allowed donation types (names) for the selected campaign.
    2. Always Ask the user:
       "Which donation type would you like to use?
       • Hadya
       • Sadqah
       • Fitra
       • Chanda"

    DEFAULT_CHAIN:
    - list_charity_active_campaigns -> campaign_donation -> get_transaction_history

    WHEN TO USE:
    - user wants to donate money to a specific campaign
    - user has already seen valid donation types for the campaign
    - user requires confirmation of the donation transaction

    REQUIRES (Intuitive Schema):
    - campaignId (str): campaign identifier
    - amount (float): donation amount
    - donation_type (str): human-readable donation type name (e.g., 'chanda', 'fitra', 'saqdah' and 'hadya')
    - password (str): user password for authorization
    - campaignType (str, optional): type of campaign (default 'CharityOrganization')

    REQUIRES (Detailed Schema):
    - campaignId (str): unique identifier of the campaign
    - amount (float): monetary amount to donate
    - donation_type (str): name of the selected donation type
    - password (str): authenticated user's password for transaction authorization
    - campaignType (str, optional): campaign type; default is 'CharityOrganization'

    RETURNS (Intuitive Schema):
    - success status and confirmation of the monetary donation

    RETURNS (Detailed Schema):
    - success (bool): indicates whether the donation was successfully processed
    - message (str): confirmation, error, or guidance message
    - data (dict): donation details returned by the backend if successful

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - data can be used to track the donation or generate a receipt
    - planner placeholder if needed: "<CAMPAIGN_DONATION_TRANSACTION_ID>"

    DO NOT STOP HERE WHEN:
    - user wants to make additional donations or check donation history
    - follow-up actions such as receipt generation or reporting are required

    USER INPUT RULE:
    - The user should NEVER be asked for donationTypeId.
    - The agent must ask for the donation type NAME
      (e.g., 'chanda', 'fitra', 'saqdah') and internally map it to the correct donationTypeId
      before calling this tool.
    - Minor spelling mistakes (like 'sadqa' instead of 'saqdah') are handled via fuzzy matching,
      but if no match is found, prompt the user to select a valid donation type.
    - Always show the allowed donation types (e.g., 'chanda', 'fitra', 'saqdah' and 'hadya')
    """
    # Verify user password
    auth = verify_user_password(password)
    if not auth["success"]:
        return {"success": False, "message": f"Transaction Denied: {auth['message']}", "data": {}}

    try:
        # Fetch donation types using helper
        donation_data = get_campaign_donation_types()
        if not donation_data["success"]:
            return {"success": False, "message": "Failed to fetch donation types.", "data": {}}

        name_to_id = donation_data["donation_map"]
        available_names = list(name_to_id.keys())

        # Fuzzy match user input
        donation_name_lower = donation_type.lower()
        if donation_name_lower in name_to_id:
            donationTypeId = name_to_id[donation_name_lower]
        else:
            closest = difflib.get_close_matches(donation_name_lower, available_names, n=1, cutoff=0.6)
            if closest:
                donationTypeId = name_to_id[closest[0]]  # pick the closest match

        # Call backend API
        donation_response = requests.post(
            f"{BASE_URL}/api/v1/donors/campaign/donate",
            headers=headers,
            json={
                "compaignId": campaignId,
                "amount": amount,
                "campaignType": campaignType,
                "donationTypeId": donationTypeId
            }
        )
        donation_response.raise_for_status()
        return donation_response.json()

    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Request failed: {str(e)}", "data": {}}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {str(e)}", "data": {}}
    
@tool
def grant_donation(charityId: str, amount: float, grantId: str, password: str):
    """
        PURPOSE:
        Make a monetary donation to a specific grant for a charity and return donation details.

        MUST_CALL_FIRST:
        - after obtaining charityId and grantId from list_charity_grants
        - after verifying the user's password for transaction authorization

        DEFAULT_CHAIN:
        - list_charity_grants -> grant_donation -> get_transaction_history

        WHEN TO USE:
        - user wants to donate to a specific grant
        - user has already seen available grants for a charity
        - user wants to contribute a specific monetary amount toward a grant
        - user requires confirmation of the donation transaction

        REQUIRES (Intuitive Schema):
        - charityId (str): selected charity identifier
        - grantId (str): selected grant identifier
        - amount (float): donation amount
        - password (str): user password for authorization

        REQUIRES (Detailed Schema):
            - charityId (str): unique identifier of the charity (from list_charity_grants)
            - grantId (str): unique identifier of the grant (from list_charity_grants)
            - amount (float): monetary amount to donate toward the grant
            - password (str): authenticated user's password for transaction authorization

        RETURNS (Intuitive Schema):
        - success status and confirmation of the grant donation

        RETURNS (Detailed Schema):
            - success (bool): indicates whether the donation was successfully processed
            - message (str): confirmation or error message
            - data (dict): grant donation details returned by the backend if successful

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - data can be used to track the grant donation or generate a receipt
        - planner placeholder if needed:
        "<GRANT_DONATION_TRANSACTION_ID>"

        DO NOT STOP HERE WHEN:
        - user wants to donate to additional grants
        - follow-up actions such as receipt generation or reporting are required

    """
    # Verify user password
    auth = verify_user_password(password)
    if not auth["success"]:
        return {
            "success": False,
            "message": f"Transaction Denied: {auth['message']}",
            "data": {}
        }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v3/donors/donate-grant",
            headers=headers,
            json={
                "data": [
                    {
                        "charity": charityId,
                        "amount": amount,
                        "grant": grantId
                    }
                ]
            }
        )

        response.raise_for_status()
        data = response.json()
        return data
    
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Request failed: {str(e)}",
            "data": {}
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}",
            "data": {}
        }





#=======================Adding Meta Data for Tool Guidance=======================

metadata_transaction = {
    "check_wallet_balance": {
        "domain": "finance",
        "type": "read",
        "when_to_use": "When the user wants to check their available wallet balance, locked balance, or confirm sufficient funds before making a donation or financial transaction.",
        "do_not_use": "Do not use for making transactions, modifying wallet data, retrieving transaction history, or fetching other user profile information.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=check_wallet_balance",
        "hint": (
                    "- This tool requires authenticated user context (valid auth headers).\n"
                    "- Use this tool before initiating a financial transaction if balance confirmation is required.\n"
                    "- The response includes only cleaned wallet data (no transaction history or internal fields).\n"
                    "- If success is False, do not assume balance values and handle the error message accordingly."
                )
    },
    "get_payment_methods": {
        "domain": "finance",
        "type": "read",
        "when_to_use": "When the user wants to view their saved payment methods before making a transaction, selecting a card for donation, or confirming available payment options.",
        "do_not_use": "Do not use for adding, deleting, or modifying payment methods. Do not use for processing payments.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=get_payment_methods",
        "hint": (
                    "- This tool requires authenticated user context (valid auth headers).\n"
                    "- Use this tool before initiating a payment if the user needs to select a saved method.\n"
                    "- The response includes masked card details (e.g., last4) and metadata only.\n"
                    "- If success is False, handle the error field and avoid assuming payment methods exist."
                )
    }, 
    "add_payment_method": {
        "domain": "finance",
        "type": "read",
        "when_to_use": "When the user wants to add a new payment method and needs a hosted payment page URL to securely enter card details.",
        "do_not_use": "Do not use for retrieving existing payment methods or processing a payment transaction directly.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=add_payment_method",
        "hint": (
                    "- This tool requires authenticated user context (valid auth headers).\n"
                    "- It returns a hosted URL where the user must complete the payment method setup.\n"
                    "- The agent should instruct the user to open the returned URL to add their card.\n"
                    "- Do not expect card details in the response; only a secure redirection link is provided."
                )
    },
    "list_charities_in_country": {
        "domain": "donations",
        "type": "read",
        "when_to_use": "When the user wants to explore or select charities available in a specific country before making a donation, viewing causes, or initiating a transaction.",
        "do_not_use": "Do not use for retrieving donation products, grants, wallet information, or executing financial transactions. Do not use without a valid country_code.",
        "supports_pagination": True,
        "requires_auth": True,
        "example_usage": "tool_name=list_charities_in_country",
        "hint": (
                    "- Always ask the user for the country code (e.g., PK, US) before calling this tool.\n"
                    "- Use this tool early in the donation flow to narrow down charity options.\n"
                    "- The tool returns cleaned charity data but may still include backend metadata fields.\n"
                    "- Default pagination is page=1 and limit=10; if more results are needed, pagination handling should be implemented.\n"
                    "- If success is False, surface the error message and avoid assuming charities exist."
                )
    },
    "get_transaction_history": {
        "domain": "finance",
        "type": "read",
        "when_to_use": "When the user wants to view their recent wallet activity, including deposits, withdrawals, refunds, or donations, for tracking or verification purposes.",
        "do_not_use": "Do not use for initiating transactions, modifying wallet balance, or adding funds. Avoid using this tool for other users' transaction data.",
        "supports_pagination": True,
        "requires_auth": True,
        "example_usage": "tool_name=get_transaction_history",
        "hint": (
                    "- This tool retrieves the last 30 transactions by default, sorted by creation date descending.\n"
                    "- Use pagination details in the response to fetch more transactions if needed.\n"
                    "- Always ensure the user is authenticated before calling this tool.\n"
                    "- Each transaction object contains sensitive financial data; handle responses securely.\n"
                    "- If success is False, surface the error message and do not assume transaction data is available."
                ) 
    },
    "fund_wallet": {
        "domain": "finance",
        "type": "action",
        "when_to_use": "When the user explicitly wants to add funds to their wallet using a saved payment method (Payment Method Id) and has provided the amount, and transaction authorization password.",
        "do_not_use": "Do not use for checking wallet balance, retrieving payment methods, or making donations directly. Do not use if the user has not confirmed the funding amount or has not provided transaction authorization.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=fund_wallet",
        "hint": (
                    "- This tool performs a financial transaction and requires strong user confirmation before execution.\n"
                    "- Always confirm the funding amount and selected payment method with the user before calling this tool.\n"
                    "- The password argument is mandatory for transaction authorization and must never be logged or exposed.\n"
                    "- Ensure amount > 0 before calling the tool.\n"
                    "- On failure (success=False), carefully surface the backend message to the user and do not assume funds were added."
                )
    },
    "product_donation": {
        "domain": "donations",
        "type": "action",
        "when_to_use": "When the user wants to donate physical products to a charity using specified partners, categories, and product details, after confirming the delivery country and providing transaction authorization.",
        "do_not_use": "Do not use for monetary donations, fetching charity data, or wallet balance checks. Avoid using without confirmed product list and user password.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=product_donation",
        "hint": (
                    "- Always confirm charityId, products, partners, and categories with the user before execution.\n"
                    "- The password argument is mandatory for transaction authorization and must never be exposed.\n"
                    "- Backend API validates quantities, pricing, and IDs; the tool does not.\n"
                    "- On failure (success=False), relay the backend message to the user."
                )
    },
    "campaign_donation": {
        "domain": "donations",
        "type": "action",
        "when_to_use": "When the user wants to make a monetary donation to a specific campaign after confirming the amount, donation type, and transaction authorization password.",
        "do_not_use": "Do not use for product donations, wallet funding, or viewing transaction history. Avoid calling without user authorization.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=campaign_donation",
        "hint": (
                    "- Confirm campaignId, donation amount, and donationTypeId with the user before execution.\n"
                    "- Password is required for transaction authorization and must not be logged.\n"
                    "- The backend validates IDs, donor balance, and campaign eligibility.\n"
                    "- The response may include a receipt URL; surface it to the user if needed.\n"
                    "- If success=False, display the backend message to the user."
                )
    },
    "grant_donation": {
        "domain": "donations",
        "type": "action",
        "when_to_use": "When the user wants to donate a specific amount to a grant associated with a charity, after confirming the grantId, amount, and providing transaction authorization.",
        "do_not_use": "Do not use for product or campaign donations, wallet funding, or viewing wallet transactions. Avoid calling without user confirmation and password.",
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": "tool_name=grant_donation",
        "hint": (
                    "- Confirm charityId, grantId, and donation amount with the user before calling.\n"
                    "- The password argument is required for transaction authorization and must never be exposed.\n"
                    "- Backend handles validation of IDs and balance; the tool does not.\n"
                    "- On failure (success=False), relay the backend message to the user.\n"
                    "- Use this tool for monetary grant donations only."
                )
    }

}



