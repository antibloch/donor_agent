const express = require("express");
const cors = require("cors");
const fs = require("fs");
const { v4: uuidv4 } = require("uuid");

const app = express();
app.use(cors());
app.use(express.json());

const DATA_FILE = "./data.json";

function loadData() {
  return JSON.parse(fs.readFileSync(DATA_FILE, "utf-8"));
}

function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

/* ============================
   1. CHECK WALLET BALANCE
============================ */
app.get("/wallet/:user_id", (req, res) => {
  const db = loadData();
  const { user_id } = req.params;

  const wallet = Object.values(db.wallets).find(
    (w) => w.user === user_id && !w.isDeleted,
  );

  if (!wallet) return res.status(404).json({ error: "Wallet not found" });

  res.json({
    wallet_id: wallet._id,
    balance: wallet.balance,
    lockedBalance: wallet.lockedBalance,
    isActive: wallet.isActive,
  });
});

/* ============================
   2. FUND WALLET
============================ */
app.post("/wallet/fund", (req, res) => {
  const { user_id, amount, card_id } = req.body;
  const db = loadData();

  const wallet = Object.values(db.wallets).find(
    (w) => w.user === user_id && !w.isDeleted,
  );
  if (!wallet) return res.status(404).json({ error: "Wallet not found" });

  const card = db.virtual_cards[card_id];
  if (!card || card.user !== user_id)
    return res.status(400).json({ error: "Invalid card" });

  if (card.isBlocked || !card.isActive)
    return res.status(400).json({ error: "Card blocked or inactive" });

  if (amount > card.limit)
    return res.status(400).json({ error: "Amount exceeds limit" });

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
    message: "Wallet funded successfully",
    new_balance: wallet.balance,
    transaction,
  });
});

/* ============================
   3. BLOCK CARD
============================ */
app.post("/card/block", (req, res) => {
  const { card_id } = req.body;
  const db = loadData();

  const card = db.virtual_cards[card_id];
  if (!card) return res.status(404).json({ error: "Card not found" });

  card.isBlocked = true;
  card.updatedAt = new Date().toISOString();

  saveData(db);

  res.json({ message: "Card blocked successfully" });
});

/* ============================
   4. GET USER CARDS
============================ */
app.get("/cards/:user_id", (req, res) => {
  const db = loadData();
  const { user_id } = req.params;

  const cards = Object.values(db.virtual_cards).filter(
    (c) => c.user === user_id && !c.isDeleted,
  );
  res.json({ cards });
});

/* ============================
   5. ADD NEW CARD
============================ */
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

  const db = loadData();

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

  res.json({ status: "success", card: newCard });
});

app.listen(3000, () => {
  console.log("Fintech service running on port 3000");
});

/* ============================
   6. GET ACTIVE AUCTIONS
============================ */
app.get("/auctions/active", (req, res) => {
  const db = loadData();

  const activeAuctions = Object.values(db.auctions).filter((auction) => {
    const now = new Date();
    const start = new Date(auction.startTimeStamp);
    const end = new Date(auction.endTimeStamp);
    return auction.status === "Active" && start <= now && now <= end;
  });

  res.json(activeAuctions);
});

// ============================
// 7. GET AUCTION DETAILS
// ============================
app.get("/auctions/:auction_id", (req, res) => {
  const db = loadData();
  const { auction_id } = req.params;

  const auction = Object.values(db.auctions).find((a) => a._id === auction_id);

  if (!auction) return res.status(404).json({ error: "Auction not found" });

  res.json(auction);
});