#!/usr/bin/env python3
import atexit
import signal
import sys

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
import os
import time
from functools import cmp_to_key
from itertools import cycle
from pathlib import Path
import platform
import socket
from threading import Thread
from time import sleep
from demo import Demo

ready_to_send = False

if platform.machine() == 'aarch64':  # Jetson
    os.environ['OPENBLAS_CORETYPE'] = "ARMV8"

sys.path.append(str(Path(__file__).parent.absolute()))
sys.path.append(str((Path(__file__).parent / "depthai_sdk" / "src").absolute()))

from depthai_helpers.app_manager import App
from depthai_helpers.arg_manager import parseArgs

args = parseArgs()

try:
    import cv2
    import depthai as dai
    import numpy as np
except Exception as ex:
    print("Third party libraries failed to import: {}".format(ex))
    print("Run \"python3 install_requirements.py\" to install dependencies or visit our installation page for more details - https://docs.luxonis.com/projects/api/en/latest/install/")
    sys.exit(42)

from log_system_information import make_sys_report
from depthai_helpers.supervisor import Supervisor
from depthai_helpers.config_manager import ConfigManager, DEPTHAI_ZOO, DEPTHAI_VIDEOS
from depthai_helpers.metrics import MetricManager
from depthai_helpers.version_check import checkRequirementsVersion
from depthai_sdk import FPSHandler, loadModule, getDeviceInfo, downloadYTVideo, Previews, createBlankFrame
from depthai_sdk.managers import NNetManager, SyncedPreviewManager, PreviewManager, PipelineManager, EncodingManager, BlobManager

class OverheatError(RuntimeError):
    pass

if not args.noSupervisor:
    print('Using depthai module from: ', dai.__file__)
    print('Depthai version installed: ', dai.__version__)

if not args.debug and not args.skipVersionCheck and platform.machine() not in ['armv6l', 'aarch64']:
    checkRequirementsVersion()

sentryEnabled = False

try:
    import sentry_sdk

    sentry_sdk.init(
        "https://159e328c631a4d3eb0248c0d92e41db3@o1095304.ingest.sentry.io/6114622",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0,
        with_locals=False,
    )
    sentry_sdk.set_context("syslog", make_sys_report(anonymous=True, skipUsb=True, skipPackages=True))
    sentryEnabled = True
except Exception as ex:
    print("Logging and crash reporting disabled! {}".format(ex))

class Trackbars:
    instances = {}

    @staticmethod
    def createTrackbar(name, window, minVal, maxVal, defaultVal, callback):
        def fn(value):
            if Trackbars.instances[name][window] != value:
                callback(value)
            for otherWindow, previousValue in Trackbars.instances[name].items():
                if otherWindow != window and previousValue != value:
                    Trackbars.instances[name][otherWindow] = value
                    cv2.setTrackbarPos(name, otherWindow, value)

        cv2.createTrackbar(name, window, minVal, maxVal, fn)
        Trackbars.instances[name] = {**Trackbars.instances.get(name, {}), window: defaultVal}
        cv2.setTrackbarPos(name, window, defaultVal)

noop = lambda *a, **k: None

def prepareConfManager(in_args):
    confManager = ConfigManager(in_args)
    confManager.linuxCheckApplyUsbRules()
    if not confManager.useCamera:
        if str(confManager.args.video).startswith('https'):
            confManager.args.video = downloadYTVideo(confManager.args.video, DEPTHAI_VIDEOS)
            print("Youtube video downloaded.")
        if not Path(confManager.args.video).exists():
            raise ValueError("Path {} does not exists!".format(confManager.args.video))
    return confManager


def runOpenCv():
    confManager = prepareConfManager(args)
    demo = Demo()
    signal.signal(signal.SIGINT, demo.stop)
    signal.signal(signal.SIGTERM, demo.stop)
    atexit.register(demo.stop)
    demo.run_all(confManager)

# function to create threads
#def send_function(arg):
#    print("************************************************************************")
#    global ready_to_send
#    if ready_to_send:
#        print("ready_to_send = True")
#        send_data(x_global, y_global, z_global)
#        sleep(1)
#        ready_to_send = False
#
#thread = Thread(target = send_function, args = (10, ))
#thread.start()
#thread.join()
#print("thread finished...exiting")

# Send data
def send_data(x,y,z):
    print ("start sending data")
    try:
        c, addr = s.accept() # Establish connection with client
        print ("connection established")
        try:
            print ("start recieving request")
            msg = c.recv(1024).decode()
            print("Joint Positions = ", msg)
            msg = c.recv(1024).decode()
            print("Request = ", msg)
            X= y+0.33
            Y= x-0.03
            Z= z-0.2
            if ((Z>0.7) and (Z<1.3)):
                instruction = f"({X}, {Y}, {Z})".encode()
                print(instruction)
                print(type(instruction))
                print ("start sending ...")
                c.send(instruction)
                print("The position is sent")
            else:
                pass
        except:
            print ("Fail recieving request or sending data")
    except:
        print("connection cannot be established")

###########################################################################
################################### MAIN ##################################
###########################################################################

HOST = ""    # The remote host
PORT = 30000 # The same port as used by the server

print("Starting Program")

mysocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mysocket.settimeout(1)
mysocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
mysocket.bind((HOST, PORT)) # Bind to the port 
mysocket.listen(5) # Now wait for client connection

if __name__ == "__main__":
    try:
        args.guiType = "cv"
        runOpenCv()
    except KeyboardInterrupt:
        sys.exit(0)
