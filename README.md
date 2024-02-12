A Python application with html dashboard designed to help use your KrakenSDR with TAK products.
For use in a non-production environment.
Defaults are set to be run on the same server as your KrakenSDR server, however other network configurations should work.

Tested using Python and Python 3 with a Chrome browser.
# Quick Start
Step 1:
Clone or download Kraken-to-TAK-Python to your computer

Step 2:
Initialize or start your KrakenSDR software (this can be done after starting Kraken to TAK also)

Step 3:
Navigate to the directory and start
```
$ cd Kraken-to-TAK-Python
$ python KrakenToTAK.py
```

Step 4:
Open a browser and navigate to http://<YOUR_IP:8000

https://www.youtube.com/watch?v=AjJOk-vhxMA
# Instructions
Kraken Server
	-Kraken Server IP should be the IPv4 of the computer that your KrakenSDR software is running on.
<img width="325" alt="Screenshot 2024-02-11 at 5 06 51 PM" src="https://github.com/canaryradio/Kraken-to-TAK-Python/assets/127666889/a57aa025-4e57-4522-a30e-1ae678b5a072">

TAK Server
	-TAK Server IP should be the IPv4 of your TAK Server. TAK Server Port should be the port you assigned for the Kraken input. TAK Multicast will enable and disable sending Kraken packets to the multicast default for TAK clients

<img width="328" alt="Screenshot 2024-02-11 at 5 09 54 PM" src="https://github.com/canaryradio/Kraken-to-TAK-Python/assets/127666889/36be1a29-7fe7-4d11-b306-81c6f7ee7b9b">

Bearing Filter
	-DOA Ignore/Exclusion Range is the option to not build a packet for bearings that are coming from the specified direction. The reset button will remove the filter.

<img width="332" alt="Screenshot 2024-02-11 at 5 10 51 PM" src="https://github.com/canaryradio/Kraken-to-TAK-Python/assets/127666889/69abba4a-aaa0-4972-963e-5204c208bc8c">

New line with new UID
	-Persist DOA Line will randomize the UID of the Line XML payload which will create a new line for each DOA bearing instead of overwriting the same line.

<img width="330" alt="Screenshot 2024-02-11 at 5 11 29 PM" src="https://github.com/canaryradio/Kraken-to-TAK-Python/assets/127666889/1a7231f5-586b-49fe-89b5-749bdfb1fd35">
