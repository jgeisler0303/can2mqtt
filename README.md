# Invocation
Run `./can2mqtt.py -h` to see a list of command line parameters.
Default is to read configuration from local directory from file `config.json` and log to stdout with level INFO.

# Configuaration
Connection to CAN bus is configured in `canbus` section of json config file.
Connection to MQTT broker is configured in `mqtt` section.
Translation of CAN messages to MQTT is configured in `receivers` section.
Translation of MQTT messages to CAN is configured in `transmitters` section.

## CAN parameters
Connection to CAN bus is made using [python-can package](http://python-can.readthedocs.io/en/latest/index.html).
See documentation on available interfaces [here](http://python-can.readthedocs.io/en/latest/interfaces.html).

## MQTT parameters
Cennection to MQTT broker is made using [paho-mqtt package](https://pypi.python.org/pypi/paho-mqtt).
You may set `client_id` (default is `can2mqtt`), `host` (default is `127.0.0.1`) and `port` (default is `1883`).

## Packing and Unpacking of CAN message
CAN messages are packed and unpacked using [bitstruct package](http://bitstruct.readthedocs.io/en/latest/#).
See [here](http://bitstruct.readthedocs.io/en/latest/#bitstruct.pack) for valid syntax of `pack_template` of transmitter resp. `unpack_template` of receiver.
Each value from the template is later referenced by a variable name given in `var_names`.

## Formating of topic and payload string
Multiple topic and payload strings can be formed and sent to the broker from one CAN message via one or more receiver.
`topic_template` and `payload_template` may be strings or arrays of strings. Each string is formated using [Format Specification Mini-Language](https://docs.python.org/2/library/string.html#format-specification-mini-language).
Each replacement field has to explicitly reference a variable name from `var_names`.
Additionally to the variable names defined in `var_names`, `topic_template` and `payload_template` may reference the timestamp and CAN id of the received message by the names `canid`resp. `t`.

## Parsing of incoming MQTT messages
Each transmitter handles MQTT messages received due to its `subscriptions`.
Received topics and payloads are parsed using [parse package](https://pypi.python.org/pypi/parse).
Again explicit field names have to be used.
`var_names` gives the order of the parsed named values to be used to pack the CAN message using the `pack_template`.
The CAN id is either a decimal integer, a hex formatted integer string or a single variable name from the set of parsed named values.

## Transforming values
Unpacked and parsed values named by variable names in the `var_names` parameter may be transformed using a python function defined in the `can2mqtt_vias.py` module.
Each such function must expect one scalar parameter and return one scalar parameter.
To use a translation the variable name in `var_names` has to be followed by th key word "via" and then the name of the transformation function.

# Logging
For logging [python logging](https://docs.python.org/2/library/logging.html) is used.

# CANopen
The special section `canopen` allows to configure the bridge to send some [CANopen](https://en.wikipedia.org/wiki/CANopen) specific messages.
If `sync_interval` is specified a sync message is sent every interval seconds. If `sync_count` is specified the sync message has one data byte that cyclicly counts from 0 to the given count.
If `auto_start` is true the program listens to CANopen NMT bootup and heartbeat messages and sends a start command to every node that indicates it is not in operational mode.
