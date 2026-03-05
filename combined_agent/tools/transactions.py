import requests
from langchain_core.tools import tool
from tools.tool_helpers import _ok, _fail, _get

BASE_URL = "https://giverr-api.verior.co"
DONATION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"
headers = {
    "Authorization": f"Bearer {DONATION_TOKEN}"
}

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
    Fetch the wallet details for the authenticated user.  
    Returns: 
        dict:
            - success (bool): Indicates whether the request was successful
            - message (str): Response message from the API 
            - wallet (dict | None):
                - _id (str): Wallet ID
                - user (str): Associated user ID
                - balance (float): Available balance
                - lockedBalance (float): Locked amount 
                - isDeleted (bool): Deletion status
                - isActive (bool): Wallet active status
                - createdAt (str): Creation timestamp (ISO format)

        If the wallet is not found:
            - success (bool): False
            - message (str): Error message
    """
    try:
        response = requests.get(f"{BASE_URL}/api/v1/wallet/balance", headers=headers)

        response.raise_for_status() 
        data = response.json()
        
        if not data.get("success"):
            return {
                "success": False,
                "message": "Failed to fetch wallet balance",
                "wallet": None,
            } 

        wallet = data.get("wallet")

        # Clean wallet data
        if wallet:
            wallet.pop("__v", None)
            wallet.pop("transactionsHistory",None)

        return {
            "success": True,
            "message": "Wallet fetched successfully",
            "wallet": wallet,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error fetching wallet balance: {str(e)}",
            "wallet": None,
        }


@tool
def get_payment_methods():
    """
    Retrieve available payment methods for the authenticated mock user.
    
    Returns:
        dict:
            - success (bool): Indicates if the request was successful
            - data (dict):
                - success (bool): Internal operation status
                - message (str): Operation result message
                - count (int): Number of payment methods returned 
                - data (list): List of payment method objects, each including:
                    - last4 (str): Last four digits of the card
                    - type (int): Payment method type identifier
                    - createdAt (str): Creation timestamp (ISO 8601 format)
                    - brand (str): Card brand (e.g., visa)
                    - expiryDate (str): Card expiry date (YYYY-MM-DD)
                    - uid (str): Unique payment method identifier
                    - country (str): Issuing country code (ISO 2-letter)
                    
        If retrieval fails:
            - error (str): Error message explaining the issue. 
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/payment-apis/get-payment-methods",
            headers=headers
        )

        response.raise_for_status() 
        data = response.json()

        return {
            "success": True,
            "data": data
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

@tool
def add_payment_method():
    """
    Generate a hosted payment method page URL for the authenticated user.
                                                                                                                                                                                                                                                                                                                                                                                                                                                             
    Returns:
        dict:
            - success (bool): Indicates if the request was successful
            - data (dict): 
                - success (bool): Internal operation status
                - message (str): Operation result message
                - url (str): Hosted payment page URL where user can add new payment methods
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/payment-apis/add-method",
            headers=headers
        )

        response.raise_for_status()  # Raise exception for HTTP errors
        data = response.json()

        return {
            "success": True,
            "data": data
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }
@tool
def list_charities_by_country(country_code: str):
    """
    Retrieve a list of charities available in the specified country.
    
    Args:
        country_code (str): The country for which to fetch charities for e.g., (PK). You should ask the user for it. 
    
    Returns:
        dict: 
            - success (bool): Indicates if the request was successful
            - charities (list[dict]): List of charity objects, each containing:
                - _id (str): Charity ID
                - name (str): Charity name
                - email (str): Contact email
                - phone (str): Contact phone number
                - description (str): Charity description
                - address (dict): Charity address with fields:
                    - street (str), city (str), state (str), country (str), countryCode (str), postalCode (str), latitude (float), longitude (float)
                - verificationStatus (str): Approval status
                - CountryAvailability (list[dict]): List of countries where the charity operates
                - website (str): Charity website URL 
                - other fields like paymentCustomerId, registrationNumber, walletUid, partOfGiver, isDeleted, isSuspended, user, createdAt, updatedAt
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

        # Clean charities data
        if charities:
            charities.pop("documents", None)
            charities.pop("logo",None)
            charities.pop("isLikedByMe",None)
            charities.pop("walletUid",None)
            charities.pop("__v",None)

        return {
            "success": True,
            "charities": charities,
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }
    
@tool
def get_charity_donation_products(charityID: str):
    """
    Retrieve the information regarding donation products for a specific charity.
    Args:
        charityID (str): The unique identifier of the charity whose products 
                         are to be fetched. You should get it from list_charities_by_country() tool.

    Returns:
        dict:
            - success (bool): Indicates whether the request was successful.
            - data (list[dict]): List of product objects, each containing:
                - _id (str): Product ID.
                - partnerProd (str): Partner product reference ID. 
                - name (str): Product name. 
                - description (str): Product description.
                - pricePerUnit (int | float): Cost per unit of the product.
                - category (dict): Product category details:
                    - _id (str): Category ID.
                    - name (str): Category name.
                - charity (dict): Charity information:
                    - _id (str): Charity ID.
                    - name (str): Charity name.
                    - registrationNumber (str): Charity registration number.
                    - logo (str): Path/URL to charity logo.
                - partner (dict):
                    - _id (str): Partner ID.
                - minimumDonationQuantity (int): Minimum allowed donation quantity.
                - maximumDonationQuantity (int): Maximum allowed donation quantity.
                - availableQuantity (int): Total available quantity.
                - remainingQuantity (int): Remaining quantity available.
                - impactLife (int): Impact metric (e.g., number of lives impacted). 
                - location (dict):
                    - _id (str): Location ID.
                    - state (str)
                    - city (str)
                    - country (str)
                - createdAt (str): ISO timestamp of product creation.
                - updatedAt (str): ISO timestamp of last update.
                
    """
    params = {
        "page": 1,
        "limit": 10,
    }
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/donors/get-charity-products/{charityID}",
            headers=headers,
            params=params
        )
        response.raise_for_status()

        data = response.json()
        products = data.get("products", data.get("data", []))

        if isinstance(products, list):
            for product in products:
                product.pop("images", None)
                category = product.get("category")
                if isinstance(category, dict):
                    category.pop("color", None)
                charity = product.get("charity")
                if isinstance(charity, dict):
                    charity.pop("address", None)
                    charity.pop("logo", None)

        return {
            "success": True,
            "products": products,
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

@tool
def get_all_charities_with_grants():
    """
    Retrieve a paginated list of all charities along with their associated grants.
    
    Returns:
        dict:
            - success (bool): Indicates whether the request was successful. 
            - message (str): Response message from the server.
            - data (list[dict]): List of charity objects, each containing:
                
                - charity (dict): Charity details:
                    - _id (str): Charity ID.
                    - email (str): Charity email address.
                    - name (str): Charity name.
                    - registrationNumber (str): Charity registration number. 
                    - logo (str): Path/URL to charity logo.
                    - address (dict):
                        - street (str)
                        - city (str)
                        - state (str)
                        - country (str)
                        - countryCode (str)
                        - postalCode (str)
                        - latitude (float)
                        - longitude (float)
                    
                - grants (list[dict]): List of grant objects associated with the charity:
                    - _id (str): Grant ID.
                    - profile (str): Reference ID of the charity profile.
                    - profileModel (str): Profile model type (e.g., "CharityOrganization").
                    - title (str): Grant title.
                    - description (str): Grant description.
                    - expectedAmount (int | float): Target funding amount. 
                    - raisedAmount (int | float): Amount raised so far.
                    - status (str): Grant status (e.g., Started, Suspended, Completed, Pending, In Progress).
                    - location (dict):
                        - city (str)
                        - state (str)
                        - country (str)
                        - countryCode (str)
                        - latitude (float)
                        - longitude (float)
                    - createdAt (str): ISO timestamp when grant was created.
                    - updatedAt (str): ISO timestamp when grant was last updated.
            
            - totalItems (int): Total number of charities.
            - totalPages (int): Total number of pages.
            - currentPage (int): Current page number.
            - hasNext (bool): Whether a next page exists.
            - hasPrev (bool): Whether a previous page exists.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/donors/all-charities",
            headers=headers
        )

        response.raise_for_status()  
        data = response.json()

        return {
            "success": True,
            "data": data
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

@tool
def get_all_active_campaigns():
    """
    Retrieve a paginated list of all active campaigns.

    Returns:
        dict:
            - success (bool): Indicates whether the request was successful.
            - message (str): Response message from the server.
            
            - data (list[dict]): List of active campaign objects, each containing:
                - _id (str): Campaign ID.
                - title (str): Campaign title.
                - description (str): Campaign description (may contain HTML).
                - logo (str): Path/URL to campaign logo image.
                - backgroundImage (str): Path/URL to campaign background image.
                - goalSettings (bool): Whether goal tracking is enabled.
                - goalAmount (int | float): Target fundraising amount. 
                - receivedAmount (int | float): Amount raised so far.
                - meterOption (str): Indicates if progress meter is shown ("Yes"/"No").
                - isFeatured (bool): Whether the campaign is marked as featured.
                - isCauseCampaign (bool): Whether it is a cause-based campaign.
                - isP2P (bool): Whether it is a peer-to-peer campaign.
                - showToDonors (bool): Whether the campaign is visible to donors.
                - isEnabled (bool): Whether the campaign is currently active.
                - milestones (list[dict]): List of campaign milestones:
                    - _id (str): Milestone ID.
                    - title (str): Milestone title.
                    - description (str): Milestone description.
                    - checked (bool): Whether milestone is completed.
                - donationTypes (list[dict], optional): Donation type options (if applicable):
                    - _id (str): Donation type ID.
                    - name (str): Donation type name.
                    - createdBy (str): Creator profile ID.
                    - createdByModel (str): Creator model type.
                    - isDeleted (bool): Whether donation type is deleted.
                    - createdAt (str): ISO timestamp.
                    - updatedAt (str): ISO timestamp.
                - charity (dict, optional): Associated charity details (if campaign belongs to a charity):
                    - name (str): Charity name.
                    - logo (str): Charity logo.
                    - country (str): Charity country.
                - donor (dict, optional): Donor details (for donor-created campaigns):
                    - _id (str): Donor ID. 
                    - firstName (str): Donor first name.
                    - lastName (str): Donor last name.
                    - profile (str): Profile image path.
                - job (dict): Campaign category/location details:
                    - category (str): Campaign category.
                    - country (str): Country where campaign is focused. 
                - numberOfUniqueDonors (int): Total unique donors for this campaign.
                - createdAt (str): ISO timestamp when campaign was created.
                - updatedAt (str): ISO timestamp when campaign was last updated.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    
            - featuredCampaigns (list[dict]): List of featured campaign objects 
              (same structure as items inside `data`).
            - pagination (dict): Pagination details:
                - currentPage (int): Current page number.
                - totalPages (int): Total number of pages.
                - totalItems (int): Total number of campaigns.
                - itemsPerPage (int): Number of items per page.
                - hasNextPage (bool): Whether a next page exists.
                - hasPrevPage (bool): Whether a previous page exists.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/donors/fetch-all-active-campaigns",
            headers=headers
        )

        response.raise_for_status()  
        data = response.json()

        return {
            "success": True,
            "data": data
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }


