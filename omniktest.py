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

# There is no need to change this if this proxy must log your data directly to the Omnik/SolarmanPV servers
omnikloggerpublicaddress = b'176.58.117.69'        # If you have an aditional omniklogger, change the ip to enlarge the chain
omnikloggerdestport = 10004                        # This is the port the omnik/SolarmanPV datalogger server listens to

###############################################################################################
#
#
# the chack_status loop called each 60 sec

def main():
    msg = b'\x68\x55\x41\xb0\x8b\xe8\xdc\x23\x8b\xe8\xdc\x23\x81\x02\x01\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x01\x3d\x08\x9e\x00\x00\xff\xff\x00\x0b\x00\xb4\xff\xff\x00\x08\xff\xff\xff\xff\x09\x2d\xff\xff\xff\xff\x13\x8a\x00\xd1\xff\xff\xff\xff\xff\xff\xff\xff\x03\x30\x00\x00\x00\x51\x00\x00\x00\x0a\x00\x01\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x76\x16\x68\x0f\x41\xf0\x8b\xe8\xdc\x23\x8b\xe8\xdc\x23\x44\x41\x54\x41\x20\x53\x45\x4e\x44\x20\x49\x53\x20\x4f\x4b\xfe\x16'
#    msg = b'\x68\x7d\x41\xb0\x5d\x1f\x19\x24\x5d\x1f\x19\x24\x81\x02\x01\x4e\x4c\x44\x4e\x31\x35\x32\x30\x31\x33\x38\x43\x31\x30\x30\x31\x01\x5c\x07\x68\x00\x00\xff\xff\x00\x03\x00\xb4\xff\xff\x00\x02\xff\xff\xff\xff\x09\x28\xff\xff\xff\xff\x13\x89\x00\x37\xff\xff\xff\xff\xff\xff\xff\xff\x00\xdd\x00\x01\x7b\xf7\x00\x00\x9b\x10\x00\x01\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x4e\x4c\x31\x2d\x56\x31\x2e\x30\x2d\x30\x30\x34\x33\x2d\x34\x00\x00\x00\x00\x00\x56\x31\x2e\x36\x2d\x30\x30\x31\x38\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x7b\x16'

    omnik = Omnik.Response()
    print(omnik.decode(msg))


    print(omnik.getRawMsg())
    print(omnik.getPayload())
    print(omnik.getValues())

    print(omnik.getJSON())

    print(omnik.getLoggerId())
    print(omnik.getInverterId())
    print(omnik.getMasterVersion())
    print(omnik.getSlaveVersion())
    print(omnik.getTemp())
    print(omnik.getPower())
    print(omnik.getEToday())
    print(omnik.getETotal())
    print(omnik.getPower())
    print(omnik.getFrequency())
    print(omnik.getCurrent())
    print(omnik.getVoltage())
    print("------")
    print("Creating a request string")

    request = Omnik.Request().encode(605626205) #605202385 #601680011  #605626205
    print(binascii.hexlify(request,' '))

    omnikloggerpublicaddress = '192.168.2.157'
    omnikloggerdestport = 8899
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            print("Connecting to {0}:{1}".format(omnikloggerpublicaddress, omnikloggerdestport))
            s.connect((omnikloggerpublicaddress, omnikloggerdestport))
            print("Sending message {0}".format(binascii.hexlify(request, ' ')))
            s.sendall(request)
            print("Waiting for response")
            s.settimeout(2.0)
            resp = s.recv(1024)
            if len(resp) > 0:
                answer = Omnik.Response()
                print("Response recieved {0}".format(binascii.hexlify(resp, ' ')))
                print(answer.decode(resp))
                print(answer.getJSON())
            else:
                print("No response recieved")

    except socket.error as msg:
        print(msg)

# bootstrap
if __name__ == '__main__':
    main()

###############################################################################################
###############################################################################################
