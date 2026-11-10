
from nautilus_trader.trading import Strategy


class RBStrategy(Strategy):
    """Initial strategy skeleton for the new trading system."""

    def on_start(self):
        print("RB Strategy started successfully")


print("SUCCESS: RBStrategy class defined")
