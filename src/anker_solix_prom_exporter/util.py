import logging
import getpass
import os

# create logger
CONSOLE: logging.Logger = logging.getLogger(__name__)
# Set parent to lowest level to allow messages passed to all handlers using their own level
CONSOLE.setLevel(logging.DEBUG)

# create console handler and set level to info
ch = logging.StreamHandler()
# This can be changed to DEBUG if more messages should be printed to console
if os.environ.get("ANKER_EXPORTER_DEBUG") == "1":
    ch.setLevel(logging.DEBUG)
else:
    ch.setLevel(logging.INFO)
CONSOLE.addHandler(ch)

_CREDENTIALS = {
    "USER": os.getenv("ANKERUSER"),
    "PASSWORD": os.getenv("ANKERPASSWORD"),
    "COUNTRY": os.getenv("ANKERCOUNTRY"),
}


def user() -> str:
    """Get anker account user."""
    if usr := _CREDENTIALS.get("USER"):
        return str(usr)
    CONSOLE.info("\nEnter Anker Account credentials:")
    username = input("Username (email): ")
    while not username:
        username = input("Username (email): ")
    return username


def password() -> str:
    """Get anker account password."""
    if pwd := _CREDENTIALS.get("PASSWORD"):
        return str(pwd)
    pwd = getpass.getpass("Password: ")
    while not pwd:
        pwd = getpass.getpass("Password: ")
    return pwd


def country() -> str:
    """Get anker account country."""
    if ctry := _CREDENTIALS.get("COUNTRY"):
        return str(ctry)
    countrycode = input("Country ID (e.g. DE): ")
    while not countrycode:
        countrycode = input("Country ID (e.g. DE): ")
    return countrycode
