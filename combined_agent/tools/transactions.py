import requests
from langchain_core.tools import tool
from .tool_helpers import _ok, _fail, _get



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
