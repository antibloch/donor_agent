import requests
from langchain_core.tools import tool
from tools.tool_helpers import _ok, _fail, _get

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
    Retrieve the current wallet balance of the authenticated user.

    Use this tool when the user:
    - asks for their wallet balance
    - wants to check available funds
    - asks if they have enough balance to donate

    Returns:
        dict:
            success (bool): Whether the request succeeded.
            balance (float | None): Available wallet balance.
            lockedBalance (float | None): Amount currently locked.
            message (str): Status message.
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

        wallet = data.get("wallet", {})

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
    Retrieve the user's saved payment methods.

    Use this tool when the user:
    - asks to see their saved cards
    - wants to choose a payment method for a donation
    - asks if they have any stored payment methods

    Returns:
        dict:
            success (bool)
            payment_methods (list): List of saved payment methods
                - uid (str): Payment method ID
                - brand (str): Card brand (e.g., Visa, Mastercard)
                - last4 (str): Last four digits of the card
                - expiryDate (str): Card expiry date
                - country (str): Issuing country
            count (int): Number of saved payment methods
            message (str)
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
    Generate a hosted URL where the user can add a new payment method.

    Use this tool when the user:
    - wants to add a new card or payment method
    - asks to save a payment method
    - cannot find a payment method to use for donation

    Returns:
        dict:
            success (bool)
            url (str | None): Hosted URL for adding a payment method
            message (str)
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/payment-apis/add-method",
            headers=headers
        )

        response.raise_for_status()
        data = response.json()

        # Extract only relevant info
        url = data.get("data", {}).get("url")

        return {
            "success": True,
            "url": url,
            "message": "Payment method URL generated successfully."
        }

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
    Retrieve a list of charities operating in the specified country.

    Use this tool when the user:
    - wants to see charities in a specific country
    - asks for donation options by country
    - wants to select a charity for donation

    Args:
        country_code (str): 2-letter ISO country code (e.g., 'PK')

    Returns:
        dict:
            success (bool)
            charities (list): List of charity objects
                - _id (str): Charity ID
                - name (str): Charity name
                - email (str): Contact email
                - phone (str): Contact phone
                - description (str)
                - address (dict): street, city, state, country, postalCode
                - verificationStatus (str)
                - website (str)
            message (str)
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
    Retrieve active donation products for a specific charity.

    Use this tool when the user:
    - wants to see donation products for a charity
    - asks what they can donate to a selected charity
    - wants product details like price, quantity, and impact

    Args:
        charity_id (str): ID of the charity (from list_charities_in_country)

    Returns:
        dict:
            success (bool)
            products (list): List of donation products
                - _id (str): Product ID
                - name (str)
                - description (str)
                - pricePerUnit (float)
                - minimumDonationQuantity (int)
                - maximumDonationQuantity (int)
                - availableQuantity (int)
                - remainingQuantity (int)
                - isActive (bool)
            totalProducts (int)
            message (str)
    """
    params = {"page": 1, "limit": 50}
    headers = {
        'xApiKey':xApiKey
    }
    try:
        if charity_id is None:
            return {
            "success": False,
            "campaigns": [],
            "pagination": {},
            "message": f"No charity specified."
            }
        response = requests.get(
            f"{BASE_URL}/api/v3/agent/charities/{charity_id}/donation-products",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("data", {}).get("items", [])
        cleaned_products = []

        for item in items:
            images = item.get("images", [])
            primary_image = None
            for img in images:
                if img.get("isPrimary"):
                    primary_image = img.get("url")
                    break

            cleaned_products.append({
                "_id": item.get("_id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "pricePerUnit": item.get("pricePerUnit"),
                "minimumDonationQuantity": item.get("minimumDonationQuantity"),
                "maximumDonationQuantity": item.get("maximumDonationQuantity"),
                "availableQuantity": item.get("availableQuantity"),
                "remainingQuantity": item.get("remainingQuantity"),
                "isActive": item.get("isActive"),
            })

        return {
            "success": True,
            "products": cleaned_products,
            "totalProducts": len(cleaned_products),
            "message": f"{len(cleaned_products)} products found for charity {charity_id}."
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "products": [],
            "totalProducts": 0,
            "message": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "products": [],
            "totalProducts": 0,
            "message": f"Unexpected error: {str(e)}"
        }
    
@tool
def list_charity_grants(charity_id: str):
    """
    Retrieve all grants for a specific charity.

    Use this tool when the user:
        - wants to see grants for a charity
        - asks what grants they can donate to a selected charity
        - grants details such as raised amount, title, etc.

    Args:
        charity_id (str): ID of the charity (from list_charities_in_country)

    Returns:
        dict:
            success (bool)
            grants (list): List of grant objects
                - _id (str): Grant ID
                - title (str)
                - description (str)
                - expectedAmount (float)
                - raisedAmount (float)
                - status (str)
                - location (dict): { city, state, country, countryCode, latitude, longitude }
                - charityId (str): Reference to the charity
                - createdAt (str)
                - updatedAt (str)
            totalGrants (int)
            message (str)
    """
    try:
        headers = {
            'xApiKey':xApiKey
        }
        if charity_id is None:
            return {
            "success": False,
            "campaigns": [],
            "pagination": {},
            "message": f"No charity specified."
            }
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
    Retrieve all active campaigns, for a specific charity.

    Use this tool when the user:
        - wants to see active campaigns for a charity
        - asks what campaigns they can donate to a selected charity
        - campaign details such as raised amount, title, etc.
        - asks which donation types are valid for a selected campaign

    Args:
        charity_id (str): ID of the charity (from list_charities_in_country)

    Returns:
        dict:
            - success (bool)
            - campaigns (list): List of active campaign objects (flattened)
            - pagination (dict): { page, limit, total, hasMore }
            - message (str)
    """
    try:
        headers = {
            "xApiKey": xApiKey
        }
        
        # Add charityID as a query param if provided
        params = {"page": 1, "limit": 10}
        if charity_id is None:
            return {
            "success": False,
            "campaigns": [],
            "pagination": {},
            "message": f"No charity specified."
            }
        params["charityId"] = charity_id

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
            milestones = [
                {"_id": m.get("_id"), "title": m.get("title"),
                 "description": m.get("description"), "checked": m.get("checked", False)}
                for m in c.get("milestones", [])
            ]

            donation_types = [
                {"_id": dt.get("_id"), "name": dt.get("name")}
                for dt in c.get("donationTypes", [])
            ]

            charity = c.get("charity")
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
                "description": c.get("description"),
                "logo": c.get("logo"),
                "backgroundImage": c.get("backgroundImage"),
                "goalSettings": c.get("goalSettings"),
                "goalAmount": c.get("goalAmount"),
                "receivedAmount": c.get("receivedAmount"),
                "meterOption": c.get("meterOption"),
                "isFeatured": c.get("isFeatured"),
                "isCauseCampaign": c.get("isCauseCampaign"),
                "isP2P": c.get("isP2P"),
                "showToDonors": c.get("showToDonors"),
                "isEnabled": c.get("isEnabled"),
                "milestones": milestones,
                "donationTypes": donation_types,
                "charity": charity_info,
                "job": c.get("job", {}),
                "numberOfUniqueDonors": c.get("numberOfUniqueDonors", 0),
                "createdAt": c.get("createdAt"),
                "updatedAt": c.get("updatedAt")
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


