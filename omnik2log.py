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
import Omnik
import socket

__version__ = '2.0.0'
listenaddress = b'127.0.0.1'                       # Default listenaddress
listenport = 10004                                 # Make sure your firewall enables you listening at this port
# There is no need to change this if this proxy must log your data directly to the Omnik/SolarmanPV servers
omnikloggerpublicaddress = b'176.58.117.69'        # If you have an aditional omniklogger, change the ip to enlarge the chain
omnikloggerdestport = 10004                        # This is the port the omnik/SolarmanPV datalogger server listens to
STATUS_ON = 'ON'
STATUS_OFF = 'OFF'
CHECK_STATUS_INTERVAL   = 60    # we check each 60 seconds if everthing is still ok
INVERTER_MAX_IDLE_TIME  = 10    # after 10 minutes we will send a status off message
ANNOUNCE_INTERVAL       = 60    # minutes between announcing the sensors

global stopflag
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s [%(levelname)s] - %(message)s',
    filename='Omnik2log.log',
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
        TCPHandler.lastupdate = datetime.datetime.now()

        # Create UDP server
        logger.info('Creating the TCP server')
        self.tcpserver = socketserver.TCPServer((args.listenaddress, args.listenport), TCPHandler)

        # Create a timer callback for every 60 sec if there is a valid update status
        self.announcetimer = datetime.datetime.now()
        self.statustimer = threading.Timer(CHECK_STATUS_INTERVAL, self.check_status)
        self.statustimer.start()

    # the chack_status loop called each 60 sec
    def check_status(self):
        # Restart the timer
        logger.debug("We checked all internal processes and go back to sleep for {0} seconds".format(CHECK_STATUS_INTERVAL))
        self.statustimer = threading.Timer(CHECK_STATUS_INTERVAL, self.check_status)
        self.statustimer.start()

    def cancel(self):
        # Stop the loop
        self.tcpserver.shutdown()
        self.statustimer.cancel()

    def run(self):
        # Try to run TCP server
        logger.info('Start Omnik proxy server. Listening to {0}:{1}'.format(args.listenaddress, args.listenport))
        self.tcpserver.serve_forever()

###############################################################################################
# class to handle UDP packages
class TCPHandler(socketserver.BaseRequestHandler):

    lastupdate  = None

    def handle(self):
        msg = self.request.recv(1024)
        #msg = self.request[0]
        logger.debug("Message received from client {0}".format(self.client_address[0]))
        logger.debug("Raw message {0}".format(binascii.hexlify(msg, ' ')))
        self.request.close()

        omnikParser = Omnik.Response()
        logger.debug("Decoding Omnik message: '{0}'".format(omnikParser.decode(msg)))

        if omnikParser.isInverterStatus():
            TCPHandler.lastupdate = datetime.datetime.now()
            # if the package is more than 99 bytes, get the serial number form the inverter
            logger.info("Processing message from logger '{0}' for inverter '{1}'".format(omnikParser.getLoggerId(), omnikParser.getInverterId()))
            # Log basics 
            logger.info("Power {0}, E-today {1}, E-total {2}".format(omnikParser.getPower(), omnikParser.getEToday(), omnikParser.getETotal()))
            # Log all
            logger.debug("{0}".format(omnikParser.getJSON()))
            
        elif omnikParser.isConfirmation():
            ## Using UDP we get a second message with \x68\x11\x41\xF0 2x[\xD5\x1F\x19\x24] 'DATA SEND IS OK\r\n' CRC \x16
            logger.info("Confirmation message received: {0}".format(omnikParser.getValues["UDP_ack"]))
            TCPHandler.lastupdate = datetime.datetime.now()
        else:
            logger.warning("Ignore unrecognized message")

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
