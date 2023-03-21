#! /usr/bin/env python3
#
# This script can be used to intercept and forward the inverter log messages.
# The script has been tested with python versions 2.7 and 3.8
# The data can be forwarded to MQTT to process using omnikdatalogger with the halogger client.
# To intercept on your local network:
# Route 176.58.117.69/32 to the device that runs this logger and listen at port 10004
# On the device NAT the poblic address to the private address (e.g. 192.168.x.x ) using iptables:
# iptables -t nat -A PREROUTING -p tcp -d 176.58.117.69 --dport 10004 -j DNAT --to-destination 192.168.x.x:10004
# iptables -t nat -A OUTPUT -p tcp -d 176.58.117.69 -j DNAT --to-destination 192.168.x.x
#

import socket
import socketserver
import argparse
import configparser
import struct
import yaml
import threading
import signal
import json
import binascii
import os
import paho.mqtt.client as mqttclient
import uuid
import logging
import datetime
import time

__version__ = '2.0.0'
listenaddress = b'127.0.0.1'                       # Default listenaddress
listenport = 10004                                 # Make sure your firewall enables you listening at this port
# There is no need to change this if this proxy must log your data directly to the Omnik/SolarmanPV servers
omnikloggerpublicaddress = b'176.58.117.69'        # If you have an aditional omniklogger, change the ip to enlarge the chain
omnikloggerdestport = 10004                        # This is the port the omnik/SolarmanPV datalogger server listens to
STATUS_ON = 'ON'
STATUS_OFF = 'OFF'
CHECK_STATUS_INTERVAL   = 60    # we check each 60 seconds if everthing is still ok
INVERTER_MAX_IDLE_TIME  = 10    # after 10 minutes we will send ourself a status off message (and set the power to 0)
ANNOUNCE_INTERVAL       = 60    # minutes between announcing the sensors

global stopflag
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s [%(levelname)s] - %(message)s',
    filename='Omnik2mqtt.log',
    force=True) 
logger = logging.getLogger(__name__)


# Generic signal handler to stop program
def signal_handler(signal, frame):
    global stopflag
    logger.debug("Signal {:0d} received. Setting stopflag.".format(signal))
    stopflag = True

###############################################################################################
# The main class which creates a
# 1. UDP server
# 2. MQTT client
# 3. Timer watchdog which posts status off when nothing is recieved
class ProxyServer(threading.Thread):

    def __init__(self, args=[], kwargs={}):
        threading.Thread.__init__(self)
        
        # creating MQTT client
        if RequestHandler.mqtt_fw == None:
            logger.info('Enabling MQTT forward to {0}:{1}'.format(args.mqtt_host, args.mqtt_port))
            RequestHandler.mqtt_fw = mqtt(args)
        
        RequestHandler.lastupdate = datetime.datetime.now()

        # Create UDP server
        logger.info('Creating the UDP server')
        self.udpserver = socketserver.UDPServer((args.listenaddress, args.listenport), RequestHandler)

        # Create a timer callback for every 60 sec if there is a valid update status
        self.announcetimer = datetime.datetime.now()
        self.statustimer = threading.Timer(CHECK_STATUS_INTERVAL, self.check_status)
        self.statustimer.start()

    # the chack_status loop called each 60 sec
    def check_status(self):
        if RequestHandler.lastupdate + datetime.timedelta(minutes=INVERTER_MAX_IDLE_TIME) < datetime.datetime.now():
            logger.debug("No message send in the past {0} minutes, so the invertor is off".format(INVERTER_MAX_IDLE_TIME))
            RequestHandler.mqtt_fw.status_off()
            RequestHandler.lastupdate = datetime.datetime.now() # set last update to prevent burst of OFF messages
        
        # every now and then we register the sensors again
        if self.announcetimer + datetime.timedelta(minutes=ANNOUNCE_INTERVAL) < datetime.datetime.now():
            logger.debug("We past another {0} minutes, its time to announce the sensors".format(ANNOUNCE_INTERVAL))
            RequestHandler.mqtt_fw.announce()
            self.announcetimer = datetime.datetime.now()

        # Restart the timer
        logger.debug("We checked all internal processes and go back to sleep for {0} seconds".format(CHECK_STATUS_INTERVAL))
        self.statustimer = threading.Timer(CHECK_STATUS_INTERVAL, self.check_status)
        self.statustimer.start()

    def cancel(self):
        # Stop the loop
        self.udpserver.shutdown()
        self.statustimer.cancel()
        RequestHandler.mqtt_fw.close()

    def run(self):
        # Try to run UDP server
        logger.info('Start Omnik proxy server. Listening to {0}:{1}'.format(args.listenaddress, args.listenport))
        self.udpserver.serve_forever()

