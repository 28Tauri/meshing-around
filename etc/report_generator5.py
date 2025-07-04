# -*- coding: utf-8 -*-
# HTML5
import os
import re
import sys
import glob
import json
import pickle
import platform
import requests
import subprocess
import configparser
from string import Template
from datetime import datetime
from importlib.metadata import version
from collections import Counter, defaultdict

# global variables
LOG_PATH = '/opt/meshing-around/logs' # override path to log files (defaults to ../log)
W3_PATH = '/var/www/html/' # override path to web server root (defaults to ../www)
multiLogReader = False # set to True to read all meshbot logs in ../log
shameWordList = ['password', 'combo', 'key', 'hidden', 'secret', 'pass', 'token', 'login', 'username', 'admin', 'root', 'base64:', '==' ]

# system variables
script_dir = os.path.dirname(os.path.realpath(__file__))
www_dir = os.path.join(script_dir, 'www')
config_file = os.path.join(script_dir, 'web_reporter.cfg')

# set up report.cfg as ini file
config = configparser.ConfigParser()
try:
    config.read(config_file)
except Exception as e:
    print(f"Error reading web_reporter.cfg: {str(e)} generating default config")

if config.sections() == []:
    print(f"web_reporter.cfg is empty or does not exist, generating default config")
    shameWordList = shameWordList_str = ', '.join(shameWordList)
    config['reporting'] = {'log_path': script_dir, 'w3_path': www_dir, 'multi_log_reader': 'False', 'shame_word_list': shameWordList}
    with open(config_file, 'w') as configfile:
        config.write(configfile)

# read config file
LOG_PATH = config['reporting'].get('log_path', LOG_PATH)
W3_PATH = config['reporting'].get('w3_path', W3_PATH)
multiLogReader = config['reporting'].getboolean('multi_log_reader', multiLogReader)
# config['reporting']['shame_word_list'] is a comma-separated string
shameWordList = config['reporting'].get('shame_word_list', '')
if isinstance(shameWordList, str):
    shameWordList = shameWordList.split(', ')


