## Setup

### 1. Clone Repository

```bash
git clone <repo-url>
cd donor_agent
```

### 3. Set API Key

```bash
# Edit .env and add:
NVIDIA_API_KEY=sk-ant-...
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
playwright install-deps
```

---

## Quick Run

Start an interactive conversation with the agent directly in your terminal:

```bash
python main_agent.py
```

### Example Interaction:

```
User: Show me active charities in Pakistan
Agent: [Lists charities with details]

User: What are the top 5 charities by donor count?
Agent: [Analyzes charity data and ranks them]

User: I want to donate 5000 to Charity X for education
Agent: [Guides through donation workflow]
```

### Features:

- Interactive multi-turn conversation
- Real-time tool execution (search, donations, transactions)
- Password-protected sensitive operations
- Rich console output with formatting
- Automatic error recovery and repair

---

## Run Docker Container

---

## IMPORT & RUN ON WINDOWS (Destination Machine)

Install docker desktop from: https://docs.docker.com/desktop/setup/install/windows-install/

Prerequisite: Ensure Docker Desktop is installed and running. Open
PowerShell or Command Prompt in the folder containing the .tar file.

1. Load the image into Docker:
   docker load -i donor_agent_image.tar

2. Run the Agent:
   docker run -it -e NVIDIA_API_KEY="paste_your_key_here" --name my_donor_agent updated_agent_image

   (Press Ctrl+C to stop)

---

## Docker Setup on Ubuntu (22.04 / Jammy)

# This document describes how to install **Docker Engine** on Ubuntu using the official Docker repository.

---

# 1. Remove Old Docker Versions (Optional)

Remove any conflicting packages:

```bash
sudo apt remove docker.io docker-compose docker-doc podman-docker containerd runc
```

---

# 2. Update System

```bash
sudo apt update
```

---

# 3. Install Required Dependencies

```bash
sudo apt install ca-certificates curl
```

Create directory for Docker keyrings:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
```

---

# 4. Add Docker GPG Key

```bash
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
-o /etc/apt/keyrings/docker.asc
```

Set permissions:

```bash
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

---

# 5. Add Docker Repository

```bash
echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list
```

---

# 6. Update Package Index

```bash
sudo apt update
```

Verify Docker repository appears in the update output.

---

# 7. Install Docker

```bash
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

---

# 8. Verify Installation

Check Docker version:

```bash
docker --version
```

Run test container:

```bash
sudo docker run hello-world
```

Expected output: Docker prints a success message confirming the installation.

---

# 9. Run Docker Without sudo (Recommended)

Add your user to the Docker group:

```bash
sudo usermod -aG docker $USER
```

Log out and log back in for the change to take effect.

---

# 10. Useful Docker Commands

List running containers:

```bash
docker ps
```

List all containers:

```bash
docker ps -a
```

List images:

```bash
docker images
```

Stop container:

```bash
docker stop <container_id>
```

Remove container:

```bash
docker rm <container_id>
```

<<<<<<< HEAD

---

---

## IMPORT & RUN ON LINUX (Destination Server)

Prerequisite: Ensure the Docker daemon is running. Open your terminal
in the directory where you uploaded the .tar file. You may need
=======

---

---

## IMPORT & RUN ON LINUX (Destination Server)

Prerequisite: Ensure the Docker daemon is running. Open your terminal
in the directory where you uploaded the .tar file. You may need

> > > > > > > 78233c66c0c52b5e7bbc9d9827c35a2f9c39cfd0
> > > > > > > to use 'sudo' depending on your user permissions.

1. Load the image into Docker:
   sudo docker load -i donor_agent_image.tar

2. Run the Agent:
   <<<<<<< HEAD
   sudo docker run -it -e NVIDIA_API_KEY="paste_your_key_here" --name my_donor_agent updated_agent_image
   (Press Ctrl+C to stop)

=======
sudo docker run -it -e NVIDIA_API_KEY="paste_your_key_here" --name my_donor_agent updated_agent_image
(Press Ctrl+C to stop)

> > > > > > > 78233c66c0c52b5e7bbc9d9827c35a2f9c39cfd0

---

## Run API Server

Start the FastAPI server:

```bash
uvicorn api:app --reload
```

Server will be available at `http://localhost:8000`