@tool 
def get_donation_types_campaign():
    """
    Retrieve a paginated list of available campaign donation types.
    
    This endpoint returns donation type categories (e.g., chanda, fitra, hadya, 
    sadaqah) created by charities. These types are used to classify donations 
    within campaigns.
    
    Returns:
        dict:
            - success (bool): Indicates whether the request was successful.
            - message (str): Response message from the server.
            
            - data (list[dict]): List of donation type objects:
                - _id (str): Unique donation type ID.
                - createdBy (str): ID of the profile (e.g., charity) that created the donation type.
                - createdByModel (str): Model type of the creator (e.g., "CharityOrganization").
                - name (str): Name of the donation type (e.g., "chanda", "fitra").
                - isDeleted (bool): Whether the donation type has been soft-deleted.
                - createdAt (str): ISO timestamp when the donation type was created.
                - updatedAt (str): ISO timestamp when the donation type was last updated.
                - __v (int): Internal version key (used by database versioning, typically MongoDB).

            - pagination (dict): Pagination details:
                - currentPage (int): Current page number.
                - totalPages (int): Total number of pages.
                - totalItems (int): Total number of donation types.
                - itemsPerPage (int): Number of items per page.
                - hasNextPage (bool): Whether a next page exists.
                - hasPrevPage (bool): Whether a previous page exists.
    """
    params = {
        "page": 1,
        "limit": 50,
    }
    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/donors/campaign/donation-types",
            headers=headers,
            params=params
        )

        response.raise_for_status()  
        data = response.json()

        return {
            "success": True,
            "data": data
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

@tool 
def get_transaction_history():
    """
    Retrieve a paginated list of the user's last 30 wallet transactions.
    This endpoint returns all financial transactions associated with the 
    authenticated user's wallet, including donations, withdrawals, refunds, 
    and other balance movements. 
    
    Returns:
        dict:
            - success (bool): Indicates whether the request was successful.
            - message (str): Response message from the server.

            - data (list[dict]): List of transaction objects:
                - _id (str): Unique transaction ID.
                - user (str): User ID associated with the transaction.
                - wallet (str): Wallet ID linked to the transaction.
                - amount (int | float): Transaction amount.
                - description (str): Description of the transaction 
                  (e.g., donation reference or withdrawal details).
                - type (str): Transaction type 
                  (e.g., "deposit", "withdrawal").
                - status (str): Current transaction status 
                  (e.g., "pending", "completed", "refunded", "failed").
                - isDeleted (bool): Whether the transaction is soft-deleted.
                - createdAt (str): ISO timestamp when the transaction was created.
                - updatedAt (str): ISO timestamp when the transaction was last updated.
                - __v (int): Internal version key (used for database versioning, typically MongoDB).

            - pagination (dict): Pagination details:
                - currentPage (int): Current page number.
                - totalPages (int): Total number of pages.
                - totalItems (int): Total number of transactions.
                - itemsPerPage (int): Number of items per page.
                - hasNextPage (bool): Whether a next page exists.
                - hasPrevPage (bool): Whether a previous page exists.
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
            "data": data.get("data", []),
            "pagination": data.get("pagination", {})
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

# ----------------------------
# POST APIs
# ----------------------------
@tool
def fund_wallet(amount: float, paymentMethodId: str, password: str):
    """
    Fund a user's wallet using a selected payment method.

    This tool sends a funding request to the wallet service using the
    provided paymentMethodId and amount. It does not perform local
    wallet or card validation logic; validation is handled by the backend API.

    Args:
        amount (float): The amount to fund into the wallet. 
            Must be greater than zero.
        paymentMethodId (str): Unique identifier of the selected
            payment method (card) to be charged.
        password (str): The user's account password for transaction authorization.

    Returns:
        dict: A dictionary containing: 
            - success (bool): Indicates if the request was successful.
            - message (str): Confirmation message.
            - data (dict):
                - paymentRequestUid (str): Unique identifier of the payment request.
                - customerId (str): Unique customer identifier.
                - walletUid (str): Unique wallet identifier.
                - newBalance (float): Updated wallet balance after funding.

        If the request fails:
            - success (bool): False
            - message (str): Error description (e.g., missing fields,
              invalid payment method, limit exceeded).
    """
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

        response.raise_for_status()  # Raise HTTP errors
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
def product_donation(charityId: str, partners: list, categories: list, country: str, countryCode: str, products: list, password: str):
    """
    Create a product donation for a specific charity.
    
    This tool sends a product-based donation request to the donation service.
    It does not perform local validation of IDs, pricing, or quantities.
    All validation logic is handled by the backend API.
 
    Args:
        charityId (str): Unique identifier of the charity.
        partners (list): List of partner IDs involved in the donation.
        categories (list): List of category IDs related to the donation.
        country (str): Country name for the delivery address.
        countryCode (str): ISO country code (e.g., PK).
        products (list): List of product objects. Each product must contain:
            - partner (str): Partner ID
            - charityProd (str): Charity product ID
            - partnerProd (str): Partner product ID
            - category (str): Category ID
            - charityProdPrice (float): Product price
            - quantity (int): Quantity of the product
        password (str): The user's account password for transaction authorization.
        
    Returns:
        dict: A dictionary containing:
            - success (bool): Indicates if the request was successful.
            - message (str): Confirmation or error message.
            - data (dict): Donation details returned by backend.

        If the request fails:
            - success (bool): False 
            - message (str): Error description (e.g., invalid IDs,
              insufficient balance, validation failure).
    """
    auth = verify_user_password(password)
    if not auth['success']:
        return {
            "success":False,
            "message":f'Transaction Denied: {auth["message"]}',
            "data":{}
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

        response.raise_for_status()  # Raise HTTP errors
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
def campaign_donation(campaignId: str, amount: float, donationTypeId: str, password: str, campaignType: str = 'CharityOrganization'):
    """
    Make a monetary donation to a specific campaign.
    
    This tool sends a donation request to the backend service for a given campaign.
    All validation (IDs, amounts, donor balance, etc.) is handled by the backend API.
    The donation can be of any valid amount specified by the user.
    
    Args:
        campaignId (str): Unique identifier of the campaign to donate to.
        amount (float): Donation amount.
        donationTypeId (str): ID of the donation type to be used.
        password (str): The user's account password for transaction authorization.
        campaignType (str, optional): Type of campaign. Default is 'CharityOrganization'.
        
    Returns:
        dict: Dictionary containing the result of the donation.

        Success response:
            - success (bool): True if donation was successful.
            - message (str): Confirmation message from the backend.
            - data (dict):
                - donation (dict): Donation record details:
                    - _id (str): Internal donation record ID.
                    - donationId (str): Human-readable donation reference ID.
                    - campaignId (str): Campaign ID for which the donation was made.
                    - childCampaignId (str | None): Child campaign ID if applicable.
                    - charityId (str): Charity ID receiving the donation.
                    - donorId (str): Donor's user ID.
                    - donorTransactionId (str): Associated donor transaction ID.
                    - charityTransactionId (str): Associated charity transaction ID.
                    - donationType (str): Donation type ID.
                    - donationSource (str): Source of donation (e.g., "Internal").
                    - amount (float): Donated amount.
                    - createdAt (str): ISO timestamp when donation was created.
                    - updatedAt (str): ISO timestamp when donation was last updated.
                    - __v (int): Internal version key (MongoDB or DB versioning).
                - receiptUrl (str): URL/path to the donation receipt PDF.

        Failure response:
            - success (bool): False
            - message (str): Error description (e.g., invalid IDs, insufficient balance, validation failure).

    """
    auth = verify_user_password(password)
    if not auth["success"]:
        return {
            "success":False,
            "message":f"Transaction Denied: {auth['message']}",
            'data':{}
        }
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

        response.raise_for_status()  # Raise HTTP errors
        data = response.json()

        return {
            "success": True,
            "message": data.get("message", "Donation successful"),
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
def grant_donation(charityId: str, amount: float, grantId: str, password: str):
    """
    Create a grant donation for a specific charity.
    
    This tool sends a monetary donation request for a specific grant
    to the donation service.
    It does not perform local validation of IDs or balance checks.
    All validation logic is handled by the backend API. 

    Args:
        charityId (str): Unique identifier of the charity.
        amount (float): Donation amount to contribute toward the grant.
        grantId (str): Unique identifier of the grant being funded.
        password (str): The user's account password for transaction authorization.

    Returns:
        dict: A dictionary containing:
            - success (bool): Indicates if the request was successful.
            - message (str): Confirmation or error message. 

        If the request fails:
            - success (bool): False
            - message (str): Error description (e.g., invalid IDs,
            insufficient balance, validation failure).
    """
    auth = verify_user_password(password)
    if not auth["success"]:
        return {
            "success":False,
            "message":f"Transaction Denied: {auth['message']}",
            "data":{}
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

        response.raise_for_status()  # Raise HTTP errors
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

