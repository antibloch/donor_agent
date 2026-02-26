const express = require("express");
const cors = require("cors");
const fs = require("fs");
const { v4: uuidv4 } = require("uuid");

const app = express();
app.use(cors());
app.use(express.json());

/* ----------------  AUTH USER ---------------- */
const MOCK_USER_ID = "usr_mujtaba";

/* ---------------- DATA FILE ---------------- */
const DATA_FILE = "./data.json";

function loadData() {
  return JSON.parse(fs.readFileSync(DATA_FILE, "utf-8"));
}

function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function getDb() {
  try {
    return loadData();
  } catch (err) {
    console.log("data.json missing or invalid.");
    return {
      wallets: {},
      virtual_cards: {},
      auctions: {},
      auctionbids: {},
      auctionbidconfigs: {},
      auctionitems: {},
      auctionitemcategories: {},
      auctionitemdeliveryaddresses: {},
    };
  }
}

/* ============================================================
   1. GET WALLET BALANCE
============================================================ */
app.get("/wallet/:user_id", (req, res) => {
  const db = getDb();
  const { user_id } = req.params;

  const wallet = Object.values(db.wallets).find(
    (w) => w.user === user_id && !w.isDeleted,
  );

  if (!wallet)
    return res.status(404).json({ success: false, error: "Wallet not found" });

  res.json({
    success: true,
    wallet_id: wallet._id,
    balance: wallet.balance,
    lockedBalance: wallet.lockedBalance,
    availableBalance: wallet.balance - wallet.lockedBalance,
    isActive: wallet.isActive,
  });
});

/* ============================================================
   2. FUND WALLET
============================================================ */
app.post("/wallet/fund", (req, res) => {
  const { user_id, amount, card_id } = req.body;
  const db = getDb();

  const wallet = Object.values(db.wallets).find(
    (w) => w.user === user_id && !w.isDeleted,
  );
  if (!wallet)
    return res.status(404).json({ success: false, error: "Wallet not found" });

  const card = db.virtual_cards[card_id];
  if (!card || card.user !== user_id)
    return res.status(400).json({ success: false, error: "Invalid card" });

  if (card.isBlocked || !card.isActive)
    return res
      .status(400)
      .json({ success: false, error: "Card blocked or inactive" });

  if (amount > card.limit)
    return res
      .status(400)
      .json({ success: false, error: "Amount exceeds card limit" });

  wallet.balance += amount;

  const transaction = {
    transactionId: uuidv4(),
    type: "CREDIT",
    amount,
    currency: card.currency,
    timestamp: new Date().toISOString(),
  };

  wallet.transactionsHistory.push(transaction);
  saveData(db);

  res.json({
    success: true,
    message: "Wallet funded successfully",
    newBalance: wallet.balance,
    transaction,
  });
});

/* ============================================================
   3. GET USER CARDS
============================================================ */
app.get("/cards/:user_id", (req, res) => {
  const db = getDb();
  const { user_id } = req.params;
  const cards = Object.values(db.virtual_cards).filter(
    (c) => c.user === user_id,
  );
  res.json({ success: true, cards });
});

/* ============================================================
   4. BLOCK CARD
============================================================ */
app.post("/card/block", (req, res) => {
  const { card_id } = req.body;
  const db = getDb();

  const card = db.virtual_cards[card_id];
  if (!card)
    return res.status(404).json({ success: false, error: "Card not found" });

  card.isBlocked = true;
  card.updatedAt = new Date().toISOString();
  saveData(db);

  res.json({ success: true, message: "Card blocked successfully" });
});

/* ============================================================
   5. ADD NEW CARD
============================================================ */
app.post("/card/add", (req, res) => {
  const {
    user_id,
    card_number,
    card_holder,
    expiry_date,
    cvv,
    card_type,
    currency,
    limit,
  } = req.body;
  const db = getDb();

  const new_id = uuidv4().replace(/-/g, "").slice(0, 24);
  const newCard = {
    _id: new_id,
    user: user_id,
    cardNumber: card_number,
    cardHolder: card_holder,
    expiryDate: expiry_date,
    cvv,
    isActive: true,
    isBlocked: false,
    cardType: card_type,
    currency,
    limit,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    __v: 0,
  };

  db.virtual_cards[new_id] = newCard;
  saveData(db);
  res.json({ success: true, card: newCard });
});

