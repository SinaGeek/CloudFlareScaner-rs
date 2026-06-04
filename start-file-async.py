import os
import sys
import requests
import json
import ipaddress
import re
import random
import time
import configparser
import subprocess
import asyncio
import aiohttp
import socket
from typing import List, Optional, Tuple, Dict, Set

print_ping_error_message = False
openssl_is_active = False

try:
    import ping3
except ImportError:
    print_ping_error_message = True


# -------------------------------------------------------------------
# Custom resolver for aiohttp
# -------------------------------------------------------------------
class SingleHostResolver:
    def __init__(self, ip: str, host: str = 'speed.cloudflare.com'):
        self.ip = ip
        self.host = host

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        if host == self.host:
            return [{
                'hostname': host,
                'host': self.ip,
                'port': port,
                'family': family or socket.AF_INET,
                'proto': socket.IPPROTO_TCP,
                'flags': socket.AI_NUMERICHOST,
            }]
        from aiohttp.resolver import AsyncResolver
        resolver = AsyncResolver()
        return await resolver.resolve(host, port, family)


# -------------------------------------------------------------------
# Async helpers
# -------------------------------------------------------------------
async def async_ping_loss(ip: str, timeout: float, count: int = 5) -> Tuple[float, float]:
    try:
        results = []
        for _ in range(count):
            try:
                resp = await asyncio.to_thread(ping3.ping, ip, timeout=timeout)
                if resp is not None and resp > 0:
                    results.append(resp * 1000)
            except Exception:
                pass
        if not results:
            return -1, 1.0
        avg_ping = sum(results) / len(results)
        loss = 1.0 - (len(results) / count)
        return avg_ping, loss
    except Exception:
        return -1, 1.0


async def async_latency_jitter(ip: str, acceptable_latency: int) -> Tuple[int, int]:
    download_size = 1000
    url = f"https://speed.cloudflare.com/__down?bytes={download_size}"
    headers = {'Host': 'speed.cloudflare.com'}
    timeout = aiohttp.ClientTimeout(total=(acceptable_latency / 1000) * 1.5)
    resolver = SingleHostResolver(ip)

    latencies = []
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=resolver, ssl=False),
            timeout=timeout
        ) as session:
            for _ in range(4):
                start = time.time()
                async with session.get(url, headers=headers) as resp:
                    await resp.read()
                latencies.append((time.time() - start) * 1000)
    except Exception:
        return 99999, -1

    avg_latency = int(sum(latencies) / len(latencies))
    jitter = int(sum(abs(latencies[i] - latencies[i-1]) for i in range(1, len(latencies))) / (len(latencies)-1)) if len(latencies) > 1 else 0
    return avg_latency, jitter


# -------------------------------------------------------------------
# Synchronous speed test functions
# -------------------------------------------------------------------
def getDownloadSpeed(ip, size, min_speed):
    global openssl_is_active
    download_size = size * 1024
    min_speed_bytes = min_speed * 125000
    timeout = download_size / min_speed_bytes
    url = f"https://speed.cloudflare.com/__down?bytes={download_size}"
    headers = {'Host': 'speed.cloudflare.com'}
    if openssl_is_active:
        params = {'resolve': f"speed.cloudflare.com:443:{ip}", 'alpn': 'h2,http/1.1', 'utls': 'random'}
    else:
        params = {'resolve': f"speed.cloudflare.com:443:{ip}"}
    try:
        start_time = time.time()
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        download_time = time.time() - start_time
        download_speed = round(download_size / download_time * 8 / 1000000, 2)
    except requests.exceptions.RequestException:
        download_speed = 0
    return download_speed


def getUploadSpeed(ip, size, min_speed):
    global openssl_is_active
    upload_size = int(size * 1024 / 4)
    min_speed_bytes = min_speed * 125000
    timeout = upload_size / min_speed_bytes
    url = 'https://speed.cloudflare.com/__up'
    headers = {'Content-Type': 'multipart/form-data', 'Host': 'speed.cloudflare.com'}
    if openssl_is_active:
        params = {'resolve': f"speed.cloudflare.com:443:{ip}", 'alpn': 'h2,http/1.1', 'utls': 'random'}
    else:
        params = {'resolve': f"speed.cloudflare.com:443:{ip}"}
    files = {'file': ('sample.bin', b"\x55" * upload_size)}
    try:
        start_time = time.time()
        response = requests.post(url, headers=headers, params=params, files=files, timeout=timeout)
        upload_time = time.time() - start_time
        upload_speed = round(upload_size / upload_time * 8 / 1000000, 2)
    except requests.exceptions.RequestException:
        upload_speed = 0
    return upload_speed


