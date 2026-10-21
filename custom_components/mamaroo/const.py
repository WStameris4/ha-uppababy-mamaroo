"""Constants for the UPPAbaby Mamaroo integration."""

DOMAIN = "mamaroo"

# Advertised and GATT identifiers, from the UPPAbaby Connect app 1.0.2.
SERVICE_UUID = "622d0100-2416-0fa7-e132-2f1495cc2ce0"
CHAR_UUID = "622d0101-2416-0fa7-e132-2f1495cc2ce0"

CONF_PAIRING_ID = "pairing_id"
CONF_BLUETOOTH_ID = "bluetooth_id"
# The address pairing used: a hint only, since one changes at every power-up.
CONF_ADDRESS = "address"

SERVICE_SEND_COMMAND = "send_command"
SERVICE_BOND = "bond"