###############################################################################################
# class to handle UDP packages
class RequestHandler(socketserver.BaseRequestHandler):

    mqtt_fw     = None
    lastupdate  = None

    def handle(self):
        #msg = self.request.recv(1024)
        msg = self.request[0]
        logger.debug("Message received from client {0}".format(self.client_address[0]))
        logger.debug("Raw message {0}".format(binascii.hexlify(msg, ' ')))

        if len(msg) >= 99:
            # if the package is more than 99 bytes, get the serial number form the inverter
            rawserial = str(msg[15:31].decode())
            logger.info("Processing message for inverter '{0}'".format(rawserial))
            self.lastupdate = datetime.datetime.now()
            # Forward logger message to MTTQ if host is defined
            if self.mqtt_fw:
                self.mqtt_fw.update(msg, rawserial)

        elif len(msg >= 26):
            ## Using UDP we get a second message with \x68\x11\x41\xF0 2x[\xD5\x1F\x19\x24] 'DATA SEND IS OK\r\n' CRC \x16
            confirmation = str(msg[12:26].decode())
            if confirmation in "DATA SEND IS OK":
                # Status is still ok, holding of the watchdog
                logger.info("Confirmation message received")
                self.lastupdate = datetime.datetime.now()
        else:
            logger.warning("Ignore unrecognized message")