# @tool
# def list_campaign_donation_types():
#     """
#     Retrieve all donation types available for campaigns.

#     Use this tool when the user:
#         - wants to see available donation types for campaigns
#         - asks about categories like chanda, fitra, hadya, sadaqah for campaigns
#         - is preparing to donate campaign and needs to select a type

#     Returns:
#         dict:
#             - success (bool)
#             - donation_types (list): List of donation type objects
#                 - _id (str)
#                 - name (str)
#                 - createdBy (str)
#                 - createdByModel (str)
#                 - isDeleted (bool)
#                 - createdAt (str)
#                 - updatedAt (str)
#             - pagination (dict): { currentPage, totalPages, totalItems, itemsPerPage, hasNextPage, hasPrevPage }
#             - message (str)
#     """
#     params = {
#         "page": 1,
#         "limit": 50
#     }
#     try:
#         response = requests.get(
#             f"{BASE_URL}/api/v3/donors/campaign/donation-types",
#             headers=headers,
#             params=params
#         )
#         response.raise_for_status()
#         data = response.json()

#         return {
#             "success": True,
#             "message": "Donation types retrieved successfully",
#             "data": data
#         }

#     except requests.exceptions.RequestException as e:
#         return {
#             "success": False,
#             "message": f"Request failed: {str(e)}",
#             "data": []
#         }

#     except Exception as e:
#         return {
#             "success": False,
#             "message": f"Unexpected error: {str(e)}",
#             "data": []
#         }

