# Addition Setup

```
pip install -U mcp langchain-mcp-adapters
npm install cors
```


# Run

```
cd cd dummy_server
node server_charity.js  # Terminal 1

node server_auction.js  # Terminal 2


cd .. 
python main_agent.py  # Terminal 3
```


# Explanation
`tools` folder contains tool bodies in analytics.py, auctions.py, and transactions.py. 

`tools/tool_setup.py` is responsible for setting up the aggregation of tool names from analytics.py, auctions.py, and transactions.py.

Therefore if you edit tools in analytics.py, auctions.py, or transactions.py in folder `tools`, you need also update the tool names in tools/tool_setup.py.