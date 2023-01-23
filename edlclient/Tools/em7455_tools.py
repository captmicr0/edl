import serial
import serial.tools.list_ports
from pprint import pp

#import sys
#sys.path.insert(0, "D:\\Programming\\Py38Projects\\edl\\edlclient\\Tools")
import sierrakeygen

def listCOMports():
    '''List all serial ports on the device. Also guesses which one is a AT modem device'''
    ports = serial.tools.list_ports.comports()
    devices, guess = [], None
    for port in sorted(ports):
        hwid = port.hwid
        if (port.vid and port.pid):
            hwid = "ID %04x:%04x" % (port.vid, port.pid)
        print("{}: {} [{}]".format(port.device, port.description, hwid))
        if ("modem" in port.description.lower()) and ("1199:9071" in hwid.lower()):
            guess = port.device
        devices += [port.device]
    return devices, guess

def selectCOMport():
    '''Selects a serial port'''
    devices, guess = listCOMports()
    choice = input("Select Serial Port [%s]: " % guess)
    if choice not in devices:
        if guess:
            choice = guess
        else:
            print("no serial port selected")
            exit()
    print("selected serial port: '%s'" % choice)
    return choice

def isOK(response):
    return response[-1] == "OK"

def isERR(response):
    return response[-1] == "ERROR"

class ATdevice:
    '''Class to communicate with AT devices'''
    def __init__(self, port=''):
        self.ser = serial.Serial(baudrate=115200, bytesize=8, parity='N', stopbits=1, timeout=1)
        self.set_port(port)
    
    def set_port(self, port=''):
        '''Set which serial port this class uses to talk to the AT device'''
        if len(port) == 0:
            port = selectCOMport()
        self.ser.port = port

    def open(self):
        '''Open the devices serial port'''
        if self.ser.isOpen():
            print("serial port already open")
            self.ser.port
        else:
            print("opening serial port... ", end="")
            try:
                self.ser.open()
                print("success!")
                self.CMD("E0") #AT echo off (breaks everything if on)
            except serial.serialutil.SerialException as err:
                print("failed:")
                print(err)
    
    def close(self):
        '''Close the devices serial port'''
        if not self.ser.isOpen():
            print("serial port already closed")
        else:
            print("closing serial port... ", end="")
            try:
                self.ser.close()
                print("success!")
            except serial.serialutil.SerialException as err:
                print("failed:")
                print(err)
    
    def list2dict(self, l):
        '''Convert list of colon separated strings into a dictionary'''
        return dict(map(lambda s : map(str.strip, s.split(':',1)), l))

    def va2str(self, *va):
        '''Convert varargs to string, encapsulating string arguments in double apostrophes, split by commas'''
        res = ""
        for arg in va:
            if type(arg) == str:
                res += '"%s",' % arg
            elif type(arg) == int:
                res += '%d,' % arg
        if res[-1] == ',':
            res = res[0:-1]
        return res

    #THE FOLLOWING FUNCTIONS ARE AT COMMAND HELPERS#
    def CMD(self, command="", ender="\r"):
        '''Send a command to the serial port and read the response'''
        command = "AT" + command + ender
        command = command.encode('utf-8')
        self.ser.write(command) 
        response = self.ser.readlines()
        response = [line.decode().strip() for line in response]
        response = [line for line in response if len(line) > 0]
        if isOK(response):
            print("AT OK [%s]" % command)
            #response = response[0:-1]
        elif isERR(response):
            print("AT ERROR [%s]" % command)
        return response
    
    def TEST(self, command):
        '''=? - Test commands - used to check whether a command is supported or not by the MODEM.'''
        return self.CMD("%s=?" % command)
    
    def READ(self, command):
        '''? - Read command - used to get mobile phone or MODEM settings for an operation.'''
        return self.CMD("%s?" % command)

    def SET(self, command, *args):
        '''= - Set command - used to modify mobile phone or MODEM settings for an operation.'''
        return self.CMD("%s=%s" % (command, self.va2str(*args)))

    def EXEC(self, command, *args):
        '''= - Execution commands - used to carry out an operation. Parameters of execution commands are not stored.'''
        if len(args) > 0:
            return self.CMD("%s=%s" % (command, self.va2str(*args)))
        else:
            return self.CMD("%s" % command)
    
    def INFO(self):
        '''Info command - used to get info about the modem'''
        res = self.EXEC("I")
        return self.list2dict(res[0:-1])
    
    def RESET(self):
        '''Reset command - used to reset the modem'''
        res = self.EXEC("!RESET")

