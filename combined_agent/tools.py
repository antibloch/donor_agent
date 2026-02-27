import json
import os
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool,tool
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient


# --------------------------
# Common helpers
# --------------------------

CHARITY_URL = "http://localhost:3030"
AUCTION_URL = "http://localhost:3000"
DEFAULT_AUTH_TOKEN = "charity-demo-token-2026"
MOCK_USER_ID = "usr_mujtaba"
AUCTION_BASE_URL = "http://localhost:3000"


def _ok(result: Any, **meta) -> str:
    payload = {"ok": True, "result": result}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _fail(error: str, **meta) -> str:
    payload = {"ok": False, "error": error}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 10) -> Dict[str, Any]:
    r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    # Your Node /api/stats always returns 200 even on errors,
    # but other endpoints return 4xx; handle both.
    try:
        data = r.json()
    except Exception:
        data = {"raw_text": r.text}
    return {"status": r.status_code, "json": data}


# --------------------------
# 1) Legacy stats tool (/api/stats?q=...)
# --------------------------

def build_node_stats_tool(base_url: str = CHARITY_URL) -> StructuredTool:
    CANONICAL_TOOLS = [
        "charity_donor_count", "charity_impactlife", "charity_donor_amount",
        "charity_total_donation", "charity_items_category",
        "charity_product_price_description", "charity_blogs",
        "charity_address", "charity_country_availability", "charity_contact_info",
    ]

    def call_node_stats(tool_name: str) -> str:
        tool_name = (tool_name or "").strip()
        if not tool_name:
            return _fail("Tool name is required.", valid_tools=CANONICAL_TOOLS)
        if tool_name not in CANONICAL_TOOLS:
            return _fail("Invalid tool name.", provided=tool_name, valid_tools=CANONICAL_TOOLS)

        try:
            out = _get(f"{base_url}/api/stats", params={"q": tool_name})
            # /api/stats returns {ok: true/false, tool, query, data, ...}
            return _ok(out["json"], endpoint="/api/stats", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), tool=tool_name, endpoint="/api/stats")

    class CharityStatsInput(BaseModel):
        tool_name: str = Field(..., description="Exact tool name from the allowed list in the tool description")

    return StructuredTool.from_function(
        func=call_node_stats,
        name="get_charity_stats",
        description=(
            "Fetch internal charity data from Node-js server via /api/stats.\n"
            "Argument tool_name must be one of:\n" + "\n".join([f"- {t}" for t in CANONICAL_TOOLS])
        ),
        args_schema=CharityStatsInput,
    )



# --------------------------
BASE_URL = "https://giverr-api.verior.co"
DONATION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"
headers = {
    "Authorization": f"Bearer {DONATION_TOKEN}"
}