###############################################################################################
# MQTT class
class mqtt(object):
    
    # constructor
    def __init__(self, args=[], kwargs={}):
        self.mqtt_client_name = args.mqtt_client_name_prefix + uuid.uuid4().hex
        self.mqtt_host = args.mqtt_host
        self.mqtt_port = int(args.mqtt_port)
        self.mqtt_retain = args.mqtt_retain
        self.tls = args.mqtt_tls
        self.ca_certs = args.mqtt_ca_certs
        self.client_cert = args.mqtt_client_cert
        self.client_key = args.mqtt_client_key

        if not args.mqtt_username or not args.mqtt_password:
            logger.error("Please specify MQTT username and password in the configuration")
            self.mqtt_client = None
            return
        else:
            self.mqtt_username = args.mqtt_username
            self.mqtt_password = args.mqtt_password

        # mqtt setup
        self.mqtt_client = mqttclient.Client(self.mqtt_client_name)
        self.mqtt_client.on_connect = self._mqtt_on_connect  # bind call back function
        self.mqtt_client.on_disconnect = self._mqtt_on_disconnect  # bind call back function
        # self.mqtt_client.on_message=mqtt_on_message (not used)
        self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
        # TLS support
        if self.tls:
            self.mqtt_client.tls_set(
                ca_certs=self.ca_certs or None,
                certfile=self.client_cert or None,
                keyfile=self.client_key or None,
            )

        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port)
        # start processing messages
        self.mqtt_client.loop_start()
        # default prefixes
        self.discovery_prefix = args.mqtt_discovery_prefix
        self.device_name = args.mqtt_device_name
        self.logger_sensor_name = args.mqtt_logger_sensor_name
        self.serial = args.serialnumber

        # a dict with all the topics we will be using
        self.topics = {}
        announce    = "{0}/sensor/{1}_{2}".format(self.discovery_prefix, self.logger_sensor_name, self.serial)
        update      = "aha/{0}".format(self.serial)
        
        self.topics['logger'] = {}
        self.topics['logger']['config']    = "{0}/logger/config".format(announce)
        self.topics['logger']['state']     = "{0}/logger/state".format(update)
        self.topics['logger']['attr']      = "{0}/logger/attr".format(update)

        self.topics['power'] = {}
        self.topics['power']['config']     = "{0}/power/config".format(announce)
        self.topics['power']['state']      = "{0}/power/state".format(update)
        self.topics['power']['attr']       = "{0}/power/attr".format(update)

        self.topics['E-today'] = {}
        self.topics['E-today']['config']   = "{0}/E-today/config".format(announce)
        self.topics['E-today']['state']    = "{0}/E-today/state".format(update)
        self.topics['E-today']['attr']     = "{0}/E-today/attr".format(update)

        self.topics['E-total'] = {}
        self.topics['E-total']['config']   = "{0}/E-total/config".format(announce)
        self.topics['E-total']['state']    = "{0}/E-total/state".format(update)
        self.topics['E-total']['attr']     = "{0}/E-total/attr".format(update)

        # lock
        self.lock = threading.Condition(threading.Lock())

    def close(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.disconnect()
            except Exception:
                pass

    def _sensors_payload(self):
        # Device payload is generic for all sensors
        device = {
            "identifiers": ["{0}_{1}".format(self.device_name, self.serial)],
            "name": "{0}_{1}".format(self.device_name, self.serial),
            "mdl": "Omnik datalogger proxy",
            "mf": 'InnoVeer',
            "sw": __version__
            }
        
        # Fill dict with sensors
        sensors = {}
        # The logger with state and (the raw mnessage) as attributes
        sensors['logger'] = {
            "uniq_id": "Logger_{0}".format(self.serial),
            "name": "Omnik-Logger",
            "stat_t": "{0}".format(self.topics['logger']['state']),
            "json_attr_t": "{0}".format(self.topics['logger']['attr']),
            "dev_cla": "enum",
            "val_tpl": "{{ value_json.state }}",
            "dev": device
            }
        # current_power
        sensors['power'] = {
            "uniq_id": "Power_{0}".format(self.serial),
            "name": "Omnik-Power",
            "stat_t": "{0}".format(self.topics['power']['state']),
            "dev_cla": "power",
            "state_class": "measurement",
            "unit_of_measurement": "W",
            "dev": device
            }
        # total power of today
        sensors['E-today'] = {
            "uniq_id": "EToday_{0}".format(self.serial),
            "name": "Omnik-Energy-Today",
            "stat_t": "{0}".format(self.topics['E-today']['state']),
            "dev_cla": "energy",
            "unit_of_measurement": "kWh",
            "state_class": "total",
            "dev": device
            }
        # total power life time
        sensors['E-total'] = {
            "uniq_id": "ETotal_{0}".format(self.serial),
            "name": "Omnik-Energy-Total",
            "stat_t": "{0}".format(self.topics['E-total']['state']),
            "dev_cla": "energy",
            "state_class": "total_increasing",
            "unit_of_measurement": "kWh",
            "dev": device
            }
        return sensors

    # Invertor specific parsing -> needs replacement as this is not MQTT related
    def __getShort(self, begin, divider=10):
        num = struct.unpack("!H", self.data[begin : begin + 2])[0]
        if num == 65535:
            return -1
        else:
            return float(num) / divider

    def __getLong(self, begin, divider=10):
        return float(struct.unpack("!I", self.data[begin : begin + 4])[0]) / divider

    def getPower(self):
        return int(self.__getShort(59, 1))
    
    def getETotal(self):
        return self.__getLong(71)

    def getEToday(self):
        return self.__getShort(69, 100)  # Devide by 100

    def getTemp(self):
        return self.__getShort(31)

    # set sensor values
    def _value_payload(self, status):
        value_pl = {}
        value_pl['logger'] = {"state": status}
        if status == STATUS_ON:
            value_pl['power'] = self.getPower()
            value_pl['E-today'] = self.getEToday()
            value_pl['E-total'] = self.getETotal()
        else:
            value_pl['power'] = 0

        return value_pl

    # set the attribute of the logger binary sensor
    def _attribute_payload(self):
        reporttime = datetime.datetime.now()
        attr_pl = {}
        attr_pl['logger'] = {
            "inverter": self.serial,
            "data": json.dumps(str(binascii.b2a_base64(self.data), encoding='ascii')),
            "current_power": self.getPower(),
            "today_energy": self.getEToday(),
            "total_energy": self.getETotal(),
            "inverter_temperature": self.getTemp(),
            "timestamp": time.time(),
            "last_update": "{0} {1}".format(reporttime.strftime('%Y-%m-%d'), reporttime.strftime('%H:%M:%S'))
            }
        return attr_pl

    # publish the message to the topic
    def _publish(self, sensor, item, payload):
        try:
            if self.mqtt_client.publish(self.topics[sensor][item], json.dumps(payload[sensor]), retain=self.mqtt_retain):
                logger.debug("Publishing {0} for sensor {1} successful.".format(item, sensor))
                return True
            else:
                logger.warning("Publishing {0} for sensor {1} failed!".format(item, sensor))
                return False
        except Exception as e:
            logger.error("Unhandled error publishing {0} for sensor {1}: {2}".format(item, sensor, e))
            return False

    # its been awhile since we heart something from the invertor, so we think its of
    def status_off(self):
        self.lock.acquire()
        logger.debug('Sending STATUS_OFF to MQTT service at "{0}"'.format(args.mqtt_host))

        # publish state
        value_pl = self._value_payload(STATUS_OFF)
        for sensor in value_pl:
            self._publish(sensor, 'state', value_pl)

        self.lock.release()

    # update
    def update(self, data, serial):
        # Decode data: base64.b64decode(json.loads(d, encoding='UTF-8'))
        self.lock.acquire()
        logger.debug('Sending STATUS_ON to MQTT service at "{0}"'.format(args.mqtt_host))

        self.data = data
        self.serial = serial

        # publish state
        value_pl = self._value_payload(STATUS_ON)
        for sensor in value_pl:
            self._publish(sensor, 'state', value_pl)

        # publish attributes
        attr_pl = self._attribute_payload()
        for sensor in attr_pl:
            self._publish(sensor, 'attr', attr_pl)

        self.lock.release()

    # register/announce the device & sensors
    def announce(self):
        # publish sensors
        self.lock.acquire()

        payload = self._sensors_payload()
        for sensor in payload:
            self._publish(sensor, 'config', payload)

        self.lock.release()

    # when connected announce the sensors
    def _mqtt_on_connect(self, client, userdata, flags, rc=0):
        if rc == 0:
            logger.info("MQTT connected")
            self.announce()
            # subscribe listening (not used)

    #disconnect
    def _mqtt_on_disconnect(self, client, userdata, flags, rc=0):
        if rc == 0:
            logger.info("MQTT disconnected")

# endof class mqtt

###############################################################################################
# main
def main(args):
    global stopflag
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    proxy = ProxyServer(args)
    proxy.start()
    try:
        while not stopflag and proxy.is_alive():
            proxy.join(1)
    except KeyboardInterrupt:
        pass
    proxy.cancel()
    logger.info("Stopping threads...")
    proxy.join()

# bootstrap
if __name__ == '__main__':
    stopflag = False
    home = os.path.expanduser('~')

    parser = argparse.ArgumentParser()
    parser.add_argument('--section', default=None,
                        help='Section to .yaml configuration file to use. Defaults to the first section found.')
    parser.add_argument('--config', default=os.path.join(home, '.omnik/config.ini'),
                        help='Path to configuration file (ini) (DECREPATED!)', metavar="FILE")
    parser.add_argument('--serialnumber', default=None, nargs='+',
                        help='The serial number(s) of your inverter (required)')
    parser.add_argument('--loglevel', default='INFO',
                        help='The basic loglevel [DEBUG, INFO, WARNING, ERROR, CRITICAL]')
    parser.add_argument('--listenaddress', default=listenaddress,
                        help='A local available address to listen to')
    parser.add_argument('--listenport', default=listenport, type=int,
                        help='The local port to listen to')
    parser.add_argument('--omniklogger', default=None,
                        help='Forward to an address omnik/SolarmanPV datalogger server listens to. '
                             'Set this to {0} as final forwarder.'.format(omnikloggerpublicaddress))
    parser.add_argument('--omnikloggerport', default=omnikloggerdestport, type=int,
                        help='The port the omnik/SolarmanPV datalogger server listens to')
    parser.add_argument('--mqtt_host', default='',
                        help='The mqtt host to forward processed data to. Config overrides.')
    parser.add_argument('--mqtt_port', default=1883, type=int,
                        help='The mqtt server port. Config overrides.')
    parser.add_argument('--mqtt_retain', default=True, type=bool,
                        help='The mqtt data message retains. Config overrides.')
    parser.add_argument('--mqtt_discovery_prefix', default='homeassistant',
                        help='The mqtt topic prefix (used for MQTT auto discovery). Config overrides.')
    parser.add_argument('--mqtt_client_name_prefix', default='ha-mqtt-omnikloggerproxy',
                        help='The port the omnik/SolarmanPV datalogger server listens to. Config overrides.')
    parser.add_argument('--mqtt_username', default=None,
                        help='The mqtt username. Config overrides.')
    parser.add_argument('--mqtt_password', default=None,
                        help='The mqtt password. Config overrides.')
    parser.add_argument('--mqtt_device_name', default='Datalogger proxy',
                        help='The device name that apears using mqtt autodiscovery (HA). Config overrides.')
    parser.add_argument('--mqtt_logger_sensor_name', default='Datalogger',
                        help='The name of data sensor using mqtt autodiscovery (HA). Config overrides.')
    parser.add_argument('--mqtt_tls', default=False, type=bool, help='Secures the connection to the MQTT service, the MQTT server side needs a valid certificate.')
    parser.add_argument('--mqtt_ca_certs', default=None, help="File path to a file containing alternative CA's. If not configure the systems default CA is used.")
    parser.add_argument('--mqtt_client_cert', default=None, help='File path to a file containing a PEM encoded client certificate.')
    parser.add_argument('--mqtt_client_key', default=None, help='File path to a file containing a PEM encoded client private key.')
    args = parser.parse_args()

    FORMAT = '%(module)s: %(message)s'
    loglevel = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
        }

    if os.path.isfile(args.config):
        c = configparser.ConfigParser(converters={'list': lambda x: [i.strip() for i in x.split(',')]})
        c.read([args.config], encoding='utf-8')
        args.mqtt_host = c.get('output.mqtt', 'host', fallback=args.mqtt_host)
        args.mqtt_port = c.getint('output.mqtt', 'port', fallback=args.mqtt_port)
        args.mqtt_retain = True if c.get('output.mqtt', 'retain', fallback='true') == 'true' else args.mqtt_retain
        args.mqtt_discovery_prefix = c.get('output.mqtt', 'discovery_prefix ', fallback=args.mqtt_discovery_prefix)
        args.mqtt_client_name_prefix = c.get('output.mqtt', 'client_name_prefix', fallback=args.mqtt_client_name_prefix)
        args.mqtt_username = c.get('output.mqtt', 'username', fallback=args.mqtt_username)
        args.mqtt_password = c.get('output.mqtt', 'password', fallback=args.mqtt_password)
        args.mqtt_device_name = c.get('output.mqtt', 'device_name', fallback=args.mqtt_device_name)
        args.logger_sensor_name = c.get('output.mqtt', 'logger_sensor_name', fallback=args.mqtt_logger_sensor_name)

        args.mqtt_tls = c.get('output.mqtt', 'tls', fallback=args.mqtt_tls)
        args.mqtt_ca_certs = c.get('output.mqtt', 'ca_certs', fallback=args.mqtt_ca_certs)
        args.mqtt_client_cert = c.get('output.mqtt', 'client_cert', fallback=args.mqtt_client_cert)
        args.mqtt_client_key = c.get('output.mqtt', 'client_key', fallback=args.mqtt_client_key)

        args.serialnumber = c.get('proxy', 'serialnumber', fallback=args.serialnumber)
        args.loglevel = c.get('proxy', 'loglevel', fallback=args.loglevel)
        args.listenaddress = c.get('proxy', 'listenaddress', fallback=args.listenaddress)
        args.listenport = c.getint('proxy', 'listenport', fallback=args.listenport)
        args.omniklogger = c.get('proxy', 'omniklogger', fallback=args.omniklogger)
        args.omnikloggerport = c.getint('proxy', 'omnikloggerport', fallback=args.omnikloggerport)
    if not args.serialnumber:
        parser.print_help()
        os.sys.exit(1)
    logging.basicConfig(level=loglevel[args.loglevel], format=FORMAT)
    main(args)

###############################################################################################
###############################################################################################
