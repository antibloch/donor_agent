const express = require("express");
const cors = require("cors");
const { v4: uuidv4 } = require("uuid");

const app = express();
app.use(cors());
app.use(express.json());

/* ---------------- MOCK AUTH USER ---------------- */

const MOCK_USER_ID = "6957c361b7df149a6c551b4c";

/* ---------------- IN-MEMORY DATABASE ---------------- */

const db = {
  wallets: {
    "6957c385b7df149a6c551b53": {
      _id: "6957c385b7df149a6c551b53",
      user: MOCK_USER_ID,
      balance: 4150.75,
      lockedBalance: 200,
      isDeleted: false,
      transactionsHistory: [],
      isActive: true,
      createdAt: "2026-01-02T13:09:25Z",
      __v: 3
    }
  },

  virtual_cards: {
    "6957d555b7df149a6c554555": {
      _id: "6957d555b7df149a6c554555",
      user: MOCK_USER_ID,
      cardNumber: "4111111111111111",
      cardHolder: "Mujtaba Mateen",
      expiryDate: "2028-05-01",
      cvv: "123",
      isActive: true,
      isBlocked: false,
      cardType: "VISA",
      currency: "USD",
      limit: 5000,
      createdAt: "2026-01-12T10:00:00Z",
      updatedAt: "2026-01-12T10:00:00Z",
      __v: 1
    }
  }
};

/* ---------------- HELPERS ---------------- */

function getUserWallet() {
  return Object.values(db.wallets).find(
    w => w.user === MOCK_USER_ID && !w.isDeleted
  );
}

function getActiveUserCard() {
  return Object.values(db.virtual_cards).find(
    c => c.user === MOCK_USER_ID && c.isActive && !c.isBlocked
  );
}

/* ---------------- 1. CHECK WALLET ---------------- */

app.get("/api/v1/wallet/balance", (req, res) => {
  const wallet = getUserWallet();
  const virtualCard = getActiveUserCard(); 

  if (!wallet) {
    return res.status(404).json({
      success: false,
      message: "Wallet not found"
    });
  }

  res.status(200).json({
    success: true,
    message: "Wallet fetched successfully",
    wallet: wallet,
    virtualCard: virtualCard || null
  });
});

/* ---------------- 2. FUND WALLET ---------------- */

app.post("/api/v1/payment-apis/fund-wallet", (req, res) => {
  const { amount, paymentMethodId } = req.body;

  if (!amount || !paymentMethodId) {
    return res.status(400).json({
      success: false,
      message: "Amount and paymentMethodId are required"
    });
  }

  return res.json({
    success: true,
    message: "Wallet funded successfully",
    data: {
      paymentRequestUid: "PR-3510F-F959B56",
      customerId: "CUS-3510F-8F3F75B",
      walletUid: "WA-3510F-4C2F124",
      newBalance: 9343
    }
  });
});

/* ---------------- 3. GET PAYMENT METHODS ---------------- */

app.get("/api/v1/payment-apis/get-payment-methods", (req, res) => {
  res.json({
    success: true,
    data: {
      success: true,
      message: "Fetched payment methods successfully",
      count: 1,
      data: [
        {
          last4: "4242",
          type: 1,
          createdAt: "2026-01-16T06:47:12+00:00",
          brand: "visa",
          expiryDate: "2029-02-01T00:00:00+00:00",
          uid: "PM-3510F-F5384D9",
          country: "US"
        }
      ]
    }
  });
});

/* ---------------- 4. ADD PAYMENT METHOD ---------------- */

app.post("/api/v1/payment-apis/add-method", (req, res) => {
  res.json({
    success: true,
    data: {
      success: true,
      message: "Hosted payment method page URL generated",
      url: "https://api.pay.biggorilla.app/v1/public/page/payment-methods?pubKey=pu_test_fc127af2263efe47bf994f4730366416c81fb28e5261d2f34ad63db1c009d97c&returnUrl=http%3A%2F%2Fdonor.verior.co%2Fdonation&customer=CUS-3510F-8F3F75B"
    }
  });
});

/* ---------------- 5. GET CHARITIES BY COUNTRY ---------------- */