def parse_log_file(file_path):
    global log_data
    lines = ['']

    # see if many logs are present
    if multiLogReader:
        # set file_path to the cwd of the default project ../log
        log_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'logs')
        log_files = glob.glob(os.path.join(log_dir, 'meshbot.log.*'))
        print(f"Checking log files: {log_files}")

        if log_files:
            log_files.sort()

            for logFile in log_files:
                with open(os.path.join(log_dir, logFile), 'r') as file:
                    lines += file.readlines()
    else:
        try:
            print(f"Checking log file: {file_path}")
            with open(file_path, 'r') as file:
                lines = file.readlines()
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            sys.exit(1)

    if multiLogReader:
        print(f"Consumed {len(lines)} lines from {len(log_files)} log files")
    else:
        print(f"Consumed {len(lines)} lines from {file_path}")

    log_data = {
        'command_counts': Counter(),
        'message_types': Counter(),
        'llm_queries': Counter(),
        'unique_users': set(),
        'warnings': [],
        'errors': [],
        'hourly_activity': defaultdict(int),
        'bbs_messages': 0,
        'messages_waiting': 0,
        'total_messages': 0,
        'gps_coordinates': defaultdict(list),
        'command_timestamps': [],
        'message_timestamps': [],
        'firmware1_version': "N/A",
        'firmware2_version': "N/A",
        'node1_uptime': "N/A",
        'node2_uptime': "N/A",
        'node1_name': "N/A",
        'node2_name': "N/A",
        'node1_ID': "N/A",
        'node2_ID': "N/A",
        'shameList': []
    }

    for line in lines:
        timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+', line)
        if timestamp_match:
            timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
            log_data['hourly_activity'][timestamp.strftime('%Y-%m-%d %H:00:00')] += 1

        if 'Bot detected Commands' in line or 'LLM Query:' in line or 'PlayingGame' in line:
            # get the command and user from the line
            command = re.search(r"'cmd': '(\w+)'", line)
            user = re.search(r"From: (.+)$", line)

            if 'LLM Query:' in line:
                log_data['command_counts']['LLM Query'] += 1
                log_data['command_timestamps'].append((timestamp.isoformat(), 'LLM Query'))

            if 'PlayingGame' in line:
                #log line looks like this. 2024-10-04 20:24:53,381 |    DEBUG | System: 862418040 PlayingGame BlackJack last_cmd: new
                game = re.search(r'PlayingGame (\w+)', line)
                user = re.search(r'System: (\d+)', line)
                log_data['command_counts'][game.group(1)] += 1
                log_data['command_timestamps'].append((timestamp.isoformat(), game))

            if user:
                user = user.group(1)
            if command:
                cmd = command.group(1)
                log_data['command_counts'][cmd] += 1
                # include the user who sent the command
                log_data['command_timestamps'].append((timestamp.isoformat(), cmd + f' from {user}'))

        if 'Sending DM:' in line or 'Sending Multi-Chunk DM:' in line or 'SendingChannel:' in line or 'Sending Multi-Chunk Message:' in line:
            log_data['message_types']['Outgoing DM'] += 1
            log_data['total_messages'] += 1
            log_data['message_timestamps'].append((timestamp.isoformat(), 'Outgoing DM'))

        if 'Received DM:' in line or 'Ignoring DM:' in line or 'Ignoring Message:' in line or 'ReceivedChannel:' in line or 'LLM Query:' in line:
            log_data['message_types']['Incoming DM'] += 1
            log_data['total_messages'] += 1
            # include a little of the message
            if 'Ignoring Message:' in line:
                log_data['message_timestamps'].append((timestamp.isoformat(), f'Incoming: {line.split("Ignoring Message:")[1][:90]}'))
            elif 'Ignoring DM:' in line:
                log_data['message_timestamps'].append((timestamp.isoformat(), f'Incoming: {line.split("Ignoring DM:")[1][:90]}'))
            elif 'LLM Query:' in line:
                log_data['message_timestamps'].append((timestamp.isoformat(), f'Incoming: {line.split("LLM Query:")[1][:90]}'))
            else:
                log_data['message_timestamps'].append((timestamp.isoformat(), 'Incoming:'))
            # check for shame words in the message
            for word in shameWordList:
                if word in line.lower():
                    if line not in log_data['shameList']:
                        line = line.replace('Ignoring Message:', '')
                        line = line.replace('|', '')
                        line = line.replace('INFO', '')
                        line = line.replace('DEBUG', '')
                        log_data['shameList'].insert(0, line)
                        
        # get the user who sent the message
        if 'To: ' in line:
            user_match = re.search(r"From: '([^']+)'(?: To:|$)", line)
        else:
            user_match = re.search(r"From: (.+)$", line)
        if user_match:
            log_data['unique_users'].add(user_match.group(1))
        
        # Error Logs
        if 'WARNING |' in line:
            # remove some junk from the line
            line = line.replace('|', '')
            line = line.replace('  ', ' ')
            log_data['warnings'].insert(0, line)

        if 'ERROR |' in line or 'CRITICAL |' in line:
            # remove some junk from the line
            line = line.replace('System:', '')
            line = line.replace('|', '')
            line = line.replace('  ', ' ')
            log_data['errors'].insert(0, line)

        # bbs messages
        bbs_match = re.search(r'📡BBSdb has (\d+) messages.*?Messages waiting: (\d+)', line)
        if bbs_match:
            bbs_messages = int(bbs_match.group(1))
            messages_waiting = int(bbs_match.group(2))
            log_data['bbs_messages'] = bbs_messages
            log_data['messages_waiting'] = messages_waiting

        gps_match = re.search(r'location data for (\d+) is ([-\d.]+),([-\d.]+)', line)
        if gps_match:
            node_id = None
            node_id, lat, lon = gps_match.groups()
            log_data['gps_coordinates'][node_id].append((float(lat), float(lon)))
        
        # get telemetry data
        if '| Telemetry:' in line:
            telemetry_match = re.search(r'Telemetry:(\d+) numPacketsRx:(\d+) numPacketsRxErr:(\d+) numPacketsTx:(\d+) numPacketsTxErr:(\d+) ChUtil%:(\d+\.\d+) AirTx%:(\d+\.\d+) totalNodes:(\d+) Online:(\d+) Uptime:(\d+d) Volt:(\d+\.\d+) Firmware:(\d+\.\d+\.\d+\.\w+)', line)
            if telemetry_match:
                interface_number, numPacketsRx, numPacketsRxErr, numPacketsTx, numPacketsTxErr, ChUtil, AirTx, totalNodes, online, uptime, volt, firmware_version = telemetry_match.groups()
                data = f"Tx: {numPacketsTx} Rx: {numPacketsRx} Uptime: {uptime} Volt: {volt} numPacketsRxErr: {numPacketsRxErr} numPacketsTxErr: {numPacketsTxErr} ChUtil: {ChUtil} AirTx: {AirTx} totalNodes: {totalNodes} Online: {online}"
                if interface_number == '1':
                    log_data['firmware1_version'] = firmware_version
                    log_data['node1_uptime'] = data
                    log_data['nodeCount1'] = totalNodes
                    log_data['nodeCountOnline1'] = online
                    log_data['tx1'] = numPacketsTx
                    log_data['rx1'] = numPacketsRx
                elif interface_number == '2':
                    log_data['firmware2_version'] = firmware_version
                    log_data['node2_uptime'] = data
                    log_data['nodeCount2'] = totalNodes
                    log_data['nodeCountOnline2'] = online
                    log_data['tx2'] = numPacketsTx
                    log_data['rx2'] = numPacketsRx

        # get name and nodeID for devices
        if 'Autoresponder Started for Device' in line:
            device_match = re.search(r'Autoresponder Started for Device(\d+)\s+([^\s,]+).*?NodeID: (\d+)', line)
            if device_match:
                device_id = device_match.group(1)
                device_name = device_match.group(2)
                node_id = device_match.group(3)
                if device_id == '1':
                    log_data['node1_name'] = device_name
                    log_data['node1_ID'] = node_id
                elif device_id == '2':
                    log_data['node2_name'] = device_name
                    log_data['node2_ID'] = node_id

    log_data['unique_users'] = list(log_data['unique_users'])
    log_data['unique_users'].reverse()
    return log_data

