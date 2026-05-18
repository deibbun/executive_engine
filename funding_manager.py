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
        
    def calculate_drawdown_governor(self, db_conn, base_risk: float = 0.02, floor_risk: float = 0.005) -> float:
        """
        Queries equity snapshots to compute the active peak-to-trough drawdown.
        Dials down risk allocation linearly as drawdown increases to preserve capital.
        """
        try:
            cursor = db_conn.cursor()
            
            # 1. Fetch the latest net worth using your exact schema column names
            cursor.execute("SELECT total_net_worth_usd FROM equity_snapshots ORDER BY snapshot_time DESC LIMIT 1;")
            latest_res = cursor.fetchone()
            
            # 2. Fetch the highest historical net worth ever achieved
            cursor.execute("SELECT MAX(total_net_worth_usd) FROM equity_snapshots;")
            peak_res = cursor.fetchone()
            
            cursor.close()
            
            if not latest_res or not peak_res or not peak_res[0]:
                return base_risk
                
            current_equity = float(latest_res[0])
            peak_equity = float(peak_res[0])
            
            if peak_equity <= 0:
                return base_risk
                
            # 3. Calculate Peak-to-Trough Drawdown Percentage
            drawdown_pct = ((peak_equity - current_equity) / peak_equity) * 100
            
            if drawdown_pct <= 0:
                return base_risk
                
            # 4. THE RISK DIAL: Reduce risk by 0.1% for every 1% of account drawdown
            reduction = (drawdown_pct * 0.1) / 100
            dynamic_risk = base_risk - reduction
            
            # Clamp the output between the absolute floor and the maximum base risk
            final_risk = max(floor_risk, min(base_risk, dynamic_risk))
            
            return final_risk
            
        except Exception as e:
            self.logger.error(f"Error calculating drawdown governor: {e}")
            # 🛡️ Roll back the aborted transaction block to clear the connection lock
            db_conn.rollback()
            return base_risk