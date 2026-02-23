"""Constants for Cloudflare."""

DOMAIN = "cloudflare"

# Config
CONF_RECORDS = "records"
CONF_IP_VERSION = "ip_version"

# IP Version options
IP_VERSION_AUTO = "auto"
IP_VERSION_IPV4 = "ipv4"
IP_VERSION_IPV6 = "ipv6"
IP_VERSION_BOTH = "both"

# Defaults
DEFAULT_UPDATE_INTERVAL = 60  # in minutes
DEFAULT_IP_VERSION = IP_VERSION_AUTO

# Services
SERVICE_UPDATE_RECORDS = "update_records"