def get_system_info():
    def get_command_output(command):
        try:
            return subprocess.check_output(command, shell=True).decode('utf-8').strip()
        except subprocess.CalledProcessError:
            return "N/A"
        
    # Capture some system information from log_data
    firmware1_version = log_data['firmware1_version']
    firmware2_version = log_data['firmware2_version']
    node1_uptime = log_data['node1_uptime']
    node2_uptime = log_data['node2_uptime']
    node1_name = log_data['node1_name']
    node2_name = log_data['node2_name']
    node1_ID = log_data['node1_ID']
    node2_ID = log_data['node2_ID']

    print(f"Node1: {node1_name} {node1_ID} {firmware1_version}")
    print(f"Node2: {node2_name} {node2_ID} {firmware2_version}")

    # get Meshtastic CLI version on web
    try:
        url = "https://pypi.org/pypi/meshtastic/json"
        data = requests.get(url, timeout=5).json()
        pypi_version = data["info"]["version"]
        cli_web = f"v{pypi_version}"
    except Exception:
        pass
    # get Meshtastic CLI version on local
    try:
        if "importlib.metadata" in sys.modules:
            cli_local = version("meshtastic")
    except:
        pass # Python 3.7 and below, meh.. 


    if platform.system() == "Linux":
        uptime = get_command_output("uptime -p")
        memory_total = get_command_output("free -m | awk '/Mem:/ {print $2}'")
        memory_available = get_command_output("free -m | awk '/Mem:/ {print $7}'")
        disk_total = get_command_output("df -h / | awk 'NR==2 {print $2}'")
        disk_free = get_command_output("df -h / | awk 'NR==2 {print $4}'")
    elif platform.system() == "Darwin":  # macOS
        uptime = get_command_output("uptime | awk '{print $3,$4,$5}'")
        memory_total = get_command_output("sysctl -n hw.memsize | awk '{print $0/1024/1024}'")
        memory_available = "N/A"  # Not easily available on macOS without additional tools
        disk_total = get_command_output("df -h / | awk 'NR==2 {print $2}'")
        disk_free = get_command_output("df -h / | awk 'NR==2 {print $4}'")
    else:
        return {
            'uptime': "N/A",
            'memory_total': "N/A",
            'memory_available': "N/A",
            'disk_total': "N/A",
            'disk_free': "N/A",
            'interface1_version': "N/A",
            'interface2_version': "N/A",
            'node1_uptime': "N/A",
            'node2_uptime': "N/A",
            'node1_name': "N/A",
            'node2_name': "N/A",
            'node1_ID': "N/A",
            'node2_ID': "N/A",
            'cli_web': "N/A",
            'cli_local': "N/A"
        }

    return {
        'uptime': uptime,
        'memory_total': f"{memory_total} MB",
        'memory_available': f"{memory_available} MB" if memory_available != "N/A" else "N/A",
        'disk_total': disk_total,
        'disk_free': disk_free,
        'interface1_version': firmware1_version,
        'interface2_version': firmware2_version,
        'node1_uptime': node1_uptime,
        'node2_uptime': node2_uptime,
        'node1_name': node1_name,
        'node2_name': node2_name,
        'node1_ID': node1_ID,
        'node2_ID': node2_ID,
        'cli_web': cli_web,
        'cli_local': cli_local
    }

def get_wall_of_shame():
    # Get the wall of shame out of the log data
    logShameList = log_data['shameList']

    # future space for other ideas

    return {
        'shame': ', '.join(shameWordList),
        'shameList': '\n'.join(f'<li>{line}</li>' for line in logShameList),
    }

