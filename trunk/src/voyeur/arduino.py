import os
import time
import struct
import binascii
import glob
import db
import platform
from Queue import Queue
from PyQt4.QtCore import QThread
from numpy import array, int32, float32, append, ndarray
from serial import Serial, SerialException
from configobj import ConfigObj
import voyeur.exceptions as ex


class SerialCallThread(QThread):
        '''
        This thread serializes communication across a single serial port.

        Calls are serialized and performed on a separate thread.
        '''

        def __init__(self, monitor=None, max_queue_size = 1, QObject_parent=None):
            QThread.__init__(self, QObject_parent)
            self.monitor = monitor
            self.output_queue = Queue(maxsize=max_queue_size)

        def enqueue(self, fn, *args, **kwargs):
            #print "Enqueuing: ", fn
            self.output_queue.put((fn, args, kwargs), block=True)

        def run(self):
            try:
                from Foundation import NSAutoreleasePool
                pool = NSAutoreleasePool.alloc().init()
            except ImportError:
                pass # Windows

            while self.monitor.running or not self.output_queue.empty():
                """print "Serializer running: ", time.clock()
                print "max size: ", self.output_queue.maxsize
                print "items: ", self.output_queue.qsize()
                print "Getting item from queue: ", time.clock()"""
                
                (output_fn, args, kwargs) = self.output_queue.get(block=True, timeout=0.5) # block 0.5 seconds
                #print "Got item in queue: ", time.clock()
                #print "queue function starting: ", time.clock()
                output_fn(*args, **kwargs)
                #print "queue function return: ", time.clock()

   
class SerialPort(object):
    
    NOLOSSTRANSMISSIONRATE = 0.7
    laststream = 0
    maxrate = 0
    overflownpackets = 0    

    def __init__(self, configFile, board = 'board1', port='port1'):
        """Takes the string name of the serial port
        (e.g. "/dev/tty.usbserial","COM1") and a baud rate (bps) and
        connects to that port at that speed.
        """
        self.config = ConfigObj(configFile)
        self.os = self.config['platform']['os']
        serial = self.config['serial']
        baudrate = serial['baudrate']
        self.board = self.config['platform'][board]
        serialport  = serial[self.os][port]
        if os.path.exists(serialport) or platform.win32_ver()[0] != '':
            self.serial = Serial(serialport, baudrate, timeout=1)
        else:
            raise ex.SerialException(serialport, "Serial Port Incorrect. Check config file.")

    def read_line(self):
        """Reads the serial buffer"""
        line = None
        try:
            line = self.serial.readline()
        except SerialException as e:
            print('pySerial exception: Exception that is raised on write timeouts')
            print(e)
        return line
        
    def write(self, data):
        """Writes *data* string to serial"""
        self.serial.write(data)
    
    def request_stream(self, stream_def, tries=10):
        """Reads stream"""
        #print "Stream request to serial: ", time.clock()
        for i in range(tries):
            #print "try: ", i
            self.write(chr(87))
            packets = self.read_line()
            
            streamtime = time.clock()
            rate = streamtime - self.laststream
            #print "Stream received: ", rate
            self.laststream = streamtime
            #skip the first two measurements
            if self.maxrate == 0:
                self.maxrate = 100
            elif self.maxrate == 100:
                self.maxrate = 0.2
            elif rate > self.maxrate:
                self.maxrate = rate
            if rate > self.NOLOSSTRANSMISSIONRATE:
                self.overflownpackets += 1
            #print "Stream returned: ", packets, " time: ", time.clock()
            return parse_serial(packets, stream_def)

    def request_event(self, event_def, tries=10):
        """Reads event data"""
        for i in range(tries):        
            self.write(chr(88)) 
            packets = self.read_line()
            return parse_serial(packets, event_def)
                
    def start_trial(self, parameters, tries=10):
        """Sends start command"""
        params = convert_format(parameters)
        params.pop("trialNumber")
        values = params.values()
        values.sort()
        for i in range(tries):        
            self.write(chr(90))
            for index, format, value in values:
                self.write(pack_integer(format, value))           
            line = self.read_line()
            if line and int(line[:1]) == 2:
                #print "Time 2 = ", time.clock()
                return True
            
    def user_def_command(self, command, tries=10):
        """Sends a user defined command
           Args: command is a string representing a command issued to arduino"""
        for i in range(tries):
            self.write(chr(86))
            self.write(command)
            self.write("\r")
            line = self.read_line()
            print line
            if line and int(line[:1]) == 2:
                return True
    
    def end_trial(self, tries=10):
        """Sends end command"""
        for i in range(tries):
            self.write(chr(89))   
            line = self.read_line()
            print line
            print "Maximum intertransmission rate(ms): ", self.maxrate
            print "Number of transmissions slower than max rate: ", self.overflownpackets
            if line and int(line[:1]) == 3:
                return True

    def request_protocol_name(self, tries=10):
        """Get protocal name from arduino (gives the name of the code that is running)"""
        for i in range(tries):
            self.write(chr(91))            
            line = self.read_line()
            if line and int(line[:1]) == 6:
                values = line.split(',')
                return values[1]
                                                                  
    def upload_code(self, hex_path):
        """Upload code to the arduino"""
        self.serial.close()
        avr = self.config['avr']
        verbosity = avr['verbosity']        
        command = avr[self.os]['command']
        conf = avr[self.os]['conf']        
        flags = avr[self.board]['flags']
        arduino_upload_cmd = command \
                            + " -C" + conf \
                            + " " + verbosity \
                            + " " + flags \
                            + " -P" + self.serial.name \
                            + " -Uflash:w:" + hex_path + ":i"
        os.system(arduino_upload_cmd)
        self.serial.open()
    
    def open(self):
        """Open the serial connection"""
        self.serial.open()

    def close(self):
        """Close the serial connection"""
        self.serial.close()