/* ============================================================
   6. GET ACTIVE AUCTIONS
   Only returns auctions where status=Active AND now is within
   the startTimeStamp-endTimeStamp window.
   Enriched with currentHighestBid and totalBids.
============================================================ */
app.get("/auctions/active", (req, res) => {
  const db = getDb();
  const now = new Date();

  const activeAuctions = Object.values(db.auctions).filter((auction) => {
    const start = new Date(auction.startTimeStamp);
    const end = new Date(auction.endTimeStamp);
    return auction.status === "Active" && start <= now && now <= end;
  });

  const enriched = activeAuctions.map((auction) => {
    const bids = Object.values(db.auctionbids).filter(
      (b) => b.auction === auction._id,
    );
    const leading = bids.find((b) => b.status === "Leading");
    return {
      ...auction,
      currentHighestBid: leading ? leading.amount : null,
      totalBids: bids.length,
    };
  });

  res.json({ success: true, count: enriched.length, auctions: enriched });
});

/* ============================================================
   7. GET SINGLE AUCTION BY ID
   Enriched with currentHighestBid and totalBids.
============================================================ */
app.get("/auctions/:auction_id", (req, res) => {
  const db = getDb();
  const { auction_id } = req.params;

  const auction = db.auctions[auction_id];
  if (!auction)
    return res.status(404).json({ success: false, error: "Auction not found" });

  const bids = Object.values(db.auctionbids).filter(
    (b) => b.auction === auction_id,
  );
  const leading = bids.find((b) => b.status === "Leading");

  res.json({
    success: true,
    auction: {
      ...auction,
      currentHighestBid: leading ? leading.amount : null,
      totalBids: bids.length,
    },
  });
});

/* ============================================================
   8. GET BIDS FOR AN AUCTION
   Returns all bids sorted highest first, plus the leading bid.
============================================================ */
app.get("/auctions/:auction_id/bids", (req, res) => {
  const db = getDb();
  const { auction_id } = req.params;

  const auction = db.auctions[auction_id];
  if (!auction)
    return res.status(404).json({ success: false, error: "Auction not found" });

  const bids = Object.values(db.auctionbids).filter(
    (b) => b.auction === auction_id,
  );

  const highestBid =
    bids.length > 0
      ? bids.reduce((prev, curr) => (prev.amount > curr.amount ? prev : curr))
      : null;

  res.json({
    success: true,
    auction_id,
    totalBids: bids.length,
    highestBid: highestBid
      ? {
          amount: highestBid.amount,
          status: highestBid.status,
          profile: highestBid.profile,
        }
      : null,
    bids: bids.sort((a, b) => b.amount - a.amount),
  });
});

/* ============================================================
   9. GET ITEMS FOR AN AUCTION
============================================================ */
app.get("/auctions/:auction_id/items", (req, res) => {
  const db = getDb();
  const { auction_id } = req.params;

  const auction = db.auctions[auction_id];
  if (!auction)
    return res.status(404).json({ success: false, error: "Auction not found" });

  const items = Object.values(db.auctionitems || {}).filter(
    (item) => item.auction === auction_id,
  );

  res.json({ success: true, auction_id, totalItems: items.length, items });
});

/* ============================================================
   10. GET BID HISTORY FOR A DONOR
   Returns all bids by this user, enriched with auction title/status.
============================================================ */
app.get("/users/:user_id/bids", (req, res) => {
  const db = getDb();
  const { user_id } = req.params;

  const bids = Object.values(db.auctionbids).filter(
    (b) => b.profile === user_id,
  );

  const enriched = bids.map((bid) => {
    const auction = db.auctions[bid.auction] || {};
    return {
      ...bid,
      auctionTitle: auction.title || "Unknown",
      auctionStatus: auction.status || "Unknown",
    };
  });

  res.json({
    success: true,
    user_id,
    totalBids: enriched.length,
    bids: enriched.sort(
      (a, b) => new Date(b.createdAt) - new Date(a.createdAt),
    ),
  });
});