def get_database_info():
    # ../config.ini location to script path
    config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'config.ini')
    # get config.ini variables
    config = configparser.ConfigParser()
    config.read(config_path)
    # for section in config.sections():
    #     print(f"Section: {section}")
    #     for key in config[section]:
    #         print(f"Key: {key}, Value: {config[section][key]}")
    banList = config['bbs'].get('bbs_ban_list', 'none')
    adminList = config['bbs'].get('bbs_admin_list', 'none')
    sentryIgnoreList = config['sentry'].get('sentryIgnoreList', 'none')

    # Define the base directory
    base_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'data'))

    # data files
    databaseFiles = [os.path.join(base_dir, 'lemonstand_hs.pkl'),
                     os.path.join(base_dir, 'dopewar_hs.pkl'),
                     os.path.join(base_dir, 'blackjack_hs.pkl'),
                     os.path.join(base_dir, 'videopoker_hs.pkl'),
                     os.path.join(base_dir, 'mmind_hs.pkl'),
                     os.path.join(base_dir, 'golfsim_hs.pkl'),
                     os.path.join(base_dir, 'bbsdb.pkl'),
                     os.path.join(base_dir, 'bbsdm.pkl'),
                     os.path.join(base_dir, 'qrz.db')]
    
    for file in databaseFiles:
        try:
            with open(file, 'rb') as f:
                if 'lemonstand' in file:
                    lemon_score = pickle.load(f)
                elif 'dopewar' in file:
                    dopewar_score = pickle.load(f)
                elif 'blackjack' in file:
                    blackjack_score = pickle.load(f)
                elif 'videopoker' in file:
                    videopoker_score = pickle.load(f)
                elif 'mmind' in file:
                    mmind_score = pickle.load(f)
                elif 'golfsim' in file:
                    golfsim_score = pickle.load(f)
                elif 'bbsdb' in file:
                    bbsdb = pickle.load(f)
                elif 'bbsdm' in file:
                    bbsdm = pickle.load(f)
                elif 'qrz.db' in file:
                    #open the qrz.db sqllite file 
                    import sqlite3
                    conn = sqlite3.connect(file)
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM qrz")
                    qrz_db = cursor.fetchall()
                    # convert to a list of strings
                    qrz_db = [f"{row[0]}: {row[1]} {row[2]}" for row in qrz_db]
                    conn.close()
        except Exception as e:
            print(f"Warning issue reading database file: {str(e)}")
            if 'lemonstand' in file:
                lemon_score = "no data"
            elif 'dopewar' in file:
                dopewar_score = "no data"
            elif 'blackjack' in file:
                blackjack_score = "no data"
            elif 'videopoker' in file:
                videopoker_score = "no data"
            elif 'mmind' in file:
                mmind_score = "no data"
            elif 'golfsim' in file:
                golfsim_score = "no data"
            elif 'bbsdb' in file:
                bbsdb = "no data"
            elif 'bbsdm' in file:
                bbsdm = "no data"

    # pretty print the bbsdb
    prettyBBSdb = ""
    try:
        for i in range(len(bbsdb)):
            prettyBBSdb += f'<li>{bbsdb[i]}</li>'
    except Exception as e:
        print(f"Error with database: {str(e)}")
        pass

    # pretty print the bbsdm
    prettyBBSdm = ""
    try:
        for i in range(len(bbsdm)):
            prettyBBSdm += f'<li>{bbsdm[i]}</li>'
    except Exception as e:
        print(f"Error with database: {str(e)}")
        pass

    if 'no data' in [lemon_score, dopewar_score, blackjack_score, videopoker_score, mmind_score, golfsim_score]:
        database = "Error(s) Detected"
    else:
        database = " Online"

    return {
        'database': database,
        "bbsdb": prettyBBSdb,
        "bbsdm": prettyBBSdm,
        'lemon_score': lemon_score,
        'dopewar_score': dopewar_score,
        'blackjack_score': blackjack_score,
        'videopoker_score': videopoker_score,
        'mmind_score': mmind_score,
        'golfsim_score': golfsim_score,
        'banList': banList,
        'adminList': adminList,
        'sentryIgnoreList': sentryIgnoreList,
        'qrz_db': qrz_db if 'qrz_db' in locals() else "no data"
    }