app.get("/api/v1/donations/charities/:country", (req, res) => {
  const { country } = req.params;

  res.json({
    success: true,
    charities: [
      {
        _id: "6957c567b7df149a6c552513",
        name: "Al Khidmat",
        email: "charity@yopmail.com",
        phone: "+923197588571",
        description: "kasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdkkasdjakshflkjsajdk",
        address: {
          street: "Muhalla Ali Abad Talti, Tehsil Sehwan",
          city: "Bhan",
          state: "Sindh",
          country: country,
          countryCode: "PK",
          postalCode: "76160",
          latitude: 26.55831,
          longitude: 67.72139
        },
        documents: {
          registrationCertificate: { name: "Registration Certificate", expiryDate: null, url: "uploads\\verification_documents\\1767359973684-495413310-receipt.pdf", verified: "verified" },
          taxExemptionCertificate: { name: "Tax Exemption Certificate", expiryDate: null, url: "uploads\\verification_documents\\1767359973693-623745883-receipt.pdf", verified: "verified" },
          annualReport: { name: "Annual Report", year: 2026, url: "uploads\\verification_documents\\1767359973715-543811371-receipt.pdf", expiryDate: null, verified: "verified" },
          governmentApproval: { name: "Government Approval", expiryDate: null, url: "uploads\\verification_documents\\1767359973717-143661164-receipt.pdf", verified: "verified" }
        },
        verificationStatus: "Approved",
        CountryAvailability: [
          { country: "India", countryCode: "IN", _id: "6957c5ccb7df149a6c5525a8" },
          { country: "Pakistan", countryCode: "PK", _id: "6957c5ccb7df149a6c5525a9" },
          { country: "United Arab Emirates", countryCode: "AE", _id: "6957c5ccb7df149a6c5525aa" },
          { country: "United States", countryCode: "US", _id: "6957c5ccb7df149a6c5525ab" }
        ],
        website: "https://www.alkhidmat.com",
        logo: "uploads/charity-logos/1770102543437-195556637-istockphoto-1353332258-612x612.jpg",
        isLikedByMe: false,
        paymentCustomerId: "CUS-3510F-ABDD162",
        registrationNumber: "REG-76160",
        walletUid: "WA-3510F-8FB0480",
        partOfGiver: true,
        isDeleted: false,
        isSuspended: false,
        user: "6957c567b7df149a6c55250f",
        createdAt: "2026-01-02T13:17:27.390Z",
        updatedAt: "2026-02-03T07:09:03.446Z",
        __v: 0
      },
      {
        _id: "6957d4da18b6ecd763ad9b5e",
        name: "Edhi Foundation",
        email: "edhi@yopmail.com",
        phone: "+923101173683",
        description: "akdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhsakdjhajkshdkhs",
        address: {
          street: "Muhalla Ali Abad Talti",
          city: "Bhan",
          state: "Sindh",
          country: country,
          countryCode: "PK",
          postalCode: "76160",
          latitude: 26.55831,
          longitude: 67.72139
        },
        documents: {
          registrationCertificate: { name: "Registration Certificate", expiryDate: null, url: "uploads\\verification_documents\\1767363893006-87396187-receipt.pdf", verified: "verified" },
          taxExemptionCertificate: { name: "Tax Exemption Certificate", expiryDate: null, url: "uploads\\verification_documents\\1767363892989-334621071-receipt.pdf", verified: "verified" },
          annualReport: { name: "Annual Report", year: 2026, expiryDate: null, url: "uploads\\verification_documents\\1767363893016-9247905-receipt.pdf", verified: "verified" },
          governmentApproval: { name: "Government Approval", expiryDate: null, url: "uploads\\verification_documents\\1767363893000-99248107-receipt.pdf", verified: "verified" }
        },
        verificationStatus: "Approved",
        CountryAvailability: [
          { country: "Pakistan", countryCode: "PK", _id: "6957d52218b6ecd763ad9ba9" },
          { country: "United States", countryCode: "US", _id: "6957d52218b6ecd763ad9baa" }
        ],
        website: "https://edhifoundation.org",
        logo: "uploads/charity-logos/1770902683611-152509026-meaty-hamburger-restaurant_7939-1857.jpg",
        isLikedByMe: false,
        paymentCustomerId: "CUS-3510F-ED7D1C6",
        registrationNumber: "REG-1122876",
        walletUid: "WA-3510F-925A402",
        partOfGiver: true,
        isDeleted: false,
        isSuspended: false,
        user: "6957d4da18b6ecd763ad9b5a",
        createdAt: "2026-01-02T14:23:22.242Z",
        updatedAt: "2026-02-12T13:24:43.619Z",
        __v: 0
      }
    ],
    pagination: {
      currentPage: 1,
      totalPages: 1,
      totalResults: 2,
      hasMore: false
    }
  });
});

/* ---------------- GET CHARITY PRODUCTS ---------------- */

