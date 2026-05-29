from vnstock.ui import Market

def __main__():
    market = Market()
    print(market.equity("FPT").ohlcv(start="2025-01-01", end="2025-01-02"))
    
if __name__ == '__main__':    
    __main__()