/* ============================================================
   11. POST PLACE BID
   Full validation flow:
   1. Required fields
   2. Auction exists
   3. Auction is Active
   4. Within time window
   5. Bid config exists and is Active
   6. Amount within config limit
   7. Minimum bid / increment rule
   8. Wallet has sufficient available balance
   9. Unlock previous leader, lock new bid
   10. Insert bid, save, respond
============================================================ */
app.post("/auction/bid", (req, res) => {
  try {
    const { user_id, auction_id, amount } = req.body;

    // 1. Required fields
    if (!user_id || !auction_id || !amount) {
      return res.json({
        success: false,
        message: "user_id, auction_id and amount are required",
      });
    }

    const numericAmount = Number(amount);
    if (isNaN(numericAmount) || numericAmount <= 0) {
      return res.json({ success: false, message: "Invalid bid amount" });
    }

    const db = getDb();

    // 2. Auction exists
    const auction = db.auctions[auction_id];
    if (!auction) {
      return res.json({
        success: false,
        message: "Auction not found",
        auction_id,
      });
    }

    // 3. Auction is Active
    if (auction.status !== "Active") {
      return res.json({
        success: false,
        message: `Auction is "${auction.status}" and not accepting bids`,
      });
    }

    // 4. Within time window
    const now = new Date();
    const start = new Date(auction.startTimeStamp);
    const end = new Date(auction.endTimeStamp);

    if (now < start) {
      return res.json({
        success: false,
        message: "Auction has not started yet",
      });
    }
    if (now > end) {
      return res.json({ success: false, message: "Auction has already ended" });
    }

    // 5. Bid config exists and is Active
    const config = Object.values(db.auctionbidconfigs).find(
      (c) =>
        c.profile === user_id &&
        c.auction === auction_id &&
        c.status === "Active",
    );

    if (!config) {
      return res.json({
        success: false,
        message:
          "You are not configured to bid on this auction. Please contact support.",
      });
    }

    // 6. Amount within config limit
    if (numericAmount > config.limit) {
      return res.json({
        success: false,
        message: `Your bid of $${numericAmount} exceeds your configured limit of $${config.limit}`,
        configLimit: config.limit,
        attemptedBid: numericAmount,
      });
    }

    // 6b. Self-bid check — user is already the highest bidder
    const existingBids = Object.values(db.auctionbids).filter(
      (b) => b.auction === auction_id,
    );
    const currentLeader = existingBids.find((b) => b.status === "Leading");

    if (currentLeader && currentLeader.profile === user_id) {
      return res.json({
        success: false,
        message: `You are already the highest bidder on this auction with a bid of $${currentLeader.amount}. Wait for someone to outbid you.`,
        currentBid: currentLeader.amount,
      });
    }

    // 7. Minimum bid / increment rule
    const bids = Object.values(db.auctionbids).filter(
      (b) => b.auction === auction_id,
    );

    const highestBidAmount =
      bids.length > 0 ? Math.max(...bids.map((b) => b.amount)) : null;

    let minRequired;
    if (!highestBidAmount) {
      minRequired = auction.minBidAmount;
    } else if (auction.incrementType === "fixed") {
      minRequired = highestBidAmount + auction.incrementValue;
    } else if (auction.incrementType === "percentage") {
      minRequired = parseFloat(
        (highestBidAmount * (1 + auction.incrementValue / 100)).toFixed(2),
      );
    } else {
      return res
        .status(400)
        .json({ success: false, error: "Invalid increment configuration" });
    }

    if (numericAmount < minRequired) {
      return res.json({
        success: false,
        message: `Your bid of $${numericAmount} is too low. Minimum required bid is $${minRequired}`,
        minRequired,
        currentHighestBid: highestBidAmount,
        yourBid: numericAmount,
      });
    }

    // 8. Wallet exists and has sufficient available balance
    const wallet = Object.values(db.wallets).find(
      (w) => w.user === user_id && !w.isDeleted,
    );

    if (!wallet) {
      return res
        .status(404)
        .json({ success: false, error: "Wallet not found" });
    }
    if (!wallet.isActive) {
      return res
        .status(400)
        .json({ success: false, error: "Wallet is not active" });
    }

    const availableBalance = wallet.balance - wallet.lockedBalance;
    if (numericAmount > availableBalance) {
      return res.json({
        success: false,
        message: `Insufficient balance. Available: $${availableBalance.toFixed(2)}, Required: $${numericAmount}`,
        availableBalance,
        requiredAmount: numericAmount,
      });
    }

    // 9. Unlock previous leading bid
    const leadingBid = bids.find((b) => b.status === "Leading");
    if (leadingBid) {
      const prevWallet = Object.values(db.wallets).find(
        (w) => w.user === leadingBid.profile,
      );
      if (prevWallet) {
        prevWallet.lockedBalance = Math.max(
          0,
          prevWallet.lockedBalance - leadingBid.amount,
        );
      }
      leadingBid.status = "Outbid";
      leadingBid.updatedAt = new Date().toISOString();
    }

    // 10. Lock new bid amount
    wallet.lockedBalance += numericAmount;

    // 11. Insert new bid
    const bidId = uuidv4().replace(/-/g, "").slice(0, 24);
    db.auctionbids[bidId] = {
      _id: bidId,
      profile: user_id,
      profileModel: "DonorProfile",
      auction: auction_id,
      amount: numericAmount,
      status: "Leading",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      __v: 0,
    };

    saveData(db);

    // Compute next minimum bid for convenience
    const nextMinBid =
      auction.incrementType === "fixed"
        ? numericAmount + auction.incrementValue
        : parseFloat(
            (numericAmount * (1 + auction.incrementValue / 100)).toFixed(2),
          );

    return res.json({
      success: true,
      message: `Bid of $${numericAmount} placed successfully on "${auction.title}"`,
      bidId,
      auctionTitle: auction.title,
      amount: numericAmount,
      nextMinimumBid: nextMinBid,
      newLockedBalance: wallet.lockedBalance,
      availableBalance: wallet.balance - wallet.lockedBalance,
    });
  } catch (error) {
    console.error("Bid Error:", error);
    return res
      .status(500)
      .json({ success: false, error: "Internal server error" });
  }
});