def generate_main_html(log_data, system_info):
    html_template = """
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MeshBot (BBS) Web Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --background-color: #ecf0f1;
            --card-background: #ffffff;
            --text-color: #34495e;
            --sidebar-text-color: #ecf0f1;
            --accent-color-1: #e74c3c;
            --accent-color-2: #2ecc71;
            --accent-color-3: #f39c12;
            --shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            --transition: all 0.3s ease;
        }

        [data-theme="dark"] {
            --primary-color: #1a2639;
            --secondary-color: #2980b9;
            --background-color: #2c3e50;
            --card-background: #34495e;
            --text-color: #ecf0f1;
            --sidebar-text-color: #ecf0f1;
            --accent-color-1: #c0392b;
            --accent-color-2: #27ae60;
            --accent-color-3: #d35400;
            --shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }

        [data-theme="high-contrast"] {
            --primary-color: #000000;
            --secondary-color: #000000;
            --background-color: #000000;
            --card-background: #000000;
            --text-color: #ffffff;
            --sidebar-text-color: #ffffff;
            --accent-color-1: #ff0000;
            --accent-color-2: #00ff00;
            --accent-color-3: #ffff00;
            --shadow: 0 0 0 2px #ffffff;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--background-color);
            color: var(--text-color) !important;
            line-height: 1.6;
            transition: var(--transition);
        }

        .header {
            background-color: var(--secondary-color);
            color: var(--sidebar-text-color);
            padding: 1rem;
            font-size: 1.5rem;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1000;
            box-shadow: var(--shadow);
            }
                
        .main-container {
            display: flex;
            margin-top: 3.5rem;
            }

        .sidebar {
            width: 250px;
            background-color: var(--secondary-color);
            padding: 1rem;
            height: calc(100vh - 3.5rem);
            position: fixed;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: var(--shadow);
            transition: var(--transition);
        }

        .sidebar:hover {
            width: 270px;
        }

        .sidebar-nav ul {
            list-style-type: none;
        }

        .sidebar-nav li {
            margin-bottom: 1rem;
        }

        .sidebar-nav a {
            color: var(--sidebar-text-color);
            text-decoration: none;
            font-weight: 400;
            transition: var(--transition);
            display: block;
            padding: 0.5rem;
            border-radius: 4px;
        }

        .sidebar-nav a:hover {
            background-color: rgba(255, 255, 255, 0.1);
            transform: translateX(5px);
        }

        .sidebar-footer {
            font-size: 0.75rem;
            color: var(--sidebar-text-color);
            opacity: 0.8;
        }

        .content {
            margin-left: 250px;
            padding: 1rem;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            flex-grow: 1;
            background-color: var(--background-color);
            transition: var(--transition);
            color: var(--text-color);
        }

        .chart-container {
            background-color: var(--card-background);
            border-radius: 8px;
            padding: 1.5rem;
            height: 400px;
            display: flex;
            flex-direction: column;
            box-shadow: var(--shadow);
            transition: var(--transition);
        }

        .chart-container:hover {
            transform: translateY(-5px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }

        .chart-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text-color);
        }

        #map, .chart-content {
            flex-grow: 1;
            width: 100%;
            border-radius: 4px;
            overflow: hidden;
        }

        .list-container {
            background-color: var(--card-background);
            border-radius: 8px;
            padding: 1.5rem;
            height: 400px;
            overflow-y: auto;
            box-shadow: var(--shadow);
            transition: var(--transition);
        }

        .list-container:hover {
            transform: translateY(-5px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }

        ul {
            list-style-type: none;
        }

        li {
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--background-color);
            transition: var(--transition);
        }

        li:last-child {
            border-bottom: none;
        }

        li:hover {
            background-color: rgba(255, 255, 255, 0.05);
            padding-left: 0.5rem;
        }

        #iframe-content {
            display: none;
            position: fixed;
            top: 3.5rem;
            left: 250px;
            right: 0;
            bottom: 0;
            background: var(--card-background);
            background-color: var(--card-background);
            z-index: 900;
            box-shadow: var(--shadow);
            color: var(--text-color);
        }

        iframe {
            width: 100%;
            height: 100%;
            border: none;
            background-color: var(--card-background);
            color: var(--text-color);
        }

        .timestamp-list {
            height: 400px;
            overflow-y: auto;
            font-size: 0.85rem;
        }

        .theme-switch {
            display: flex;
            align-items: center;
            margin-top: 1rem;
        }

        .theme-switch-label {
            margin-right: 10px;
            color: var(--sidebar-text-color);
        }

        .switch {
            position: relative;
            display: inline-block;
            width: 60px;
            height: 34px;
        }

        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 34px;
        }

        .slider:before {
            position: absolute;
            content: "";
            height: 26px;
            width: 26px;
            left: 4px;
            bottom: 4px;
            transition: .4s;
            background-color: white;
            border-radius: 50%;
        }

        input:checked + .slider {
            background-color: var(--accent-color-2);
        }

        input:checked + .slider:before {
            transform: translateX(26px);
        }

        @media (max-width: 768px) {
            .sidebar {
                width: 100%;
                height: auto;
                position: static;
            }

            .content {
                margin-left: 0;
                grid-template-columns: 1fr;
            }

            #iframe-content {
                left: 0;
            }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        .chart-container, .list-container {
            animation: fadeIn 0.5s ease-out;
        }
    </style>
</head>
<body>
    <header class="header">MeshBot (BBS) Web Dashboard</header>
    <div class="main-container">
        <nav class="sidebar">
            <div class="sidebar-nav">
                <ul>
                    <li><a href="#" onclick="showDashboard(); return false;">Dashboard</a></li>
                    <li><a href="#" onclick="showIframe('network_map_${date}.html'); return false;">Network Map</a></li>
                    <li><a href="#" onclick="showIframe('wall_of_shame_${date}.html'); return false;">Wall of Shame</a></li>
                    <li><a href="#" onclick="showIframe('database_${date}.html'); return false;">Database Info</a></li>
                    <li><a href="#" onclick="showIframe('hosts_${date}.html'); return false;">Host</a></li>
                </ul>
                <div class="theme-switch">
                    <span class="theme-switch-label">Theme:</span>
                    <label class="switch">
                        <input type="checkbox" id="theme-toggle">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
            <div class="sidebar-footer">
                <p>&copy; 2024 MeshBot Dashboard</p>
                <p>Version 1.0</p>
            </div>
        </nav>
        <main class="content" id="dashboard-content">
            <section class="chart-container">
                <h2 class="chart-title">Node Locations</h2>
                <div id="map"></div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Network Activity</h2>
                <div class="chart-content">
                    <canvas id="activityChart"></canvas>
                </div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Command Usage</h2>
                <div class="chart-content">
                    <canvas id="commandChart"></canvas>
                </div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Message Types</h2>
                <div class="chart-content">
                    <canvas id="messageChart"></canvas>
                </div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Message Counts</h2>
                <div class="chart-content">
                    <canvas id="messageCountChart"></canvas>
                </div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Recent Commands</h2>
                <div class="timestamp-list">
                    <ul>
                        ${command_timestamps}
                    </ul>
                </div>
            </section>
            <section class="chart-container">
                <h2 class="chart-title">Recent Messages</h2>
                <div class="timestamp-list">
                    <ul>
                        ${message_timestamps}
                    </ul>
                </div>
            </section>
            <section class="list-container">
                <h2 class="chart-title">Unique Users</h2>
                <ul>
                    ${unique_users}
                </ul>
            </section>
            <section class="list-container">
                <h2 class="chart-title">Warnings</h2>
                <ul>
                    ${warnings}
                </ul>
            </section>
            <section class="list-container">
                <h2 class="chart-title">Errors</h2>
                <ul>
                    ${errors}
                </ul>
            </section>
        </main>
        <div id="iframe-content">
            <iframe id="content-iframe" src=""></iframe>
        </div>
    </div>
    <script>
        const commandData = ${command_data};
        const messageData = ${message_data};
        const activityData = ${activity_data};
        const messageCountData = {
            labels: ['BBSdm Messages', 'BBSdb Messages', 'Channel Messages'],
            datasets: [{
                label: 'Message Counts',
                data: [${messages_waiting}, ${bbs_messages}, ${total_messages}],
                backgroundColor: ['rgba(255, 206, 86, 0.6)', 'rgba(75, 192, 192, 0.6)', 'rgba(54, 162, 235, 0.6)']
            }]
        };

        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false
        };

        function createCharts() {
            new Chart(document.getElementById('commandChart'), {
                type: 'bar',
                data: {
                    labels: Object.keys(commandData),
                    datasets: [{
                        label: 'Command Usage',
                        data: Object.values(commandData),
                        backgroundColor: 'rgba(75, 192, 192, 0.6)'
                    }]
                },
                options: chartOptions
            });

            new Chart(document.getElementById('messageChart'), {
                type: 'pie',
                data: {
                    labels: Object.keys(messageData),
                    datasets: [{
                        data: Object.values(messageData),
                        backgroundColor: ['rgba(255, 99, 132, 0.6)', 'rgba(54, 162, 235, 0.6)']
                    }]
                },
                options: chartOptions
            });

            new Chart(document.getElementById('activityChart'), {
                type: 'line',
                data: {
                    labels: Object.keys(activityData),
                    datasets: [{
                        label: 'Hourly Activity',
                        data: Object.entries(activityData).map(([time, count]) => ({x: new Date(time), y: count})),
                        borderColor: 'rgba(153, 102, 255, 1)',
                        fill: false
                    }]
                },
options: {
                    ...chartOptions,
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'hour',
                                displayFormats: {
                                    hour: 'MMM d, HH:mm'
                                }
                            },
                            title: {
                                display: true,
                                text: 'Time'
                            }
                        },
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Activity Count'
                            }
                        }
                    }
                }
            });

            new Chart(document.getElementById('messageCountChart'), {
                type: 'bar',
                data: messageCountData,
                options: {
                    ...chartOptions,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }

        function initMap() {
            var map = L.map('map').setView([0, 0], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);
        
            var gpsCoordinates = ${gps_coordinates};
            var bounds = [];
            var defaultCoordinate = [0, 0]; // Set your default coordinate here
        
            for (var nodeId in gpsCoordinates) {
                if (gpsCoordinates[nodeId] && gpsCoordinates[nodeId][0]) {
                    var coords = gpsCoordinates[nodeId][0];
                    L.marker(coords).addTo(map)
                        .bindPopup("Node ID: " + nodeId);
                    bounds.push(coords);
                } else {
                    // Optionally, handle the case where coordinates are missing
                    // bounds.push(defaultCoordinate);
                }
            }
        
            if (bounds.length > 0) {
                map.fitBounds(bounds);
            } else {
                // Optionally, set the view to the default coordinate if no valid bounds are found
                map.setView(defaultCoordinate, 2);
            }
        }

        function showIframe(src) {
            document.getElementById('dashboard-content').style.display = 'none';
            document.getElementById('iframe-content').style.display = 'block';
            document.getElementById('content-iframe').src = src;
        }

        function showDashboard() {
            document.getElementById('dashboard-content').style.display = 'grid';
            document.getElementById('iframe-content').style.display = 'none';
            document.getElementById('content-iframe').src = '';
        }

        const themes = ['light', 'dark', 'high-contrast'];
        let currentThemeIndex = themes.indexOf(localStorage.getItem('theme') || 'light');

        function cycleTheme() {
            currentThemeIndex = (currentThemeIndex + 1) % themes.length;
            const newTheme = themes[currentThemeIndex];
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateCharts();
            updateSwitchState();
        }

        function updateSwitchState() {
            const switchElement = document.getElementById('theme-toggle');
            switchElement.checked = currentThemeIndex !== 0;
        }

        function updateCharts() {
            const theme = document.documentElement.getAttribute('data-theme');
            const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-color').trim();
            
            Chart.helpers.each(Chart.instances, function(chart) {
                chart.options.plugins.legend.labels.color = textColor;
                chart.options.scales.x.ticks.color = textColor;
                chart.options.scales.y.ticks.color = textColor;
                chart.update();
            });
        }

        document.addEventListener('DOMContentLoaded', function() {
            createCharts();
            initMap();

            const savedTheme = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-theme', savedTheme);
            currentThemeIndex = themes.indexOf(savedTheme);
            updateSwitchState();
            updateCharts();

            document.getElementById('theme-toggle').addEventListener('change', cycleTheme);
        });
    </script>
</body>
</html>    
"""

    template = Template(html_template)
    return template.safe_substitute(
        date=datetime.now().strftime('%Y-%m-%d'),
        command_data=json.dumps(log_data['command_counts']),
        message_data=json.dumps(log_data['message_types']),
        activity_data=json.dumps(log_data['hourly_activity']),
        bbs_messages=log_data['bbs_messages'],
        messages_waiting=log_data['messages_waiting'],
        total_messages=log_data['total_messages'],
        total_llm_queries=log_data['message_types']['LLM Query'],
        gps_coordinates=json.dumps(log_data['gps_coordinates']),
        unique_users='\n'.join(f'<li>{user}</li>' for user in log_data['unique_users']),
        warnings='\n'.join(f'<li>{warning}</li>' for warning in log_data['warnings']),
        errors='\n'.join(f'<li>{error}</li>' for error in log_data['errors']),
        command_timestamps='\n'.join(f'<li>{timestamp}: {cmd}</li>' for timestamp, cmd in reversed(log_data['command_timestamps'][-50:])),
        message_timestamps='\n'.join(f'<li>{timestamp}: {msg_type}</li>' for timestamp, msg_type in reversed(log_data['message_timestamps'][-50:]))
    )

