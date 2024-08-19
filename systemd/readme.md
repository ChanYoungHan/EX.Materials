## USAGE
command with sudo
```bash
mkdir -p  /usr/local/etc/test_scripts
cp ./chanyoung-service1.sh /usr/local/etc/test_scripts
cp ./chanyoung-service2.sh /usr/local/etc/test_scripts
cp ./other-service2.sh /usr/local/etc/test_scripts
chmod +x ~/test_scripts/chanyoung-service1.sh
chmod +x ~/test_scripts/chanyoung-service2.sh
chmod +x ~/test_scripts/other-service.sh
```

```bash
sudo cp ./chanyoung-service1.service /etc/systemd/system
sudo cp ./chanyoung-service2.service /etc/systemd/system
sudo cp ./other-service.service /etc/systemd/system
sudo systemctl daemon-reload
sudo systemctl start chanyoung-service1.service
sudo systemctl start chanyoung-service2.service
sudo systemctl start other-service.service
```