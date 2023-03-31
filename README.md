# OMNIK2MQTTPROXY
Based on the scripts build by @jbouwh and furthermore inspired by the work of 
@klaasnicolaas https://github.com/klaasnicolaas/python-omnikinverter
@robbinjansen https://github.com/robbinjanssen/home-assistant-omnik-inverter

Its my first programming in Python so bare with me.

While the previous mentioned people did amazing work on getting the Omnik invertor integrated in Home Assistant, all these versions didnt work out for my Omnik invertor.

This fork of the proxy will use a UDP server to receive update messages from the Omnik Invertor and forwards these, using multiple sensors to MQTT. Using auto discovery the sensors will be available in HA.
Eventually I would like this version to be running in AppDeamon, however so far I wasnt able to get AppDeamon to maintain memory usage, to get required packages installed and to listen to the network address which is available to my invertor (I'm running HAOS in HyperV on a laptiop running windows 10)

## A level 2 heading
`I need to keep this here for my reference as also using GitHub is new to me`

### Command line
```
usage: omnikloggerproxy.py [-h] --serialnumber SERIALNUMBER [SERIALNUMBER ...]
                           [--config FILE  Path to configuration file (ini)]
                           [--loglevel LOGLEVEL]
                           [--listenaddress LISTENADDRESS]
                           [--listenport LISTENPORT]
                           [--omniklogger OMNIKLOGGER]
                           [--omnikloggerport OMNIKLOGGERPORT]
                           [--mqtt_host MQTT_HOST] [--mqtt_port MQTT_PORT]
                           [--mqtt_retain MQTT_RETAIN]
                           [--mqtt_discovery_prefix MQTT_DISCOVERY_PREFIX]
                           [--mqtt_client_name_prefix MQTT_CLIENT_NAME_PREFIX]
                           [--mqtt_username MQTT_USERNAME]
                           [--mqtt_password MQTT_PASSWORD]
                           [--mqtt_device_name MQTT_DEVICE_NAME]
                           [--mqtt_logger_sensor_name MQTT_LOGGER_SENSOR_NAME]
                           [--mqtt_tls MQTT_TLS]
                           [--mqtt_ca_certs MQTT_CA_CERTS]
                           [--mqtt_client_cert MQTT_CLIENT_CERT]
                           [--mqtt_client_key MQTT_CLIENT_KEY]
```

