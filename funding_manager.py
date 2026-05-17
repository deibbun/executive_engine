from decimal import Decimal, ROUND_DOWN
import logging

class FundingManager:
    def __init__(self, min_trade_threshold=Decimal("10.00")):
        self.min_threshold = min_trade_threshold
        self.logger = logging.getLogger("ExecutiveEngine.Funding")

    def get_liquid_pool(self, total_balance, reserved_dict):
        """
        Calculates the actual spendable USD.
        Liquid = Total USD - sum(all reserved USD for pending tranches)
        """
        total_reserved = sum(reserved_dict.values())
        liquid_usd = total_balance - total_reserved
        return max(liquid_usd, Decimal("0.00"))

    def determine_division_factor(self, bots_ready_to_trade):
        """
        Implements your 1, 2, 3 division rule.
        """
        count = len(bots_ready_to_trade)
        if count == 0:
            return 0
        return min(count, 3)

    def allocate(self, total_balance, reserved_dict, active_signals):
        """
        The core logic:
        1. Identifies bots with 'Hunting' signals (Price > SMA).
        2. Calculates the share per bot based on the division factor.
        3. Enforces the $10 floor.
        """
        liquid_pool = self.get_liquid_pool(total_balance, reserved_dict)
        
        # Only bots that suggest a division (Price > SMA) get a slice
        ready_bots = [symbol for symbol, signal in active_signals.items() if signal['is_hunting']]
        
        divisor = self.determine_division_factor(ready_bots)
        
        if divisor == 0:
            return {symbol: Decimal("0.00") for symbol in active_signals.keys()}

        # Calculate share (e.g., Liquid / 3)
        raw_share = liquid_pool / Decimal(str(divisor))
        
        # Round down to 2 decimal places for exchange precision
        final_share = raw_share.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        allocations = {}
        for symbol in active_signals.keys():
            if symbol in ready_bots and final_share >= self.min_threshold:
                allocations[symbol] = final_share
            else:
                allocations[symbol] = Decimal("0.00")
                
        return allocations