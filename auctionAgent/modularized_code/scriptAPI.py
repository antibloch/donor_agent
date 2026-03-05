import requests

BASE_URL = "https://giverr-api.verior.co"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"
headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Test 1 - auctions list (no status filter = active only)
r = requests.get(f"{BASE_URL}/api/v3/auctions/list", headers=headers, params={"page": 1, "limit": 10})
print("STATUS:", r.status_code)
print("BODY:", r.json())


#bid history
DONOR_PROFILE_ID = "695803a95d120db61afaf03e"
r = requests.get(f"{BASE_URL}/api/v3/auctions/user/{DONOR_PROFILE_ID}/bids", headers=headers)
print("STATUS:", r.status_code)
print("BODY:", r.json())

#single auciton details
r = requests.get(f"{BASE_URL}/api/v3/auctions/507f1f77bcf86cd799439011", headers=headers)
print("STATUS:", r.status_code)
print("BODY:", r.json())

#place bid
r = requests.post(
    f"{BASE_URL}/api/v3/auctions/REAL_AUCTION_ID/bid",
    headers=headers,
    json={"donorProfileId": DONOR_PROFILE_ID, "bidAmount": 100}
)
print("STATUS:", r.status_code)
print("BODY:", r.json())