### Endpoints

| Method | Endpoint | Description                 |
| ------ | -------- | --------------------------- |
| GET    | /health  | Health check                |
| POST   | /chat    | Send a message to the agent |
| POST   | /reset   | Clear conversation history  |

### Health Check

```bash
GET http://localhost:8000/health
```

### Chat

```bash
POST http://localhost:8000/chat
```

Headers:

```
Content-Type: application/json
```

Body:

```json
{
  "message": "show me active auctions"
}
```

Response:

```json
{
  "response": "Here are the active auctions...",
  "requires_password": false
}
```

### Password Flow

When `requires_password` is `true`, send the password as the next message:

```json
{
  "message": "Google@123"
}
```

### Reset Session

```bash
POST http://localhost:8000/reset
```

Clears conversation history and starts a fresh session.

---

## Configuration

### Environment Variables (.env)

#### **Debug & Display**

- `DEBUG_MESSAGES`: Enable debug output (0 or 1)
- `SHOW_PLANNER_HISTORY`: Display planner conversation history (0 or 1)
- `SHOW_RESPONDER_HISTORY`: Display responder conversation history (0 or 1)
- `SHOW_GATE_TOOL_OUTPUTS`: Show tool execution results (0 or 1)

#### **Performance Tuning**

- `TRUNCATION_TOOL_LIMIT`: Character limit for tool calls (default: 12000)
- `TRUNCATION_LIMIT_PLANNER_HISTORY`: Max tokens for planner memory (default: 10000)
- `TRUNCATION_LIMIT_RESPONDER_HISTORY`: Max tokens for responder memory (default: 10000)
- `TRUNCATION_LIMIT_GATE_HISTORY`: Max tokens for gate memory (default: 10000)

#### **Agent Behavior**

- `GATE_MAX_REACT_STEPS`: Max error recovery attempts (default: 10)
- `DO_SELECTION`: Enable tool pool reduction (0 or 1)

---

## Architecture

The agent uses a multi-node architecture:

```
User Input
    ↓
[Planner Node]  ← Plans tool execution strategy
    ↓
[Validator Node] ← Validates plan feasibility
    ↓
[Executor Node]  ← Executes tools & collects results
    ↓
[Gate Node]      ← Error detection & recovery
    ↓
[Responder Node] ← Formats final response
    ↓
User Output
```

### Key Components:

- **main_agent.py**: Core agent graph definition
- **api.py**: FastAPI REST wrapper
- **nodes.py**: Agent node implementations (Planner, Validator, Executor, Gate, Responder)
- **llm.py**: LLM configuration (NVIDIA NIM API)
- **routing.py**: Conditional routing between nodes
- **history_formatters.py**: Message formatting utilities

---

## Available Tools

### Charity Discovery & Details

- `discover_charities`: Search charities by name/location
- `charity_details`: Get detailed info about a specific charity

### Donations

- `list_charities_in_country`: Browse charities by country
- `list_charity_products`: View donation products
- `list_charity_grants`: View available grants
- `list_charity_active_campaigns`: View active campaigns
- `product_donation`: Donate physical products
- `campaign_donation`: Donate to a campaign
- `grant_donation`: Donate to a grant

### Auctions

- `get_active_auctions`: Browse available auctions
- `get_auction_details`: Get detailed auction info
- `get_my_bid_history`: View your bids
- `place_bid`: Place a bid on an auction
- `get_donation_categories`: Browse donation categories
- `get_charities_by_donation_type`: Filter charities by cause

### Wallet & Payments

- `check_wallet_balance`: Check your balance
- `list_saved_payment_methods`: View saved cards
- `create_payment_method_url`: Add a new payment method
- `fund_wallet`: Add funds to wallet
- `get_transaction_history`: View transaction history

### Analytics

- `Python_REPL`: Execute Python for data analysis (uses pandas, numpy, scipy)
- `fetch_url`: Fetch website content for analysis
- `Python_REPL` tool supports advanced analytics using:
  - **pandas**: Multi-charity comparisons, aggregations, grouping
  - **numpy**: Array operations and numerical computations
  - **scipy**: Statistical analysis and optimization
  - **statistics**: Built-in mean, median, stdev functions
