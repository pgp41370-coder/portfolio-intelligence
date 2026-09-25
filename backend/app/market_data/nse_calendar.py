"""Default NSE equity-segment trading calendar, used by the price-freshness rules.

Sources:

* NSE, "Holidays for the calendar year 2026 - Equities" (re-checked 24 Sep 2026, and it still
  matches every 2026 entry below): https://www.nseindia.com/resources/exchange-communication-holidays
* NSE circular CMTR72349, "Live Trading Session on February 01, 2026":
  https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf
* The 2025 entries are corroborated by the provider's own price history: across the five NSE
  securities synced into the development database, no security has a close on any of them,
  while every other weekday in 15 Sep 2025 - 15 Sep 2026 has one.

NSE's holiday page publishes the current calendar year only. It offered no 2025 archive and no
2027 list when this was written, which is why ``CALENDAR_COMPLETE_FROM`` / ``_TO`` exist: the
application states the range its calendar is known to be complete for instead of assuming that
every weekday outside that range is a trading session.

Only data lives here. When NSE publishes a new year's list, add its dates below and extend the
completeness range (or set ``NSE_TRADING_HOLIDAYS`` / ``NSE_SPECIAL_TRADING_SESSIONS``); the
logic in ``calendar.py`` does not change.
"""

from datetime import date

# The window over which the lists below are known to be complete. Before 15 Sep 2025 there is
# neither a published list nor price evidence, so holidays there may be missing; after
# 31 Dec 2026 NSE has not published a list at all.
CALENDAR_COMPLETE_FROM = date(2025, 9, 15)
CALENDAR_COMPLETE_TO = date(2026, 12, 31)

# Weekday trading holidays. Holidays that fall on a Saturday or Sunday need no entry.
NSE_TRADING_HOLIDAYS: dict[date, str] = {
    # 2025 (see the sourcing note above).
    date(2025, 10, 2): "Mahatma Gandhi Jayanti / Dussehra",
    date(2025, 10, 22): "Diwali-Balipratipada",
    date(2025, 11, 5): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2025, 12, 25): "Christmas",
    # 2026.
    date(2026, 1, 15): "Municipal Corporation Election - Maharashtra",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali-Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
}

# Exchange-declared sessions on days that are normally closed, held at normal market hours.
# Muhurat Trading on Sunday 8 Nov 2026 is deliberately not listed: it is a short evening
# session whose timings NSE had not notified, and the 18:00 IST availability rule would not
# fit it. Without an entry its bar is ignored and the next regular session is used.
NSE_SPECIAL_TRADING_SESSIONS: dict[date, str] = {
    date(2026, 2, 1): "Union Budget live trading session (Sunday)",
}
