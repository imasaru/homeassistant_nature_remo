DOMAIN = "nature_remo"

# Local API options
# Per Remo device local host is stored under the HA device registry id (existing
# "IP Address" option); these keys are per appliance / per Remo device id.
OPT_LOCAL_PROTOCOL = "local_protocol_{appliance_id}"
OPT_LOCAL_POLL = "local_poll_{device_id}"
LOCAL_PROTOCOL_NONE = "none"
LOCAL_PROTOCOL_FUJITSU_ARRFF2J = "fujitsu_arrff2j"
LOCAL_PROTOCOLS = [LOCAL_PROTOCOL_NONE, LOCAL_PROTOCOL_FUJITSU_ARRFF2J]

LOCAL_POLL_INTERVAL = 2  # seconds