@tool
def check_wallet_balance():
    """
    Fetch the wallet and associated virtual card details
    for the authenticated user.  
    
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
                - transactionsHistory (list): List of transaction records
                - createdAt (str): Creation timestamp (ISO format)

            - virtualCard (dict | None):
                - _id (str): Virtual card ID
                - user (str): Associated user ID 
                - cardHolder (str): Card holder name
                - expiryDate (str): Card expiry date (YYYY-MM-DD)
                - isActive (bool): Card active status
                - isBlocked (bool): Card blocked status
                - cardType (str): Card network type (e.g., VISA)
                - currency (str): Card currency
                - limit (float): Spending limit
                - createdAt (str): Creation timestamp
                - updatedAt (str): Last update timestamp

        If the wallet is not found:
            - success (bool): False
            - message (str): Error message
    """
    try:
        response = requests.get(f"{BASE_URL}/api/v1/wallet/balance", headers=headers).json()
        
        if not response.get("success"):
            return {
                "success": False,
                "message": response.get("message", "Failed to fetch wallet balance"),
                "wallet": None,
                "virtualCard": None
            } 

        wallet = response.get("wallet")
        virtual_card = response.get("virtualCard")

        # Clean wallet data
        if wallet:
            wallet.pop("__v", None)

        # Clean virtual card data and extract last 4 digits
        if virtual_card:
            full_card_number = virtual_card.get("cardNumber", "")
            virtual_card["last4"] = full_card_number[-4:] if full_card_number else None
            virtual_card.pop("cardNumber", None)
            virtual_card.pop("cvv", None)

        return {
            "success": True,
            "message": response.get("message", "Wallet fetched successfully"),
            "wallet": wallet,
            "virtualCard": virtual_card
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error fetching wallet balance: {str(e)}",
            "wallet": None,
            "virtualCard": None
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
    Generate a hosted payment method page URL for the authenticated mock user.
    
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
        country_code (str): The country for which to fetch charities for e.g., (PK)
    
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
                - documents (dict): Verification documents with fields like registrationCertificate, taxExemptionCertificate, annualReport, governmentApproval
                - verificationStatus (str): Approval status
                - CountryAvailability (list[dict]): List of countries where the charity operates
                - website (str): Charity website URL 
                - logo (str): URL to charity logo
                - isLikedByMe (bool): Whether the current user has liked this charity
                - other fields like paymentCustomerId, registrationNumber, walletUid, partOfGiver, isDeleted, isSuspended, user, createdAt, updatedAt, __v
            - pagination (dict): 
                - currentPage (int): Current page number
                - totalPages (int): Total number of pages
                - totalResults (int): Total number of charities 
                - hasMore (bool): Whether more pages are available
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/donations/charities/{country_code}",
            headers=headers
        )

        response.raise_for_status()  
        data = response.json()

        return {
            "success": True,
            "charities": data.get("charities", []),
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

@tool
def get_charity_donation_products(charityID: str):
    """
    Retrieve the information regarding donation products for a specific charity.
    User can donate in any of the following product. For information related to
    different donation products of different charities, call this method.
    
    Args:
        charityID (str): The unique identifier of the charity whose products 
                         are to be fetched.
    
    Returns:
        dict:
            - success (bool): Indicates whether the request was successful.
            - data (list[dict]): List of product objects, each containing:
                - _id (str): Product ID.
                - partnerProd (str): Partner product reference ID. 
                - name (str): Product name. 
                - description (str): Product description.
                - pricePerUnit (int | float): Cost per unit of the product.
                - images (list[dict]): List of product images:
                    - url (str): Image file path or URL.
                    - isPrimary (bool): Whether this image is the primary image.
                    - _id (str): Image ID.
                - category (dict): Product category details:
                    - _id (str): Category ID.
                    - name (str): Category name.
                    - color (str): Category display color (hex code).
                - charity (dict): Charity information:
                    - _id (str): Charity ID.
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
            - pagination (dict):
                - currentPage (int): Current page number.
                - totalPages (int): Total number of pages.
                - totalItems (int): Total number of products.
                - hasNext (bool): Whether a next page exists.
                - hasPrev (bool): Whether a previous page exists. 
                
    """
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/donors/get-charity-products/{charityID}",
            headers=headers
        )

        response.raise_for_status()  
        data = response.json()

        return {
            "success": True,
            "products": data.get("products", data.get("data", [])),
            "pagination": data.get("pagination")
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
            f"{BASE_URL}/api/v1/payment-apis/add-method",
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
    try:
        response = requests.get(
            f"{BASE_URL}/api/v3/donors/campaign/donation-types",
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
def get_transaction_history(page: int = 1, sortBy: str = "createdAt", order: str = "desc"):
    """
    Retrieve a paginated list of the user's last 10 wallet transactions.
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
        "page": page,
        "limit": 10,
        "sortBy": sortBy,
        "order": order
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
def fund_wallet(amount: float, paymentMethodId: str):
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
def product_donation(charityId: str, partners: list, categories: list, country: str, countryCode: str, products: list):
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
def campaign_donation(campaignId: str, amount: float, donationTypeId: str, campaignType: str = 'CharityOrganization'):
    """
    Make a monetary donation to a specific campaign.
    
    This tool sends a donation request to the backend service for a given campaign.
    All validation (IDs, amounts, donor balance, etc.) is handled by the backend API.
    The donation can be of any valid amount specified by the user.
    
    Args:
        campaignId (str): Unique identifier of the campaign to donate to.
        amount (float): Donation amount.
        donationTypeId (str): ID of the donation type to be used.
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
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/donors/campaign/donate",
            headers=headers,
            json={
                "campaignId": campaignId,  # fixed typo from 'compaignId'
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
def grant_donation(charityId: str, amount: float, grantId: str):
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

    Returns:
        dict: A dictionary containing:
            - success (bool): Indicates if the request was successful.
            - message (str): Confirmation or error message. 

        If the request fails:
            - success (bool): False
            - message (str): Error description (e.g., invalid IDs,
            insufficient balance, validation failure).
    """
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




def build_get_wallet_balance_tool() -> StructuredTool:
    def get_wallet_balance() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/wallet/{MOCK_USER_ID}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class WalletInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_wallet_balance,
        name="get_wallet_balance",
        description=(
            "Fetch the current wallet balance for the authenticated user.\n"
            "Returns: balance, lockedBalance, availableBalance."
        ),
        args_schema=WalletInput,
    )


def build_get_active_auctions_tool() -> StructuredTool:
    def get_active_auctions() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/active")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionsInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_active_auctions,
        name="get_active_auctions",
        description=(
            "Fetch all currently active auctions.\n"
            "Returns: list of auctions with _id, title, minBidAmount, "
            "currentHighestBid, endTimeStamp, incrementType, incrementValue."
        ),
        args_schema=AuctionsInput,
    )


def build_get_auction_details_tool() -> StructuredTool:
    def get_auction_details(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionDetailsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_details,
        name="get_auction_details",
        description=(
            "Retrieve full details of a single auction by its ID.\n"
            "Returns: full auction object including currentHighestBid, totalBids, incrementType, incrementValue."
        ),
        args_schema=AuctionDetailsInput,
    )


def build_get_auction_bids_tool() -> StructuredTool:
    def get_auction_bids(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/bids")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionBidsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_bids,
        name="get_auction_bids",
        description=(
            "Retrieve all bids for a specific auction including the highest bid.\n"
            "Returns: totalBids, highestBid (amount, status, profile), bids list."
        ),
        args_schema=AuctionBidsInput,
    )


def build_get_auction_items_tool() -> StructuredTool:
    def get_auction_items(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/items")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionItemsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_items,
        name="get_auction_items",
        description=(
            "Retrieve all items listed under a specific auction.\n"
            "Returns: totalItems, items list with name, description, condition."
        ),
        args_schema=AuctionItemsInput,
    )


def build_get_my_bid_history_tool() -> StructuredTool:
    def get_my_bid_history() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/users/{MOCK_USER_ID}/bids")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class BidHistoryInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_my_bid_history,
        name="get_my_bid_history",
        description=(
            "Retrieve the authenticated user's full bid history across all auctions.\n"
            "Returns: totalBids, bids list with amount, status (Leading/Outbid/Won/Lost), "
            "auctionTitle, auctionStatus."
        ),
        args_schema=BidHistoryInput,
    )


def build_place_bid_tool() -> StructuredTool:
    def place_bid(auction_id: str, amount: float) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        if not amount or amount <= 0:
            return _fail("amount must be a positive number.")
        try:
            r = requests.post(
                f"{AUCTION_BASE_URL}/auction/bid",
                json={"user_id": MOCK_USER_ID, "auction_id": aid, "amount": amount},
                timeout=5,
            )
            if not r.text.strip():
                return _fail("Empty response from server.")
            data = r.json()
            if not data.get("success"):
                return _fail(data.get("message", "Bid failed."), details=data)
            return _ok(data)
        except requests.exceptions.ConnectionError:
            return _fail("Could not connect to auction server.")
        except requests.exceptions.Timeout:
            return _fail("Auction server timed out.")
        except Exception as e:
            return _fail(str(e))

    class PlaceBidInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction to bid on.")
        amount: float = Field(..., description="The bid amount in USD.", gt=0)

    return StructuredTool.from_function(
        func=place_bid,
        name="place_bid",
        description=(
            "Place a bid on an active auction on behalf of the authenticated user.\n"
            "Server validates: auction status, minimum bid, increment rules, config limit, wallet balance.\n"
            "On success: bid amount is locked in wallet. If outbid, amount is auto-released.\n"
            "Returns: bidId, auctionTitle, amount, nextMinimumBid, newLockedBalance, availableBalance."
        ),
        args_schema=PlaceBidInput,
    )


def build_finalize_ended_auctions_tool() -> StructuredTool:
    def finalize_ended_auctions() -> str:
        try:
            r = requests.post(f"{AUCTION_BASE_URL}/auction/finalize", timeout=10)
            if not r.text.strip():
                return _fail("Empty response from server.")
            data = r.json()
            return _ok(data)
        except requests.RequestException as e:
            return _fail(str(e))

    class FinalizeInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=finalize_ended_auctions,
        name="finalize_ended_auctions",
        description=(
            "Finalize all auctions that have ended.\n"
            "Deducts winning bid from winner wallet and releases locked funds for all other bidders.\n"
            "Returns: success message."
        ),
        args_schema=FinalizeInput,
    )

# --------------------------
# Tool setup
# --------------------------

async def setup_tools():
    local_tools = [
        # charity tools
        build_node_stats_tool(),
        PythonREPLTool(),
        # transactions tools
        check_wallet_balance, fund_wallet, get_payment_methods, add_payment_method, list_charities_by_country, get_charity_donation_products,
        get_all_charities_with_grants, product_donation, get_all_active_campaigns, grant_donation, get_transaction_history, get_donation_types_campaign, campaign_donation,
        # auction tools
        build_get_wallet_balance_tool(),
        build_get_active_auctions_tool(),
        build_get_auction_details_tool(),
        build_get_auction_bids_tool(),
        build_get_auction_items_tool(),
        build_get_my_bid_history_tool(),
        build_place_bid_tool(),
        build_finalize_ended_auctions_tool(),

    ]

    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    mcp_tools = await client.get_tools()
    return [*local_tools, *mcp_tools]




def build_tool_context(tools_by_name: dict):
    blocks = []
    for tool in tools_by_name.values():
        name = tool.name
        description = (getattr(tool, "description", "") or "No description.").strip()
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            arg_lines = []
            for k, v in fields.items():
                req = getattr(v, "is_required", lambda: False)()
                arg_lines.append(f"- {k} ({'required' if req else 'optional'})")
            args_text = "\n".join(arg_lines) if arg_lines else "No parameters"
        else:
            args_text = "- input (required string). For Python_REPL, this must be python code."
        blocks.append(f"""
{name}
Description:
{description}

Arguments:
{args_text}
""")
    return "\n\n".join(blocks)