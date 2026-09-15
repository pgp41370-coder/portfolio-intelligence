"""Default NSE equity-segment trading calendar, used by the price-freshness rules.

Sources (checked 15 Sep 2026):

* NSE, "Holidays for the calendar year 2026 - Equities":
  https://www.nseindia.com/resources/exchange-communication-holidays
* NSE circular CMTR72349, "Live Trading Session on February 01, 2026":
  https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf

Only data lives here. When NSE publishes a new year's list, add its dates below (or set
``NSE_TRADING_HOLIDAYS`` / ``NSE_SPECIAL_TRADING_SESSIONS``); the freshness logic in
``calendar.py`` does not change.
"""

from datetime import date

# Weekday trading holidays. Holidays that fall on a Saturday or Sunday need no entry.
NSE_TRADING_HOLIDAYS: dict[date, str] = {
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
