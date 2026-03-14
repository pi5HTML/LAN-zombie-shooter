# LAN-zombie-shooter
A simple fun LAN video game, all you do i put 2 files on a pi (I have tested with a zero 2 w and it works very well) and type in the IP at port 5000 and anyone on your wifi can join.
made with the help of AI.
how to set up:

start by flahing Pi OS lite onto a Pi and make sure SSH is on


then SSH into your pi and update everything by runing the normal: sudo apt update && sudo apt upgrade -y


then install the python stuff to manage it: sudo apt install python3-pip python3-flask -y


install 2 more python libraries (this is very important, it reduces lag spikes): pip3 install flask-socketio eventlet --break-system-packages


install the game: git clone https://github.com/pi5HTML/LAN-zombie-shooter



go into the folder that was just made: cd LAN-zombie-shooter



create the file that tells it to alway run: sudo nano /etc/systemd/system/zombie.service



past this in and change user name to the user name you set when flashing the OS: 

[Unit]

Description=LAN Zombie Shooter

After=network.target

[Service]

ExecStart=/usr/bin/python3 /home/pi/LAN-zombie-shooter/server.py

WorkingDirectory=/home/pi/LAN-zombie-shooter

Restart=always

RestartSec=3

User= <-- change this to you user, no space bettween the = and the start of your username

[Install]

WantedBy=multi-user.target

^last line^ do not copy this or anything under



then hit control+o enter then control+x (save and exit) 



then reload all files so it can read it: sudo systemctl daemon-reload



then enable it: sudo systemctl enable zombie



and run it: sudo systemctl start zombie


there you go, should away be on at boot and stay on, to join, go to: http://(your pi's ip):5000


and then you have a easy to play fun zombie shooter that runs on your wifi