def generate_network_map_html(log_data):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Network Map</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        <style>
            body { margin: 0; padding: 0; }
            #map { position: absolute; top: 0; bottom: 0; width: 100%; }
        </style>
    </head>
    <body>
        <div id="map"></div>
        <script>
            var map = L.map('map').setView([0, 0], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);

            var gpsCoordinates = ${gps_coordinates};
            for (var nodeId in gpsCoordinates) {
                var coords = gpsCoordinates[nodeId][0];
                L.marker(coords).addTo(map)
                    .bindPopup("Node ID: " + nodeId);
            }

            var bounds = [];
            for (var nodeId in gpsCoordinates) {
                bounds.push(gpsCoordinates[nodeId][0]);
            }
            map.fitBounds(bounds);
        </script>
    </body>
    </html>
    """

    template = Template(html_template)
    return template.safe_substitute(gps_coordinates=json.dumps(log_data['gps_coordinates']))

def generate_sys_hosts_html(system_info):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Host Information</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }
            h1 { color: #00ff00; }
            table { border-collapse: collapse; width: 100%; background-color: #d3d3d3; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <h1>System Host Information</h1>
        <table>
            <tr><th>OS Metric</th><th>Value</th></tr>
            <tr><td>Uptime</td><td>${uptime}</td></tr>
            <tr><td>Total Memory</td><td>${memory_total}</td></tr>
            <tr><td>Available Memory</td><td>${memory_available}</td></tr>
            <tr><td>Total Disk Space</td><td>${disk_total}</td></tr>
            <tr><td>Free Disk Space</td><td>${disk_free}</td></tr>
            <tr><th>Meshtastic Metric</th><th>Value</th></tr>
            <tr><td>API Version/Latest</td><td>${cli_local} / ${cli_web}</td></tr>
            <tr><td>Int1 Name ID</td><td>${node1_name} (${node1_ID})</td></tr>
            <tr><td>Int1 Stat</td><td>${node1_uptime}</td></tr>
            <tr><td>Int1 FW Version</td><td>${interface1_version}</td></tr>
            <tr><td>Int2 Name ID</td><td>${node2_name} (${node2_ID})</td></tr>
            <tr><td>Int2 Stat</td><td>${node2_uptime}</td></tr>
            <tr><td>Int2 FW Version</td><td>${interface2_version}</td></tr>
        </table>
    </body>
    </html>
    """

    template = Template(html_template)
    return template.safe_substitute(system_info)

