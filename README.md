<p align="center">
  <h3 align="center">Pentest Collaboration Framework</h3>
  <p align="center">
    Web application to help security specialist manage and share project information.
    <br />
    <a href="https://gitlab.com/invuls/pentest-projects/pcf/-/wikis/home"><strong>Explore the docs »</strong></a>
    <br />
    <img src="https://gitlab.com/invuls/pentest-projects/pcf/-/raw/master/static/images/main.png">
    <br />
    <!-- <a href="https://199.192.28.132:55666/">View Demo</a>
    · -->
    <a href="https://gitlab.com/invuls/pentest-projects/pcf/issues">Report Bug</a>
    ·
    <a href="https://gitlab.com/invuls/pentest-projects/pcf/issues">Request Feature</a>
  </p>
</p>

[![Deploy](https://www.herokucdn.com/deploy/button.png)](https://dashboard.heroku.com/new-app?template=https://github.com/drakylar/pcf_FORK_CHECK_GITLAB)





# 🤔 What is this?
1. Create personal account
2. Create security team
3. Add members to team
4. Create testing project
5. ???
6. Profit!


PCF only job is to help security specialists to save project information and share it with your teammates.

# ✨ Features
* 🔬 You can create private or team projects!
* 💼 Team moderation.
* 🛠 Multiple tools integration support! Such as Nmap/Masscan, Nikto, Nessus and Acunetix! 
* 😁 Super-User-Friendly design.

## ‼️ Important Links

| Installation Guide | Documentation | Telegram |
| ------------------ | ------------- | ------- |
| 📖 [Installation Guide](https://gitlab.com/invuls/pentest-projects/pcf/-/wikis/Installation) | 📚 [Documentation](https://gitlab.com/invuls/pentest-projects/pcf/-/wikis/home) | 💬 [Telegram](https://t.me/PentestCollaborationFramework)

## 🙋 Table of Contents
* 📖 [Fast Installation Guide](https://gitlab.com/invuls/pentest-projects/pcf#-full-installation-guide)
    * 💻 [Standalone](https://gitlab.com/invuls/pentest-projects/pcf#-windows-linux-macos)
    * ☁️ [Heroku](https://gitlab.com/invuls/pentest-projects/pcf#%EF%B8%8F-heroku)
    * 🐋 [Docker Usage](https://gitlab.com/invuls/pentest-projects/pcf#whale-docker)
* 🦜 [Telegram](https://t.me/PentestCollaborationFramework)
* 🤸 [Usage](https://gitlab.com/invuls/pentest-projects/pcf#-usage)
* 🖼️ [Gallery](https://gitlab.com/invuls/pentest-projects/pcf#-gallery)
* ⚠️ [WARNING](https://gitlab.com/invuls/pentest-projects/pcf#-warning)
* 🎪 [Community](https://gitlab.com/invuls/pentest-projects/pcf#-community)
* 📝 [TODO](https://gitlab.com/invuls/pentest-projects/pcf#-todo)

# 🔭 Why PCF?
Why use notepad? <br>
Why scatter files into folders, and then remember what file it is? <br>
Why send a lot of messages to colleagues on the project, and then try to find the right one? <br><br> 
![image](https://i.ibb.co/f4d2RgQ/issues.png)

**Indeed, for all this, you can use the Pentest Collaboration Framework - an opensource and portable toolkit for automating routine processes when carrying out various works for testing!**

## 📊 PCF vs analogues

| **Name**  | PCF | Lair | Dradis | Faraday | AttackForge | PenTest.WS
| -------------- | --- | ---- | ------ | ------- | ----------- | ---------- 
| Portable | ✅ | ❌ | ❌ | ❌ | ❌  | ✅💲
| Cross-platform | ✅ | ✅ | ✅ | ✅ | ❌ | ❌
| Free | ✅ | ✅ | ❌✅ | ❌✅ | ❌✅  | ❌✅
| NOT deprecated! | ✅ | ❌ | ✅ | ✅ | ✅ | ✅
| Data export | ✅ | ❌✅ | ✅ | ✅ | ✅ | ❌✅
| Chat | ✅ | ❌ | ❌ | ❌ | ✅ | ❌
| Made for sec specialists, not managers | ✅ | ✅ | ✅ | ✅ | ❌ | ✅
| Report generation | ✅ | ❌ | ✅ | ✅ | ✅ | ✅
| API | ✅ | ❌✅ | ✅ | ✅ | ✅ | ✅

## Supported tools

| **Tool name**  | Integration type | Description
| ---------- | ---------------- | ---------------
| Nmap | Import | Import XML results (ip, port, service type, service version, hostnames, os). Supported plugins: vulners
| Nessus | Import | Import .nessus results (ip, port, service type, security issues, os)
| Masscan | Import | Import XML results (ip, port)
| Nikto | Import | Import XML, CSV, JSON results (issue, ip, port)
| Acunetix | Import | Import XML results (ip, port, issue)
| Checkmarx SAST | Import | Import XML/CSV results (code info, issue)
| ipwhois | Scan | Scan hosts(s)/network(s) and save whois data
| shodan | Scan | Scan hosts ang save info (ip, port, service).
| HTTP-Sniffer | Additional | Create multiple http-sniffers for any project.

# 📖 Fast Installation Guide
**You need only Python3**. 

## 🖥️ Windows / Linux / MacOS

Download project:
```sh
git clone https://gitlab.com/invuls/pentest-projects/pcf/
```

Go to folder:
```bash
cd pcf
```

Install deps (for unix-based systems):
```bash
pip3 install -r requirements_unix.txt

```
or windows:
```bash
pip.exe install -r requirements_windows.txt

```

Run initiation script:
```bash
python3 new_initiation.py
```

Edit configuration:
```bash
nano configuration/settings.ini
```

Run:
```bash
python3 app.py
```

## ☁️ Heroku

### 👍 Easy way

Deploy from our github repository:

[![Deploy](https://www.herokucdn.com/deploy/button.png)](https://dashboard.heroku.com/new-app?template=https://github.com/drakylar/pcf_FORK_CHECK_GITLAB)

Careful: Check github repo last push version!

You can check 😓Harder and 💀Impossible ways at [🌐wiki page](https://gitlab.com/invuls/pentest-projects/pcf/-/wikis/Heroku%20installation)!

## :whale: Docker 

#### One line install

_Will be added later!_

#### Build by yourself

Clone repository
```bash
git clone https://gitlab.com/invuls/pentest-projects/pcf
```
Go to folder:
```bash
cd pcf
```
Run docker-compose:
```bash
docker-compose up
```
and go to URL
```bash
http://127.0.0.1:5000/
```
# 🤸 Usage

Default port (check config): 5000
Default ip (if run at localhost): 127.0.0.1 



1. Register at http(s)://\<ip\>:\<port\>/register

2. Login at http(s)://\<ip\>:\<port\>/login

3. Create team (if need) at http(s)://\<ip\>:\<port\>/create_team

4. Create project at http(s)://\<ip\>:\<port\>/new_project

5. Enjoy your hacking process! 

API information: https://gitlab.com/invuls/pentest-projects/pcf/-/wikis/API%20documentation

## 🖼️ Gallery


|||
:-------------------------:|:-------------------------:
![image](https://i.ibb.co/y4qNYJr/team.png)|![image](https://i.ibb.co/8DyCK1J/2020-08-26-014024.png)
Team information|Projects list
![image](https://i.ibb.co/f4d2RgQ/issues.png)|![image](https://i.ibb.co/mDrNQYQ/2020-08-26-014024.png)
Project: issues|Project: host page
![image](https://i.ibb.co/rdCNZqv/2020-08-26-014024.png)|![image](https://i.ibb.co/r0PPbwV/2020-08-26-014024.png)
Project: hosts|Project:services
![image](https://i.ibb.co/17R9tjP/2020-08-26-021037.png)|![image](https://i.ibb.co/fMyfHmb/2020-08-26-021037.png)
Project: issue info|Project: issue info (PoC)
![image](https://i.ibb.co/CtFX3nD/2020-08-26-014024.png)|![image](https://i.ibb.co/6vSddfD/2020-08-26-021037.png)
Project: networks|Project: files
![image](https://i.ibb.co/P6HB4kD/2020-08-26-235628.png)|![image](https://i.ibb.co/6FBhh1p/2020-08-26-235628.png)
Project: tools (may be changed)|Project: found credentials
![image](https://i.ibb.co/8xmZyNL/2020-08-26-235628.png)|![image](https://i.ibb.co/g3rD3nj/2020-08-26-235628.png)
Project: testing notes|Project: chats
![image](https://i.ibb.co/3Y1psdS/2020-08-26-235628.png)|![image](https://i.ibb.co/NCmRJf9/2020-08-26-235628.png)
Project: settings|Project: reports (in development process)


# ⚠️ WARNING


#### 🚨 Default settings

This program, by default, uses 5000 port and allows everyone to register and use it, so you need to set correct firewall & network rules.

#### 🔌 Initiation logic

Careful with new_initiation script! It makes some important changes with filesystem:

1. Renames database /configuration/database.sqlite3 
2. Regenerates SSL certificates
3. Regenerates session key.
4. Creates new empty /configuration/database.sqlite3 database
5. Creates /tmp_storage/ folder


# 🎪 Community

If you have any feature suggestions or bugs, leave a GitLab issue. We welcome any and all support :D

We communicate over Telegram. [Click here](https://t.me/PentestCollaborationFramework) to join our Telegram community!


## 📝 TODO

#### General
* [x] Team config storage
* [x] Team report templates storage
* [x] Automatic database backup
* [x] Share Issues with non-registered users
* [x] Report generation
* [x] Fast popular password bruteforce check (top-10k)
* [x] REST-API
* [ ] Network graph
* [x] Hash fast export/import
* [ ] Add another databases
* [x] Add .doc report generation support
* [ ] Full redesign (after stable version)
    
#### Tools
* [x] HTTP-sniffer
* [ ] NetNTLM smb sniffer
* [ ] Custom tool txt report upload support
* [x] Hash fast check top-10k passwords


P.S. Readme template was copied from [RustScan](https://github.com/RustScan/RustScan) project.
