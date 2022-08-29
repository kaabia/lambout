
import _thread as thread
import time

# Define a function for the thread
def print_time(threadName, delay):
   while 1:
      print ("{}: {}".format(threadName, time.ctime(time.time())))

# Create two threads as follows
try:
   thread.start_new_thread( print_time, ("Thread-1", 2, ) )
   thread.start_new_thread( print_time, ("Thread-2", 4, ) )
except:
   print("Error: unable to start thread")

while 1:
   pass