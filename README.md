A Python application with a html dashboard designed to help use your KrakenSDR with TAK products
Designed for use in a non-production environment
Defaults are set to be run on the same server as your KrakenSDE server, however alternative netork configurations should work

Tested using Python and Python 3 with a Chrome browser

Step 1:
Clone or download to your computer

Step 2:
Initialize or start your KrakenSDR software (this can be done after starting Kraken to TAK also)

Step 3:
Navigate to the directory and start with $ python kraken-to-TAK

Step 4:
Open a browser and navigate to http://<YOUR_IP:8000

Kraken Server IP should be the IPv4 of the computer that your KrakenSDR software is running on

<img width="325" alt="Screenshot 2024-02-11 at 5 06 51 PM" src="https://github.com/canaryradio/Kraken-to-TAK-Python/assets/127666889/a57aa025-4e57-4522-a30e-1ae678b5a072">

TAK Server IP should be the IPv4 of your TAK Server
TAK Server Port should be the port you assigned for the Kraken input
TAK Multicast will enable and disable sending Kraken packets to the multicast default for TAK clients

DOA Ignore/Exclusion Range is the option to not build a packet for bearings that are coming from the specified direction

Persist DOA Line will randomize the UID of the Line XML payload which will create a new line for each DOA bearing instead of overwriting the same line