def parse_serial(packets, protocol_def):
    """Parse serial read"""
    data = {}
    eot = False
    #print packets
    if packets:
        for packet in packets.split('*'):
            if packet and packet != '\r\n':
                payload = packet.split(',')
                handshake = int(payload[0])
                if handshake == 1:
                    if protocol_def:
                        for key, (index, kind) in protocol_def.items():
                            if payload[index] == '':
                                data[key] = None
                            else:
                                data[key] = convert_type(kind, payload[index])
                elif handshake == 4:
                    if protocol_def:
                        for key, (index, kind) in protocol_def.items(): 
                            data[key] =  convert_type(kind, payload[index])
                    #print data
                elif handshake == 5:
                    eot = True
        if eot:
            exp = ex.EndOfTrialException('End of trial')
            exp.last_read = data
            raise exp
    return data

                
def convert_format(parameters):
    """Converts dictionary database type format to serial transmission format"""
    values = parameters.copy()
    for key, (index, format, value) in values.items():
        if type(format) == type(db.Int):
            values[key] = (index, 'I', value)
        elif type(format) == type(db.Int16):
            values[key] = (index, 'h', value)
        elif type(format) == type(db.Float):
            values[key] = (index, 'f', value)
        elif type(format) == type(db.String32):
            values[key] = (index, 's', value)
        elif type(format) == type(db.StringN):
            values[key] = (index, 's', value)                                    
        elif type(format) == type(db.Time):
            values[key] = (index, 'd', value)
    return values


def convert_type(kind, value):
    """Converts string to python type"""
    if type(kind) == type(db.Int):
        return int(value)
    elif type(kind) == type(db.Int16):
        return int(value)
    elif type(kind) == type(db.Float):
        return float(value)
    elif type(kind) == type(db.String32):
        return str(value)
    elif type(kind) == type(db.StringN):
        return str(value)                                    
    elif type(kind) == type(db.Time):
        return float(value)
    elif type(kind) == ndarray:
        array = []
        elements = value.split(';')
        if(elements[:-1] is None): # NB: Admir's spec says there shouldn't be a trailing semi-colon, but check anyways
            elements.pop() # null value
        if kind.dtype == int32:
            for element in elements:
                array.append(int(element))
            return append(db.IntArray, array)
        elif kind.dtype == float32:
            for element in elements:
                array.append(float(element))
            return append(db.FloatArray, array)                
    return value


def pack_integer(format, value):
    """Packs integer as a binary string
       I = python 4 byte unsigned integer to an arduino unsigned long
       h = python 2 byte short to an arduino integer
    """

    return struct.pack(format, value)


def strip_tuple(dict):
    """Ensures the tuple in the dictionary does not have third value"""
    values = dict.values()
    if len(values[0]) == 2:
        return dict
    elif len(values[0]) == 3:
        return strip_3tuple(dict)
    return None


def strip_2tuple(dict):
    """
    Strips the second value of the tuple out of a dictionary
    {key: (first, second)} => {key: first}
    """
    new_dict = {}
    for key, (first, second) in dict.items(): 
        new_dict[key] =  first
    return new_dict


def strip_3tuple(dict):
    """
    Strips the third value of the tuple out of a dictionary
    {key: (first, second, third)} => {key: first, second}
    """
    new_dict = {}
    for key, (first, second, third) in dict.items(): 
        new_dict[key] =  (first, second)
    return new_dict