app.get("/api/v1/donors/get-charity-products/:charityId", (req, res) => {
  res.json({
    success: true,
    data: [
      {
        _id: "6985ea95a6a19be52a4d24a0",
        partnerProd: "6985cce2a6a19be52a4b6409",
        name: "Desert",
        description: "desrt product",
        pricePerUnit: 12,
        images: [],
        category: {
          _id: "6957c39db7df149a6c551ba6",
          name: "Food",
          color: "#DEFF9E"
        },
        charity: {
          _id: "6957c567b7df149a6c552513",
          address: {
            street: "Muhalla Ali Abad Talti, Tehsil Sehwan",
            city: "Bhan",
            state: "Sindh",
            country: "Pakistan",
            countryCode: "PK",
            postalCode: "76160",
            latitude: 26.55831,
            longitude: 67.72139
          },
          name: "Al Khidmat",
          registrationNumber: "REG-76160",
          logo: "uploads/charity-logos/sample.jpg"
        },
        partner: {
          _id: "6957c54eb7df149a6c5524fa"
        },
        minimumDonationQuantity: 1,
        maximumDonationQuantity: 10,
        availableQuantity: 100,
        remainingQuantity: 49,
        impactLife: 1,
        location: {
          _id: "6957c63cb7df149a6c5529ca",
          state: "California",
          city: "Adelanto",
          country: "United States"
        },
        createdAt: "2026-02-06T13:20:21.172Z",
        updatedAt: "2026-02-09T07:47:15.370Z"
      },
      {
        _id: "6982ed4357108b2ce2b7110d",
        partnerProd: "6982ec0e57108b2ce2b6e758",
        name: "Donation gift",
        description: "Sample description",
        pricePerUnit: 5,
        images: [
          {
            url: "uploads/products/sample.jpg",
            isPrimary: true,
            _id: "69831d2fb7e9c649e30c793a"
          }
        ],
        category: {
          _id: "6957c3c6b7df149a6c551be7",
          name: "Appliences",
          color: "#C2B2FA"
        },
        charity: {
          _id: "6957c567b7df149a6c552513",
          address: {
            street: "Muhalla Ali Abad Talti, Tehsil Sehwan",
            city: "Bhan",
            state: "Sindh",
            country: "Pakistan",
            countryCode: "PK",
            postalCode: "76160",
            latitude: 26.55831,
            longitude: 67.72139
          },
          name: "Al Khidmat",
          registrationNumber: "REG-76160",
          logo: "uploads/charity-logos/sample.jpg"
        },
        partner: {
          _id: "6957c54eb7df149a6c5524fa"
        },
        minimumDonationQuantity: 3,
        maximumDonationQuantity: 5,
        availableQuantity: 1000,
        remainingQuantity: 973,
        impactLife: 1,
        location: {
          _id: "6957c63cb7df149a6c5529ca",
          state: "California",
          city: "Adelanto",
          country: "United States"
        },
        createdAt: "2026-02-04T06:54:59.759Z",
        updatedAt: "2026-02-06T11:11:04.720Z"
      }
    ],
    pagination: {
      currentPage: 1,
      totalPages: 1,
      totalItems: 6,
      hasNext: false,
      hasPrev: false
    }
  });
});

/* ---------------- GET ALL CHARITIES WITH GRANTS ---------------- */

/* ---------------- GET ALL CHARITIES WITH GRANTS ---------------- */

