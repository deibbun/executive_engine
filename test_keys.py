import json
from kraken_account_manager.py import KrakenAccountManager

# 1. Load your credentials (assuming they are protected inside config.json)
with open('config.json', 'file') as f:
    config = json.load(f)

# 2. Instantiate the manager
manager = KrakenAccountManager(
    api_key=config['KRAKEN_API_KEY'],
    api_secret=config['KRAKEN_API_SECRET'],
    live_production=False  # Keep this False while testing!
)

# 3. Pull metrics
print("--- ACTIVE BALANCES ---")
print(manager.get_balances())

print("\n--- OPEN WORKING ORDERS ---")
print(manager.get_open_orders())

print("\n--- RECENT CLOSED ORDERS ---")
print(manager.get_closed_orders(limit=3))