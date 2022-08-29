#!/usr/bin/python3           # This is client.py file

import socket
from time import sleep

# create a socket object
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 

# get local machine name
host = socket.gethostname()                           

port = 30000

# connection to hostname on the port.
s.connect((host, port))                               

msg = 'asking for data'
s.send(msg.encode('ascii'))

# Receive no more than 1024 bytes
msg = s.recv(1024)                                    

s.close()
print (msg.decode('ascii'))