def generate_wall_of_shame_html(shame_info):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Wall Of Shame</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }
            h1 { color: #00ff00; }
            table { border-collapse: collapse; width: 100%; background-color: #d3d3d3; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <h1>Collected Shame</h1>
        <table>
            <tr><th>Shame Metric</th><th>Value</th></tr>
            <tr><td>Shamefull words</td><td>${shame}</td></tr>
            <tr><td>Shamefull messages</td><td>${shameList}</td></tr>
        </table>
    </body>
    </html>
    """

    template = Template(html_template)
    return template.safe_substitute(shame_info)

def generate_database_html(database_info):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Database Information</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }
            h1 { color: #00ff00; }
            table { border-collapse: collapse; width: 100%; background-color: #d3d3d3; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <h1>Database Information</h1>
        <p>Conection ${database}. I cant see this text on dark mode</p>
        <table>
            <tr><th>config.ini Settings</th><th>Value</th></tr>
            <tr><td>Admin List</td><td>${adminList}</td></tr>
            <tr><td>Ban List</td><td>${banList}</td></tr>
            <tr><td>Sentry Ignore List</td><td>${sentryIgnoreList}</td></tr>
        </table>
        <h1>BBS Message Database</h1>
        <table>
            <tr><th>Database</th><th>Contents</th></tr>
            <tr><td>BBSdb</td><td>${bbsdb}</td></tr>
            <tr><td>BBSdm</td><td>${bbsdm}</td></tr>
        </table>
        <h1>High Scores</h1>
        <table>
            <tr><th>Game</th><th>High Score</th></tr>
            <tr><td>Lemonade Stand</td><td>${lemon_score}</td></tr>
            <tr><td>Dopewars</td><td>${dopewar_score}</td></tr>
            <tr><td>Blackjack</td><td>${blackjack_score}</td></tr>
            <tr><td>Video Poker</td><td>${videopoker_score}</td></tr>
            <tr><td>Mastermind</td><td>${mmind_score}</td></tr>
            <tr><td>Golf Simulator</td><td>${golfsim_score}</td></tr>
        </table>
        <h1>QRZ Database</h1>
        <p>QRZ Database holds heard nodeID and Shortname</p>
        <table>
            <tr><td>${qrz_db}</td></tr>
        </table>
    </body>
    </html>
    """

    template = Template(html_template)
    return template.safe_substitute(database_info)

def main():
    # Log file
    log_dir = LOG_PATH
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = f'meshbot.log'
    log_path = os.path.join(log_dir, log_file)

    if not os.path.exists(log_path):
        # set file_path to the cwd of the default project ../log
        file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'logs')
        file_path = os.path.abspath(file_path)
        log_path = os.path.join(file_path, log_file)

    log_data = parse_log_file(log_path)
    system_info = get_system_info()
    shame_info = get_wall_of_shame()
    database_info = get_database_info()

    main_html = generate_main_html(log_data, system_info)
    network_map_html = generate_network_map_html(log_data)
    hosts_html = generate_sys_hosts_html(system_info)
    wall_of_shame = generate_wall_of_shame_html(shame_info)
    database_html = generate_database_html(database_info)

    output_dir = W3_PATH
    index_path = os.path.join(output_dir, 'index.html')

    print(f"\n\nMeshBot (BBS) Web Dashboard Report Generator")
    print(f"\nMain dashboard: file://{index_path}\n")
    
    try:
        if not os.path.exists(output_dir):
            output_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'www')
            output_dir = os.path.abspath(output_dir)
            index_path = os.path.join(output_dir, 'index.html')

        # Create backup of existing index.html if it exists
        if os.path.exists(index_path):
            backup_path = os.path.join(output_dir, f'index_backup_{today}.html')
            os.rename(index_path, backup_path)
            print(f"Existing index.html backed up to {backup_path}")

        # Write main HTML to index.html
        with open(index_path, 'w') as f:
            f.write(main_html)
        print(f"Main dashboard written to {index_path}")

        # Write other HTML files
        with open(os.path.join(output_dir, f'network_map_{today}.html'), 'w') as f:
            f.write(network_map_html)
        
        with open(os.path.join(output_dir, f'hosts_{today}.html'), 'w') as f:
            f.write(hosts_html)

        with open(os.path.join(output_dir, f'wall_of_shame_{today}.html'), 'w') as f:
            f.write(wall_of_shame)
        
        with open(os.path.join(output_dir, f'database_{today}.html'), 'w') as f:
            f.write(database_html)

        print(f"HTML reports generated for {today} in {output_dir}")

    except PermissionError:
        print("Error: Permission denied. Please run the script with appropriate permissions (e.g., using sudo).")
    except Exception as e:
        print(f"An error occurred while writing the output: {str(e)}")

if __name__ == "__main__":
    main()