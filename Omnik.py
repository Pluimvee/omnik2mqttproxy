##################################################################################################
# Class for parsing Omnik packages and creating request messages
# Erik Veer
# Credits to: https://github.com/Woutrrr and https://github.com/jbouwh
##################################################################################################
import struct  # Converting bytes to numbers
import datetime
import time
import binascii
import json

##################################################################################################
#
##################################################################################################
class Response:

    def __init__(self, msg=b''):
        self.decode(msg)

    def decode(self, msg):
        self.values = {}
        self.rawmsg = binascii.hexlify(msg, ' ')
        self.payload = b''
        self.values["timestamp"] = datetime.datetime.utcfromtimestamp(time.time()).strftime("%Y-%m-%dT%H:%M:%SZ")

        if len(msg) < 12:
            return "Message does not have the required header length"
        
        start, payload_lg, unkwn1, unkwn2, loggerId1, loggerId2 = struct.unpack("<BBBBII", msg[0:12])
        if start != 0x68:
            return "Unknown start byte, expecting 0x68, received {0}".format(start)

        if len(msg) != payload_lg+14:
            return "Expecting {0} bytes, recieved {1}".format(payload_lg+14, len(msg))
        
        if loggerId1 != loggerId2:
            return "LoggerId mismatch in header"
        self.values["logger_id"] = loggerId1

        self.payload = binascii.hexlify(msg[12:12+payload_lg], ' ')

        if payload_lg == 125:
#           instr = struct.unpack("BBB", msg[12:15])   three bytes with the response id? \x81\x02\x01
            payload = struct.unpack(">16s20H2I18s15s5s9s", msg[15:126])

            self.values["inverter_id"]     = str(payload[0].decode())
            self.values["temperature"]    = payload[1]/10.0
            self.values["voltage_pv1"]    = payload[2]/10.0
#            self.values["voltage_pv2"]    = payload[3]/10.0
#            self.values["voltage_pv3"]    = payload[4]/10.0
            self.values["current_pv1"]    = payload[5]/10.0
#            self.values["current_pv2"]    = payload[6]/10.0
#            self.values["current_pv3"]    = payload[7]/10.0
            self.values["current_ac1"]    = payload[8]/10.0
#            self.values["current_ac2"]    = payload[9]/10.0
#            self.values["current_ac3"]    = payload[10]/10.0
            self.values["voltage_ac1"]    = payload[11]/10.0
#            self.values["voltage_ac2"]    = payload[12]/10.0
#            self.values["voltage_ac3"]    = payload[13]/10.0
            self.values["frequency_ac1"]  = payload[14]/100.0
            self.values["power_ac1"]      = payload[15]
#            self.values["frequency_ac2"]  = payload[16]/100.0
#            self.values["power_ac2"]      = payload[17]
#            self.values["frequency_ac3"]  = payload[18]/100.0
#            self.values["power_ac3"]      = payload[19]
            self.values["energy_today"]   = payload[20]/100.0
            self.values["energy_total"]   = payload[21]/10.0
            self.values["operating_hours"]= payload[22]
            self.values["master_version"] = str(payload[24].decode())
            self.values["slave_version"]  = str(payload[26].decode())

        # using UDP we get two message, the above and a 17bytes confirmation
        # 'DATA SEND IS OK\r\n'
        if payload_lg == 0x11:
            self.values["UDP_ack"]        = str(msg[12:12+0x11].decode())

        # todo check the crc and closing character 0x16
        return "Successfully decoded message from logger {0}".format(loggerId1)

    # some message type checks
    def isInverterStatus(self):
        return self.values.get("inverter_id") != None

    def isConfirmation(self):
        return self.values.get("UDP_ack") != None

    # access to the values
    def getRawMsg(self):
        return self.rawmsg
    
    def getPayload(self):
        return self.payload

    def getValues(self):
        return self.values

    def getJSON(self):
        return json.dumps(self.values)

    # easy access to some identifiers
    def getLoggerId(self):
        return self.values["logger_id"]

    def getInverterId(self):
        return self.values["inverter_id"]

    def getMasterVersion(self):
        return self.values["master_version"]

    def getSlaveVersion(self):
        return self.values["slave_version"]

    # easy access to some common values
    def getTemp(self):
        return self.values["temperature"]

    def getETotal(self):
        return self.values["energy_total"]

    def getEToday(self):
        return self.values["energy_today"]

    def getHTotal(self):
        return self.values["operating_hours"]

    # easy access to phase one values
    def getPower(self):
        return self.values["power_ac1"]        

    def getVoltage(self):
        return self.values["voltage_ac1"]    

    def getFrequency(self):
        return self.values["frequency_ac1"]    

    def getCurrent(self):
        return self.values["current_ac1"]    


##################################################################################################
#
##################################################################################################
class Request:

    def _package(self, ser, payload):
        """
        The request string is build from several parts. 

        start char  \x68
        payload lg  \x02
        unknown     \x40
        unknown     \x30
        WiFiLog s/n 4 bytes     
        WiFiLog s/n 4 bytes     2 times!!
        payload
        checksum
        end char    \x16
        """
        # the starting datagram
        message = struct.pack("<B", len(payload))
        message += b'\x40\x30'
        message += struct.pack("<II", ser, ser)
        message += payload
        cs = sum([c for c in message]) & 255     # wrap arround one byte
        csbyte = struct.pack("<B", cs)

        container = b''.join([b'\x68', message, csbyte, b"\x16"])
        return container

    def encode(self, ser):
        return self._package(ser, b'\x01\x00')

##################################################################################################
##################################################################################################