# -------------------------------------------------------------------
# Cloudflare functions
# -------------------------------------------------------------------
def validateCloudflareCredentials(email, api_key, zone_id):
    headers = {
        "X-Auth-Email": email,
        "X-Auth-Key": api_key,
        "Content-Type": "application/json"
    }
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    response = requests.get(url, headers=headers)
    return response.status_code == 200


def getCloudflareExistingRecords(email, api_key, zone_id, subdomain):
    headers = {
        "X-Auth-Email": email,
        "X-Auth-Key": api_key,
        "Content-Type": "application/json"
    }
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&name={subdomain}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return json.loads(response.text)["result"]


def deleteCloudflareExistingRecord(email, api_key, zone_id, record_id):
    headers = {
        "X-Auth-Email": email,
        "X-Auth-Key": api_key,
        "Content-Type": "application/json"
    }
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    response = requests.delete(url, headers=headers)
    response.raise_for_status()


def addNewCloudflareRecord(email, api_key, zone_id, subdomain, ip):
    headers = {
        "X-Auth-Email": email,
        "X-Auth-Key": api_key,
        "Content-Type": "application/json"
    }
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    data = {
        "type": "A",
        "name": subdomain,
        "content": ip,
        "ttl": 3600,
        "proxied": False
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()


def has_openssl():
    try:
        subprocess.check_call(["openssl", "version"], stdout=subprocess.PIPE)
        return True
    except:
        return False


# -------------------------------------------------------------------
# IPInfo class with serialization
# -------------------------------------------------------------------
class IPInfo:
    def __init__(self, ip, ping, jitter, latency, packet_loss, upload, download):
        self.ip = ip
        self.ping = ping
        self.jitter = jitter
        self.latency = latency
        self.packet_loss = packet_loss
        self.upload = upload
        self.download = download

    def to_dict(self):
        return {
            'ip': self.ip,
            'ping': self.ping,
            'jitter': self.jitter,
            'latency': self.latency,
            'packet_loss': self.packet_loss,
            'upload': self.upload,
            'download': self.download
        }

    @staticmethod
    def from_dict(d):
        return IPInfo(d['ip'], d['ping'], d['jitter'], d['latency'],
                      d['packet_loss'], d['upload'], d['download'])


# -------------------------------------------------------------------
# Random IP generator (range first, then IP)
# -------------------------------------------------------------------
def random_ip_generator(ranges: List[ipaddress.IPv4Network], tested_ips: Set[str], total_possible: int):
    while len(tested_ips) < total_possible:
        net = random.choice(ranges)
        ip_int = random.randint(int(net.network_address) + 1, int(net.broadcast_address) - 1)
        ip = str(ipaddress.IPv4Address(ip_int))
        if ip not in tested_ips:
            tested_ips.add(ip)
            yield ip


# -------------------------------------------------------------------
# Live table drawing (updates in-place)
# -------------------------------------------------------------------
last_table_height = 0

def print_live_table(selected_ips: List[IPInfo], testing_entry: Optional[dict] = None):
    global last_table_height
    table_str = "|---|---------------|--------|-------|-------|--------|----------|---------|\n"
    table_str += "| # |       IP      |Ping(ms)|Loss(%)|Jit(ms)|Lat(ms)|Up(Mbps)|Down(Mbps)|\n"
    table_str += "|---|---------------|--------|-------|-------|--------|----------|---------|\n"

    for i, el in enumerate(selected_ips, 1):
        loss_percent = f"{el.packet_loss*100:.1f}"
        table_str += f"|{i:3d}|{el.ip:15s}|{el.ping:7d} |{loss_percent:6s} |{el.jitter:6d} |{el.latency:6d} |{el.upload:7.2f} |{el.download:9.2f} |\n"

    if testing_entry:
        idx = len(selected_ips) + 1
        loss_percent = f"{testing_entry['packet_loss']*100:.1f}"
        table_str += f"|{idx:3d}|{testing_entry['ip']:15s}|{testing_entry['ping']:7d} |{loss_percent:6s} |{testing_entry['jitter']:6d} |{testing_entry['latency']:6d} | testing |  testing  |\n"

    table_str += "|---|---------------|--------|-------|-------|--------|----------|---------|\n"

    if last_table_height > 0:
        for _ in range(last_table_height):
            sys.stdout.write("\033[F\033[K")
    sys.stdout.write(table_str)
    sys.stdout.flush()
    last_table_height = table_str.count('\n')


# -------------------------------------------------------------------
# Stage 1: normal scan (refactored batch gather)
# -------------------------------------------------------------------
async def normal_scan(config: configparser.ConfigParser,
                      ip_gen, total_ips: int, target_valid: int) -> List[dict]:
    max_ping = int(config.get('DEFAULT', 'max_ping'))
    max_jitter = int(config.get('DEFAULT', 'max_jitter'))
    max_latency = int(config.get('DEFAULT', 'max_latency'))
    max_packet_loss = float(config.get('DEFAULT', 'max_packet_loss', fallback=0.5))

    satisfied = []
    sem = asyncio.Semaphore(100)
    checked = 0

    async def check_ip(ip: str) -> Optional[dict]:
        async with sem:
            ping_timeout = max_ping / 1000
            avg_ping, loss = await async_ping_loss(ip, ping_timeout)
            if avg_ping < 0 or avg_ping > max_ping or loss > max_packet_loss:
                return None
            latency, jitter = await async_latency_jitter(ip, max_latency)
            if jitter > max_jitter or latency > max_latency:
                return None
            return {
                'ip': ip,
                'ping': int(avg_ping),
                'jitter': jitter,
                'latency': latency,
                'packet_loss': round(loss, 4)
            }

    batch_size = 100
    while len(satisfied) < target_valid:
        tasks = []
        for _ in range(batch_size):
            try:
                ip = next(ip_gen)
                checked += 1
                tasks.append(asyncio.create_task(check_ip(ip)))
            except StopIteration:
                break

        if not tasks:
            break

        for t in asyncio.as_completed(tasks):
            try:
                res = await t
            except Exception:
                continue
            if res is not None:
                satisfied.append(res)
                if len(satisfied) >= target_valid:
                    break
        sys.stdout.write(f"\r{checked}/{total_ips} IPs checked, {len(satisfied)} valid.")
        sys.stdout.flush()

    sys.stdout.write(f"\r{checked}/{total_ips} IPs checked, {len(satisfied)} valid.\n")
    sys.stdout.flush()
    return satisfied


# -------------------------------------------------------------------
# Speed test batch with live table (normal search)
# -------------------------------------------------------------------
def speed_test_batch_live(selected_ips: List[IPInfo],
        candidates: List[dict],
        config: configparser.ConfigParser,
        max_to_add: int, min_dl: float, min_ul: float,
        already_tested_ips: Set[str],
        save_checkpoint=None) -> None:
    global last_table_height
    last_table_height = 0
    test_size = int(config.get('DEFAULT', 'test_size'))
    added = 0
    print("\nSpeed test is under progress ...")
    for entry in candidates:
        ip = entry['ip']
        if ip in already_tested_ips:
            continue
        if added >= max_to_add:
            break

        print_live_table(selected_ips, entry)

        upload = getUploadSpeed(ip, test_size, min_ul)
        if upload < min_ul:
            already_tested_ips.add(ip)
            print_live_table(selected_ips, None)
            continue

        download = getDownloadSpeed(ip, test_size, min_dl)
        if download < min_dl:
            already_tested_ips.add(ip)
            print_live_table(selected_ips, None)
            continue

        new_ip = IPInfo(ip, entry['ping'], entry['jitter'], entry['latency'],
                        entry['packet_loss'], upload, download)
        selected_ips.append(new_ip)
        added += 1
        already_tested_ips.add(ip)
        print_live_table(selected_ips, None)

    if save_checkpoint:
        save_checkpoint()
    print("\nSpeed test completed.")


# -------------------------------------------------------------------
# Extended search with live table (uses batch gather)
# -------------------------------------------------------------------
async def extended_search_live(config: configparser.ConfigParser,
                            ip_gen, total_ips: int,
                            current_averages: Dict[str, float],
                            already_speedtested: Set[str],
                            target_count: int,
                            selected_ips: List[IPInfo],
                            save_checkpoint=None):
    global last_table_height
    last_table_height = 0
    test_size = int(config.get('DEFAULT', 'test_size'))
    min_dl = float(config.get('DEFAULT', 'min_download_speed'))
    min_ul = float(config.get('DEFAULT', 'min_upload_speed'))
    max_packet_loss = float(config.get('DEFAULT', 'max_packet_loss', fallback=0.5))
    sem = asyncio.Semaphore(100)
    found = 0
    checked = 0

    async def test_and_add(entry: dict):
        nonlocal found
        ip = entry['ip']
        print_live_table(selected_ips, entry)

        upload = await asyncio.to_thread(getUploadSpeed, ip, test_size, min_ul)
        if upload < min_ul:
            already_speedtested.add(ip)
            print_live_table(selected_ips, None)
            return

        download = await asyncio.to_thread(getDownloadSpeed, ip, test_size, min_dl)
        if download < min_dl:
            already_speedtested.add(ip)
            print_live_table(selected_ips, None)
            return

        # Must be strictly better in both speeds AND pass absolute loss limit
        if upload > current_averages['upload'] and download > current_averages['download']:
            new_ip = IPInfo(ip, entry['ping'], entry['jitter'], entry['latency'],
                            entry['packet_loss'], upload, download)
            selected_ips.append(new_ip)
            found += 1
            # Update averages
            n = len(selected_ips)
            current_averages['ping'] = sum(el.ping for el in selected_ips) / n
            current_averages['loss'] = sum(el.packet_loss for el in selected_ips) / n
            current_averages['jitter'] = sum(el.jitter for el in selected_ips) / n
            current_averages['latency'] = sum(el.latency for el in selected_ips) / n
            current_averages['upload'] = sum(el.upload for el in selected_ips) / n
            current_averages['download'] = sum(el.download for el in selected_ips) / n

            if save_checkpoint:
                save_checkpoint()

        already_speedtested.add(ip)
        print_live_table(selected_ips, None)

    async def check_ip(ip: str) -> Optional[dict]:
        async with sem:
            ping_timeout = current_averages['ping'] / 1000
            avg_p, loss = await async_ping_loss(ip, ping_timeout)
            if avg_p < 0 or avg_p > current_averages['ping'] or loss > current_averages['loss'] or loss > max_packet_loss:
                return None
            lat, jit = await async_latency_jitter(ip, int(current_averages['latency']))
            if jit > current_averages['jitter'] or lat > current_averages['latency']:
                return None
            return {
                'ip': ip,
                'ping': int(avg_p),
                'jitter': jit,
                'latency': lat,
                'packet_loss': round(loss, 4)
            }

    print("\nExtended speed test is under progress ...")
    batch_size = 100
    while found < target_count:
        tasks = []
        for _ in range(batch_size):
            try:
                ip = next(ip_gen)
                checked += 1
                tasks.append(asyncio.create_task(check_ip(ip)))
            except StopIteration:
                break

        if not tasks:
            break

        for t in asyncio.as_completed(tasks):
            try:
                res = await t
            except Exception:
                continue
            if res is not None:
                await test_and_add(res)
                if found >= target_count:
                    break
        sys.stdout.write(f"\r{checked}/{total_ips} extended checked, {found}/{target_count} better found.")
        sys.stdout.flush()

    print(f"\nExtended search completed. {found} better IPs added.")


# -------------------------------------------------------------------
# Helper: print final table with average row
# -------------------------------------------------------------------
def print_final_table(selected_ips: List[IPInfo], title: str = "selected IP(s)"):
    if not selected_ips:
        print("\nNo IPs to display.")
        return
    selected_ips.sort(key=lambda x: x.download, reverse=True)
    print(f"\n{len(selected_ips)} {title} (sorted by download speed):")
    print("|---|---------------|--------|-------|-------|--------|----------|---------|")
    print("| # |       IP      |Ping(ms)|Loss(%)|Jit(ms)|Lat(ms)|Up(Mbps)|Down(Mbps)|")
    print("|---|---------------|--------|-------|-------|--------|----------|---------|")
    for i, el in enumerate(selected_ips, 1):
        loss_percent = f"{el.packet_loss*100:.1f}"
        print(f"|{i:3d}|{el.ip:15s}|{el.ping:7d} |{loss_percent:6s} |{el.jitter:6d} |{el.latency:6d} |{el.upload:7.2f} |{el.download:9.2f} |")
    avg_ping = sum(el.ping for el in selected_ips) / len(selected_ips)
    avg_loss = sum(el.packet_loss for el in selected_ips) / len(selected_ips) * 100
    avg_jitter = sum(el.jitter for el in selected_ips) / len(selected_ips)
    avg_latency = sum(el.latency for el in selected_ips) / len(selected_ips)
    avg_upload = sum(el.upload for el in selected_ips) / len(selected_ips)
    avg_download = sum(el.download for el in selected_ips) / len(selected_ips)
    print("|---|---------------|--------|-------|-------|--------|----------|---------|")
    print(f"|   |    Average    |{int(avg_ping):7d} |{avg_loss:5.1f}  |{int(avg_jitter):6d} |{int(avg_latency):6d} |{avg_upload:7.2f} |{avg_download:9.2f} |")
    print("|---|---------------|--------|-------|-------|--------|----------|---------|\n")


# -------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------
def main():
    DEFAULT_MAX_IP = 10
    DEFAULT_MAX_PING = 500
    DEFAULT_MAX_JITTER = 100
    DEFAULT_MAX_LATENCY = 1000
    DEFAULT_MAX_PACKET_LOSS = 0.5
    DEFAULT_IP_INCLUDE = ""
    DEFAULT_IP_EXCLUDE = ""
    DEFAULT_DOWNLOAD_SIZE_KB = 1024
    DEFAULT_MIN_DOWNLOAD_SPEED = 3
    DEFAULT_MIN_UPLOAD_SPEED = 0.2

    config = configparser.ConfigParser()
    config.read('config.ini')

    max_ip = int(config.get('DEFAULT', 'max_ip', fallback=DEFAULT_MAX_IP))
    max_ping = int(config.get('DEFAULT', 'max_ping', fallback=DEFAULT_MAX_PING))
    max_jitter = int(config.get('DEFAULT', 'max_jitter', fallback=DEFAULT_MAX_JITTER))
    max_latency = int(config.get('DEFAULT', 'max_latency', fallback=DEFAULT_MAX_LATENCY))
    max_packet_loss = float(config.get('DEFAULT', 'max_packet_loss', fallback=DEFAULT_MAX_PACKET_LOSS))
    ip_include = config.get('DEFAULT', 'ip_include', fallback=DEFAULT_IP_INCLUDE)
    ip_exclude = config.get('DEFAULT', 'ip_exclude', fallback=DEFAULT_IP_EXCLUDE)
    test_size = config.get('DEFAULT', 'test_size', fallback=DEFAULT_DOWNLOAD_SIZE_KB)
    min_download_speed = config.get('DEFAULT', 'min_download_speed', fallback=DEFAULT_MIN_DOWNLOAD_SPEED)
    min_upload_speed = config.get('DEFAULT', 'min_upload_speed', fallback=DEFAULT_MIN_UPLOAD_SPEED)
    default_upload_results = config.get('DEFAULT', 'upload_results', fallback='no')
    default_delete_existing = config.get('DEFAULT', 'delete_existing', fallback='yes')
    default_email = config.get('DEFAULT', 'email', fallback='')
    default_zone_id = config.get('DEFAULT', 'zone_id', fallback='')
    default_api_key = config.get('DEFAULT', 'api_key', fallback='')
    default_subdomain = config.get('DEFAULT', 'subdomain', fallback='')

    global print_ping_error_message, openssl_is_active

    delete_existing = default_delete_existing
    email = default_email
    zone_id = default_zone_id
    api_key = default_api_key
    subdomain = default_subdomain

    print("In each Stage Press CTRL+C to exit...\n This Code made by SACAN LEE an Annonymous Coder for Freedom dont share it with any one.\n")

    try:
        max_ip = input(f"Enter max IP (N) [{max_ip}]: ") or max_ip
        max_ping = input(f"Enter max ping [{max_ping}]: ") or max_ping
        max_jitter = input(f"Enter max jitter [{max_jitter}]: ") or max_jitter
        max_latency = input(f"Enter max latency [{max_latency}]: ") or max_latency
        max_packet_loss = input(f"Enter max packet loss ratio (0.0-1.0) [{max_packet_loss}]: ") or max_packet_loss
        ip_include = input(f"Enter IPs to include (comma seperated, '-' to ignore) [{ip_include}]: ") or ip_include
        ip_exclude = input(f"Enter IPs to exclude (comma seperated, '-' to ignore) [{ip_exclude}]: ") or ip_exclude
        test_size = input(f"Enter test data size in KB [{test_size}]: ") or test_size
        min_download_speed = input(f"Enter minimum download speed (Mbps) [{min_download_speed}]: ") or min_download_speed
        min_upload_speed = input(f"Enter minimum upload speed (Mbps) [{min_upload_speed}]: ") or min_upload_speed

        if ip_include == '-':
            ip_include = ''
        if ip_exclude == '-':
            ip_exclude = ''

        max_ip = int(max_ip)
        max_ping = int(max_ping)
        max_jitter = int(max_jitter)
        max_latency = int(max_latency)
        max_packet_loss = float(max_packet_loss)
        test_size = int(test_size)
        min_download_speed = float(min_download_speed)
        min_upload_speed = float(min_upload_speed)

        upload_results = input(f"Do you want to upload the result to your Cloudflare subdomain (yes/no) [{default_upload_results}]? ") or default_upload_results

        if upload_results.lower() in ["y", "yes"]:
            delete_existing = input(f"Do you want to delete extisting records of given subdomain before uploading the result to your Cloudflare (yes/no) [{default_delete_existing}]? ") or default_delete_existing
            email = input(f"Cloudflare email [{default_email}]: ") or default_email
            zone_id = input(f"Cloudflare zone ID [{default_zone_id}]: ") or default_zone_id
            api_key = input(f"Cloudflare API key [{default_api_key}]: ") or default_api_key
            subdomain = input(f"Subdomain to modify (i.e ip.my-domain.com) [{default_subdomain}]: ") or default_subdomain

            while not validateCloudflareCredentials(email, api_key, zone_id):
                print("Invalid cloudflare credentials, please try again.")
                email = input(f"Cloudflare email [{default_email}]: ") or default_email
                zone_id = input(f"Cloudflare zone ID [{default_zone_id}]: ") or default_zone_id
                api_key = input(f"Cloudflare API key [{default_api_key}]: ") or default_api_key

            while not re.match(r"^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,}$", subdomain):
                print("Invalid subdomain, please try again.")
                subdomain = input(f"Subdomain to modify (i.e ip.my-domain.com) [{default_subdomain}]: ") or default_subdomain

        os.system('cls' if os.name == 'nt' else 'clear')
        print("Configuration:")
        print(f"  Target IPs (N)   : {max_ip}")
        print(f"  Max ping         : {max_ping} ms")
        print(f"  Max jitter       : {max_jitter} ms")
        print(f"  Max latency      : {max_latency} ms")
        print(f"  Max packet loss  : {max_packet_loss*100:.0f}%")
        print(f"  Test data size   : {test_size} KB")
        print(f"  Min download     : {min_download_speed} Mbps")
        print(f"  Min upload       : {min_upload_speed} Mbps")
        print(f"  Upload results   : {upload_results}")
        print(f"  IP include filter: {ip_include if ip_include else 'none'}")
        print(f"  IP exclude filter: {ip_exclude if ip_exclude else 'none'}")
        print()

        config['DEFAULT'] = {
            'max_ip': str(max_ip),
            'max_ping': str(max_ping),
            'max_jitter': str(max_jitter),
            'max_latency': str(max_latency),
            'max_packet_loss': str(max_packet_loss),
            'ip_include': ip_include,
            'ip_exclude': ip_exclude,
            'test_size': str(test_size),
            'min_download_speed': str(min_download_speed),
            'min_upload_speed': str(min_upload_speed),
            'upload_results': upload_results,
            'delete_existing': delete_existing,
            'email': email,
            'zone_id': zone_id,
            'api_key': api_key,
            'subdomain': subdomain
        }
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        include_regex = None
        exclude_regex = None
        if ip_include:
            include_regex = re.compile('|'.join(['^' + re.escape(c).replace('.', '\\.') + '\\.' for c in ip_include.split(',')]))
        if ip_exclude:
            exclude_regex = re.compile('|'.join(['^' + re.escape(c).replace('.', '\\.') + '\\.' for c in ip_exclude.split(',')]))

        try:
            with open('ipv4.txt', 'r') as f:
                raw_lines = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print("Error: ipv4.txt not found.")
            sys.exit(1)

        ranges = []
        for line in raw_lines:
            if '/' in line:
                try:
                    net = ipaddress.ip_network(line, strict=False)
                    ranges.append(net)
                except ValueError:
                    print(f"Warning: skipping invalid CIDR: {line}")
            else:
                try:
                    ip_obj = ipaddress.ip_address(line)
                    ranges.append(ipaddress.ip_network(f"{ip_obj}/32"))
                except ValueError:
                    print(f"Warning: skipping invalid IP: {line}")

        filtered_ranges = []
        for net in ranges:
            if include_regex and not include_regex.match(str(net.network_address)):
                continue
            if exclude_regex and exclude_regex.match(str(net.network_address)):
                continue
            filtered_ranges.append(net)
        ranges = filtered_ranges

        total_possible = sum(len(list(net.hosts())) for net in ranges)
        print(f"Loaded {len(ranges)} CIDR ranges after filtering, total possible IPs: {total_possible}.")

        if print_ping_error_message:
            print("Missing ping3 module. Install via: pip install ping3")
            print_ping_error_message = False
            time.sleep(2)

        openssl_is_active = has_openssl()
        if not openssl_is_active:
            print("OpenSSL not found, speed tests may be less reliable.")

        # ---------- Checkpoint / Resume ----------
        CHECKPOINT_FILE = "progress.json"
        tested_ips = set()
        already_speedtested = set()
        all_selected = []

        def save_results():
            if all_selected:
                top_ips = sorted(all_selected, key=lambda x: x.download, reverse=True)[:max_ip]
                with open('selected-ips.csv', 'w') as f:
                    f.write("#,IP,Ping (ms),Packet Loss,Jitter (ms),Latency (ms),Upload (Mbps),Download (Mbps)\n")
                    for i, el in enumerate(top_ips, 1):
                        f.write(f"{i},{el.ip},{el.ping},{el.packet_loss},{el.jitter},{el.latency},{el.upload},{el.download}\n")
                with open('selected-ips.txt', 'w') as f:
                    f.write('\n'.join(el.ip for el in top_ips))

        def save_checkpoint():
            state = {
                'all_selected': [ip.to_dict() for ip in all_selected],
                'tested_ips': list(tested_ips),
                'already_speedtested': list(already_speedtested),
                'max_ip': max_ip,
                'config': {k: config['DEFAULT'][k] for k in config['DEFAULT']}
            }
            with open(CHECKPOINT_FILE, 'w') as f:
                json.dump(state, f)
            save_results()

        resume = False
        if os.path.exists(CHECKPOINT_FILE):
            ans = input("A previous session state was found. Resume from where you left? (yes/no) [yes]: ").strip().lower()
            if ans in ['', 'y', 'yes']:
                with open(CHECKPOINT_FILE, 'r') as f:
                    state = json.load(f)
                all_selected = [IPInfo.from_dict(d) for d in state['all_selected']]
                tested_ips = set(state['tested_ips'])
                already_speedtested = set(state['already_speedtested'])
                resume = True
                print(f"Resumed with {len(all_selected)} selected IPs, {len(tested_ips)} tested IPs.")
                save_results()
            else:
                os.remove(CHECKPOINT_FILE)
                print("Starting fresh scan.")

        def gen():
            return random_ip_generator(ranges, tested_ips, total_possible)

        if not resume:
            # ---------- Normal search ----------
            VALID_MULTIPLIER = 4
            target_valid = max_ip * VALID_MULTIPLIER

            ip_gen = gen()
            print("Normal search: scanning for valid IPs...")
            valid_candidates = asyncio.run(normal_scan(config, ip_gen, total_possible, target_valid))

            if valid_candidates:
                speed_test_batch_live(all_selected, valid_candidates, config,
                                    max_ip, min_download_speed, min_upload_speed,
                                    already_speedtested, save_checkpoint)

            while len(all_selected) < max_ip and len(tested_ips) < total_possible:
                ip_gen = gen()
                valid_candidates = asyncio.run(normal_scan(config, ip_gen, total_possible,
                                                        target_valid - len(all_selected)))
                if valid_candidates:
                    speed_test_batch_live(all_selected, valid_candidates, config,
                                        max_ip - len(all_selected), min_download_speed, min_upload_speed,
                                        already_speedtested, save_checkpoint)

        # After normal scan, clear screen and show table 1
        if all_selected:
            os.system('cls' if os.name == 'nt' else 'clear')
            print_final_table(all_selected[:max_ip], "selected IP(s)")
            save_results()

        # ---------- Extended search loop ----------
        while len(all_selected) >= max_ip:
            base = all_selected[:max_ip]
            avg_ping = sum(el.ping for el in base) / len(base)
            avg_loss = sum(el.packet_loss for el in base) / len(base)
            avg_jitter = sum(el.jitter for el in base) / len(base)
            avg_latency = sum(el.latency for el in base) / len(base)
            avg_upload = sum(el.upload for el in base) / len(base)
            avg_download = sum(el.download for el in base) / len(base)

            print(f"Current averages (top {max_ip}): ping={int(avg_ping)}ms, loss={avg_loss*100:.1f}%, "
                f"jitter={int(avg_jitter)}ms, latency={int(avg_latency)}ms, "
                f"up={avg_upload:.2f}Mbps, down={avg_download:.2f}Mbps")
            do_extended = input("\nPerform extended search to find better IPs? (yes/no) [no]: ").strip().lower()
            if do_extended not in ['y', 'yes']:
                break

            m = input("How many better IPs (M) to find? [10]: ").strip()
            if not m:
                m = 10
            m = int(m)

            original_top = base.copy()
            current_list = original_top.copy()
            current_avg = {
                'ping': avg_ping,
                'loss': avg_loss,
                'jitter': avg_jitter,
                'latency': avg_latency,
                'upload': avg_upload,
                'download': avg_download,
            }

            ip_gen = gen()
            asyncio.run(extended_search_live(config, ip_gen, total_possible, current_avg,
                                            already_speedtested, m, current_list,
                                            save_checkpoint))

            # After extended, clear screen and show final top N
            current_list.sort(key=lambda x: x.download, reverse=True)
            new_top = current_list[:max_ip]
            original_ips = set(el.ip for el in original_top)
            better_original = [ip for ip in new_top if ip.ip in original_ips]
            extended_ips = [ip for ip in new_top if ip.ip not in original_ips]

            os.system('cls' if os.name == 'nt' else 'clear')
            print("Extended search results:")
            if better_original:
                print_final_table(better_original, "original IPs better than average")
            if extended_ips:
                print_final_table(extended_ips, "extended search IPs")

            print("Final merged top N:")
            print_final_table(new_top, "final selected IP(s)")

            all_selected = new_top
            save_results()

            # Also save extended-specific files
            with open('selected-ips-extended.csv', 'w') as f:
                f.write("#,IP,Ping (ms),Packet Loss,Jitter (ms),Latency (ms),Upload (Mbps),Download (Mbps)\n")
                for i, el in enumerate(all_selected, 1):
                    f.write(f"{i},{el.ip},{el.ping},{el.packet_loss},{el.jitter},{el.latency},{el.upload},{el.download}\n")
            with open('selected-ips-extended.txt', 'w') as f:
                f.write('\n'.join(el.ip for el in all_selected))
            print("Extended results saved to selected-ips-extended.*")

            if len(tested_ips) >= total_possible:
                print("All IPs have been tested.")
                break

        # ---------- Cloudflare upload ----------
        if upload_results.lower() in ["y", "yes"]:
            try:
                if delete_existing.lower() in ["y", "yes"]:
                    existing_records = getCloudflareExistingRecords(email, api_key, zone_id, subdomain)
                    print("Deleting existing records...", end='', flush=True)
                    for record in existing_records:
                        deleteCloudflareExistingRecord(email, api_key, zone_id, record["id"])
                    print("Done.")
                final_ips = sorted(all_selected, key=lambda x: x.download, reverse=True)[:max_ip]
                for el in final_ips:
                    print(el.ip, end='', flush=True)
                    addNewCloudflareRecord(email, api_key, zone_id, subdomain, el.ip)
                    print(" Done.")
                print("Cloudflare updated.")
            except Exception as e:
                print("Failed to update Cloudflare!")
                print(e)

        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
        print("Done.")

    except KeyboardInterrupt:
        print("\n\nRequest cancelled by user!")
        if 'all_selected' in locals() and 'tested_ips' in locals() and 'already_speedtested' in locals():
            save_checkpoint()
            save_results()
            print("Progress and results saved to disk. You can resume later.")
        sys.exit(0)
    except requests.exceptions.RequestException as e:
        print("Error: Something went wrong, please try again!")
        sys.exit(1)


if __name__ == '__main__':
    main()