@tool
def get_transaction_history():
    """
    Retrieve the last 30 wallet transactions for the authenticated user.

    Use this tool when the user:
        - wants to see their recent wallet activity
        - asks for donation, withdrawal, or refund history
        - needs transaction details like amount, type, or status

    Returns:
        dict:
            - success (bool)
            - transactions (list): List of transaction objects
                - _id (str)
                - wallet (str)
                - amount (float)
                - description (str)
                - type (str): "deposit", "withdrawal", etc.
                - status (str): "pending", "completed", "refunded", "failed"
                - isDeleted (bool)
                - createdAt (str)
                - updatedAt (str)
            - pagination (dict): { currentPage, totalPages, totalItems, itemsPerPage, hasNextPage, hasPrevPage }
            - message (str)
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
    Fund a user's wallet using a selected payment method.

    Use this tool when the user:
        - wants to add money to their wallet
        - asks for wallet balance top-up
        - needs confirmation of successful funding

    Args:
        amount (float): Amount to add to the wallet. Must be > 0. (Ask from user)
        paymentMethodId (str): ID of the selected payment method (card) (from list_saved_payment_methods)
        password (str): User's account password for transaction authorization. (Ask from user)

    Returns:
        dict:
            - success (bool)
            - message (str): Confirmation or error message.
            - data (dict):
                - paymentRequestUid (str): Unique payment request ID.
                - customerId (str): Customer identifier.
                - walletUid (str): Wallet identifier.
                - newBalance (float): Wallet balance after funding.
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
    Create a product donation for a specific charity.

    Use this tool when the user:
        - wants to donate products to a charity

    Args:
        charityId (str): Unique identifier of the charity.
        partners (list): List of partner IDs involved in the donation.
        categories (list): List of category IDs related to the donation.
        country (str): Country name for delivery.
        countryCode (str): ISO country code (e.g., PK).
        products (list): List of product objects. Each must include:
            - partner (str): Partner ID
            - charityProd (str): Charity product ID
            - partnerProd (str): Partner product ID
            - category (str): Category ID
            - charityProdPrice (float): Price per product
            - quantity (int): Quantity to donate
        password (str): User password for transaction authorization.

    Returns:
        dict:
            - success (bool)
            - message (str): Confirmation or error message.
            - data (dict): Donation details returned by the backend.
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

        return {
            "success": True,
            "message": data.get("message", "Product donation created successfully"),
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
def campaign_donation(
    campaignId: str,
    amount: float,
    donationType: str,
    donationTypeId: str,
    password: str,
    campaignType: str = 'CharityOrganization'
):
    """
    Make a monetary donation to a specific campaign.

    Use this tool when the user:
        - wants to donate money to a campaign
        - has already seen valid donation types in prior interaction

    Args:
        campaignId (str): Unique ID of the campaign.
        amount (float): Donation amount.
        donationType (str): Donation type chosen by the user (e.g., chanda, fitra).
        donationTypeId (str): Donation type ID corresponding to the selected donationType.
        password (str): User password for transaction authorization.
        campaignType (str, optional): Type of campaign. Default is 'CharityOrganization'.

    Returns:
        dict:
            - success (bool)
            - message (str): Confirmation or error message.
            - data (dict): Donation details if successful.
    """
    # Verify user password
    auth = verify_user_password(password)
    if not auth["success"]:
        return {"success": False, "message": f"Transaction Denied: {auth['message']}", "data": {}}

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/donors/campaign/donate",
            headers=headers,
            json={
                "compaignId": campaignId,
                "amount": amount,
                "campaignType": campaignType,
                "donationTypeId": donationTypeId
            }
        )
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "message": data.get("message", "Donation successful"),
            "data": data.get("data", {})
        }

    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Request failed: {str(e)}", "data": {}}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {str(e)}", "data": {}}
    
@tool
def grant_donation(charityId: str, amount: float, grantId: str, password: str):
    """
    Make a monetary donation to a specific grant for a charity.

    Use this tool when the user:
        - wants to donate to a specific grant
        - has already seen available grants for a charity
        - wants to contribute a specific amount toward a grant

    Args:
        charityId (str): Unique ID of the charity. (from list_charity_grants)
        amount (float): Amount to donate toward the grant. (Ask user for it)
        grantId (str): Unique ID of the grant being funded. (from list_charity_grants)
        password (str): User password for transaction authorization. (Ask user for it)

    Returns:
        dict:
            - success (bool)
            - message (str): Confirmation or error message.
            - data (dict): Grant donation details if successful.

    Notes:
        - Validation of IDs, amounts, and balance is handled by the backend.
        - Agent can rely on prior tool responses to verify grant selection without extra API calls.
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

        return {
            "success": True,
            "message": data.get("message", "Grant donation successful"),
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
    "list_charities_by_country": {
        "domain": "donations",
        "type": "read",
        "when_to_use": "When the user wants to explore or select charities available in a specific country before making a donation, viewing causes, or initiating a transaction.",
        "do_not_use": "Do not use for retrieving donation products, grants, wallet information, or executing financial transactions. Do not use without a valid country_code.",
        "supports_pagination": True,
        "requires_auth": True,
        "example_usage": "tool_name=list_charities_by_country",
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