class EM7455(ATdevice):
    '''Class to communicate with EM7455 modem'''

    def EnableAdvCmds(self):
        '''Enable advanced commands'''
        return isOK(self.EXEC("!ENTERCND","A710"))
    
    def GetUSBInfo(self):
        '''Gets all USB settings'''
        self.EnableAdvCmds()
        usbinfo = []
        for cmd in ['!USBVID','!USBPID','!USBPRODUCT','!PRIID']:
            usbinfo.extend(self.READ(cmd))
        return usbinfo
    
    def MakeGeneric(self):
        if not self.EnableAdvCmds(): return False
        if not isOK(self.EXEC("!USBPID",9071,9070)                      ): return False
        if not isOK(self.EXEC("!USBVID",1199)                           ): return False
        if not isOK(self.EXEC("!USBPRODUCT","EM7455")                   ): return False
        if not isOK(self.EXEC("!PRIID","9904802","001.001","Generic")   ): return False
        # Reset
        self.EXEC("!RESET")
        return True
    
    def OpenLock(self):
        '''Unlocks engineering commands'''
        if not self.EnableAdvCmds(): return False
        challenge = self.READ('!OPENLOCK')
        pp(challenge)
        keygen = sierrakeygen.SierraGenerator()
        response = keygen.run("MDM9x30", challenge[0], 0)
        return isOK(self.EXEC("!OPENLOCK", response))

    def RepairIMEI(self, IMEI):
        '''Repairs IMEI'''
        def luhn(n):
            r = [int(ch) for ch in str(n)][::-1]
            return (sum(r[0::2]) + sum(sum(divmod(d*2,10)) for d in r[1::2])) % 10 == 0
        IMEI = str(IMEI)
        print("Repairing IMEI...")
        # Get current IMEI
        currentIMEI = ""
        try:
            currentIMEI = self.INFO()['IMEI']
            print("current IMEI: %s" % currentIMEI)
        except KeyError:
            print("failed to get old IMEI")
            return False
        # Validate new IMEI
        print("new IMEI: %s" % IMEI)
        if not luhn(int(IMEI)):
            print("Luhn checksum invalid!")
            return False
        # Unlock engineering commands
        if not self.OpenLock():
            print("OpenLock failed!")
            return False
        # Unlock IMEI NVmemory
        if not isOK(self.EXEC("!NVIMEIUNLOCK")):
            print("NVIMEIUNLOCK failed!")
            return False
        # Prepare new IMEI (two digit groups separted by ',' adding '0' to make last group two digits)
        argIMEI = IMEI + "0" #zero padding on last digit
        argIMEI = [argIMEI[i:i+2] for i in range(0, len(argIMEI), 2)]
        # Set IMEI
        if not isOK(self.CMD("!NVENCRYPTIMEI=%s" % ','.join(argIMEI))):
            print("NVENCRYPTIMEI failed!")
            return False
        # Check that IMEI was updated
        print("checking IMEI...")
        try:
            currentIMEI = self.INFO()['IMEI']
            print("current IMEI: %s" % currentIMEI)
        except:
            print("failed to get current IMEI")
            return False
        if currentIMEI == IMEI:
            print("repair success!")
            # Reset
            self.EXEC("!RESET")
            return True
        return False        


if __name__ == "__main__":
    dev = EM7455()
    dev.open()

    pp(dev.INFO())

    #dev.RepairIMEI('IMEI_goes_here')

    dev.close()