app.get("/api/v3/donors/all-charities", (req, res) => {
  res.json({
    success: true,
    message: "Charities with grants fetched successfully",
    data: [
      {
        charity: {
          address: {
            street: "1223",
            city: "Jamshoro",
            state: "Sindh",
            country: "Pakistan",
            countryCode: "PK",
            postalCode: "233",
            latitude: 25.43608,
            longitude: 68.28017
          },
          _id: "6979bdf5415f4091db478ce0",
          email: "charitytest@yopmail.com",
          name: "Charity Test",
          registrationNumber: "12345666878",
          logo: "uploads/charity-logos/1770607070903-484067208-Gradient technology background _ AI-generatedâ¦.jfif"
        },
        grants: [
          {
            location: {
              city: "Jamshoro",
              state: "Sindh",
              country: "Pakistan",
              countryCode: "PK",
              latitude: 25.43608,
              longitude: 68.28017
            },
            _id: "6994722ba575f9452396ed3b",
            profile: "6979bdf5415f4091db478ce0",
            profileModel: "CharityOrganization",
            title: "Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet",
            description: "Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet Install solar palet",
            expectedAmount: 100,
            raisedAmount: 250,
            status: "Suspended",
            createdAt: "2026-02-17T13:50:35.312Z",
            updatedAt: "2026-02-19T11:44:43.186Z"
          },
          {
            location: {
              city: "Bhimbar",
              state: "Azad Kashmir",
              country: "Pakistan",
              countryCode: "PK",
              latitude: 32.97465,
              longitude: 74.07846
            },
            _id: "69947460a575f9452396ed87",
            profile: "6979bdf5415f4091db478ce0",
            profileModel: "CharityOrganization",
            title: "instal",
            description: "FAILED: When creating a Fund Raising task, the system displays an \"Others\" category or field that appears redundant or fails to provide the necessary contextual input fields, leading to inconsistent data entries for non-standard grants.",
            expectedAmount: 1,
            raisedAmount: 0,
            status: "Completed",
            createdAt: "2026-02-17T14:00:00.872Z",
            updatedAt: "2026-02-17T14:00:30.024Z"
          },
          {
            location: {
              city: "Ashkāsham",
              state: "Badakhshan",
              country: "Afghanistan",
              countryCode: "AF",
              latitude: 36.68333,
              longitude: 71.53333
            },
            _id: "6994a9cda575f94523972e6b",
            profile: "6979bdf5415f4091db478ce0",
            profileModel: "CharityOrganization",
            title: "jasd",
            description: "nafl",
            expectedAmount: 1,
            raisedAmount: 0,
            status: "Started",
            createdAt: "2026-02-17T17:47:57.809Z",
            updatedAt: "2026-02-17T17:49:35.530Z"
          },
          {
            location: {
              city: "Ashkāsham",
              state: "Badakhshan",
              country: "Afghanistan",
              countryCode: "AF",
              latitude: 36.68333,
              longitude: 71.53333
            },
            _id: "6994aa1ea575f94523972e80",
            profile: "6979bdf5415f4091db478ce0",
            profileModel: "CharityOrganization",
            title: "lkfjs",
            description: "knalFK",
            expectedAmount: 2,
            raisedAmount: 0,
            status: "Started",
            createdAt: "2026-02-17T17:49:18.317Z",
            updatedAt: "2026-02-17T17:49:33.575Z"
          },
          {
            location: {
              city: "Ashkāsham",
              state: "Badakhshan",
              country: "Afghanistan",
              countryCode: "AF",
              latitude: 36.68333,
              longitude: 71.53333
            },
            _id: "6994aaeba575f94523973584",
            profile: "6979bdf5415f4091db478ce0",
            profileModel: "CharityOrganization",
            title: "lf;dsl",
            description: "lkasmv",
            expectedAmount: 1,
            raisedAmount: 0,
            status: "Pending",
            createdAt: "2026-02-17T17:52:43.062Z",
            updatedAt: "2026-02-17T17:52:43.062Z"
          }
        ]
      },

      /* ---- Remaining charities included exactly as provided ---- */

      {
        charity: {
          address: {
            street: "dubia street ",
            city: "Dubai",
            state: "Dubai",
            country: "United Arab Emirates",
            countryCode: "AE",
            postalCode: "1234",
            latitude: 25.0657,
            longitude: 55.17128
          },
          _id: "695f459acdae51f647639c7f",
          email: "vivk233@yopmail.com",
          name: "HopeBridge Foundation",
          registrationNumber: "HBF-2026-001",
          logo: "uploads/charity-logos/1771307263092-654824107-Adobe Express - file.png"
        },
        grants: [
          {
            location: {
              city: "Brandon",
              state: "Manitoba",
              country: "Canada",
              countryCode: "CA",
              latitude: 49.84692,
              longitude: -99.95306
            },
            _id: "6993ff2ea575f94523956329",
            profile: "695f459acdae51f647639c7f",
            profileModel: "CharityOrganization",
            title: "Install solar panels on the community center to reduce",
            description: "The objective is to install solar panels on the community center to reduce electricity costs and promote sustainable energy. Requirements include sourcing panels, hiring certified installers, and ensuring compliance with local energy regulations.",
            expectedAmount: 20000,
            raisedAmount: 1050,
            status: "Suspended",
            createdAt: "2026-02-17T05:39:58.590Z",
            updatedAt: "2026-02-17T08:17:17.409Z"
          },
          {
            location: {
              city: "Beausejour",
              state: "Manitoba",
              country: "Canada",
              countryCode: "CA",
              latitude: 50.0622,
              longitude: -96.51669
            },
            _id: "69941e95a575f94523959e1a",
            profile: "695f459acdae51f647639c7f",
            profileModel: "CharityOrganization",
            title: "Install Solar Panels on the community center to reduce",
            description: "The objective is to install solar panels on the community center to reduce electricity costs and promote sustainable energy. Requirements include sourcing panels, hiring certified installers, and ensuring compliance with local energy regulations.",
            expectedAmount: 2000,
            raisedAmount: 250,
            status: "Started",
            createdAt: "2026-02-17T07:53:57.002Z",
            updatedAt: "2026-02-19T11:44:40.738Z"
          }
        ]
      }
    ],
    totalItems: 4,
    totalPages: 1,
    currentPage: 1,
    hasNext: false,
    hasPrev: false
  });
});

/* ---------------- SERVER ---------------- */

app.listen(3000, () => {
  console.log("Fintech mock service running on port 3000");
});