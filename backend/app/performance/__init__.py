"""Historical portfolio performance: value series, returns and risk statistics.

Reads stored holdings and stored end-of-day closes only. Nothing is interpolated, carried
forward or substituted; sessions without a complete set of prices are reported as missing
rather than valued.
"""