/* ============================================================
   12. POST FINALIZE ENDED AUCTIONS
   Marks ended auctions as Closed, deducts winning bid from
   winner wallet, releases locks for all other bidders.
============================================================ */
app.post("/auction/finalize", (req, res) => {
  try {
    finalizeEndedAuctions();
    res.json({
      success: true,
      message: "All ended auctions finalized successfully",
    });
  } catch (error) {
    console.error("Finalize Error:", error);
    res.status(500).json({ success: false, error: "Internal server error" });
  }
});

function finalizeEndedAuctions() {
  const db = getDb();
  const now = new Date();

  Object.values(db.auctions).forEach((auction) => {
    const end = new Date(auction.endTimeStamp);
    if (auction.status !== "Active" || now <= end) return;

    const bids = Object.values(db.auctionbids).filter(
      (b) => b.auction === auction._id,
    );

    if (bids.length === 0) {
      auction.status = "Closed";
      console.log(`Auction "${auction.title}" closed with no bids.`);
      return;
    }

    const highestBid = bids.reduce((prev, curr) =>
      prev.amount > curr.amount ? prev : curr,
    );

    bids.forEach((bid) => {
      const wallet = Object.values(db.wallets).find(
        (w) => w.user === bid.profile,
      );
      if (!wallet) return;

      if (bid._id === highestBid._id) {
        wallet.balance = Math.max(0, wallet.balance - bid.amount);
        wallet.lockedBalance = Math.max(0, wallet.lockedBalance - bid.amount);
        bid.status = "Won";
      } else {
        wallet.lockedBalance = Math.max(0, wallet.lockedBalance - bid.amount);
        bid.status = "Lost";
      }
      bid.updatedAt = now.toISOString();
    });

    auction.status = "Closed";
    console.log(
      `Auction "${auction.title}" finalized. Winner: ${highestBid.profile} at $${highestBid.amount}`,
    );
  });

  saveData(db);
  console.log("Finalization complete.");
}

/* ============================================================
   START SERVER
============================================================ */
app.listen(3000, () => {
  console.log("Auction service running on http://localhost:3000");
});
