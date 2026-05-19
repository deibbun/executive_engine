from decimal import Decimal, ROUND_DOWN
import logging

class FundingManager:
    def __init__(self, min_trade_threshold=Decimal("10.00")):
        self.min_threshold = min_trade_threshold
        self.logger = logging.getLogger("ExecutiveEngine.Funding")
        
        # 📊 STRATEGY ALLOCATION WEIGHTS (Flat 100% Target Model)
        self.weights = {
            'master': Decimal('0.30'),
            'btc_pure': Decimal('0.30'),
            'eth_pure': Decimal('0.20'),
            'sol_pure': Decimal('0.20')
        }

    def get_strategy_pool(self, global_cash, total_global_reserved, strategy_id):
        """
        Calculates the spendable USD allocated to a specific strategy.
        Global Liquid Pool = Global Cash - Sum of all reserved funds across all bots
        Strategy Pool = Global Liquid Pool * Strategy Weight
        """
        global_liquid_pool = global_cash - total_global_reserved
        global_liquid_pool = max(global_liquid_pool, Decimal("0.00"))
        
        weight = self.weights.get(strategy_id, Decimal("0.00"))
        return (global_liquid_pool * weight).quantize(Decimal("0.01"))

    def determine_division_factor(self, bots_ready_to_trade):
        """
        Implements the 1, 2, 3 division rule for multi-asset strategies.
        """
        count = len(bots_ready_to_trade)
        if count == 0:
            return 0
        return min(count, 3)

    def allocate(self, global_cash, total_global_reserved, active_signals, strategy_id='master'):
        """
        The strategy-aware core allocation logic:
        1. Calculates the specific liquid pool slice for the given strategy.
        2. Filters signals relevant to the specific running strategy.
        3. Applies the 1, 2, 3 division rule for 'master', or 100% allocation for pure bots.
        4. Enforces the $10 floor.
        """
        strategy_pool = self.get_strategy_pool(global_cash, total_global_reserved, strategy_id)
        
        # Determine which symbols this specific bot instance is allowed to look at
        if strategy_id == 'btc_pure':
            relevant_symbols = ['BTC/USD']
        elif strategy_id == 'eth_pure':
            relevant_symbols = ['ETH/USD']
        elif strategy_id == 'sol_pure':
            relevant_symbols = ['SOL/USD']
        else:
            # The 'master' bot handles all target symbols
            relevant_symbols = list(active_signals.keys())
        
        # Only allocate to bots that are permitted by this strategy AND are signaling HUNTING
        ready_bots = [
            symbol for symbol in relevant_symbols 
            if symbol in active_signals and active_signals[symbol]['is_hunting']
        ]
        
        # Initialize flat blank allocations for all symbols
        allocations = {symbol: Decimal("0.00") for symbol in active_signals.keys()}
        
        if not ready_bots:
            return allocations
        
        # Determine the division factor based on the strategy type
        if strategy_id == 'master':
            divisor = self.determine_division_factor(ready_bots)
        else:
            # Pure single-asset bots deploy their entire strategy slice directly into their asset
            divisor = 1
        
        if divisor == 0:
            return allocations

        # Calculate share per asset within this strategy's budget
        raw_share = strategy_pool / Decimal(str(divisor))
        final_share = raw_share.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        for symbol in ready_bots:
            if final_share >= self.min_threshold:
                allocations[symbol] = final_share
                
        return allocations
        
    def calculate_drawdown_governor(self, db_conn, strategy_id: str = 'master', base_risk: float = 0.02, floor_risk: float = 0.005) -> float:
        """
        Queries equity snapshots to compute the active peak-to-trough drawdown ISOLATED by strategy.
        Dials down risk allocation linearly as drawdown increases to preserve capital.
        """
        try:
            cursor = db_conn.cursor()
            
            # 1. Fetch the latest net worth for THIS specific strategy
            cursor.execute("""
                SELECT total_net_worth_usd FROM equity_snapshots 
                WHERE strategy_id = %s 
                ORDER BY snapshot_time DESC LIMIT 1;
            """, (strategy_id,))
            latest_res = cursor.fetchone()
            
            # 2. Fetch the highest historical net worth ever achieved by THIS specific strategy
            cursor.execute("""
                SELECT MAX(total_net_worth_usd) FROM equity_snapshots 
                WHERE strategy_id = %s;
            """, (strategy_id,))
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
            self.logger.error(f"Error calculating drawdown governor for '{strategy_id}': {e}")
            db_conn.rollback()
            return base_risk