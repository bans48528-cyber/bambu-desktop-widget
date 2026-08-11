import concurrent.futures
import json
import ipaddress
import msvcrt
import os
import select
import socket
import ssl
import struct
import tempfile
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
CONFIG_LOCK_PATH = APP_DIR / "config.lock"
LOG_PATH = APP_DIR / "startup.log"
SSDP_GROUP = "239.255.255.250"
SSDP_ST = "urn:bambulab-com:device:3dprinter:1"
SSDP_LISTEN_PORTS = (2021, 1990, 1900)
SSDP_QUERY_PORTS = (1990, 1900, 2021)


DEFAULT_CONFIG = {
    "printer_ip": "192.168.1.100",
    "serial": "01S00A000000000",
    "access_code": "12345678",
    "printer_name": "Bambu P1",
    "remaining_time_unit": "minutes",
    "opacity": 0.94,
    "font_size": 14,
    "window": {"x": 80, "y": 80, "width": 330, "height": 172},
    "mqtt": {
        "port": 8883,
        "username": "bblp",
        "connection_timeout_seconds": 4,
        "keepalive_seconds": 30,
        "reconnect_seconds": 8,
        "pushall_interval_seconds": 60,
    },
    "discovery": {
        "enabled": True,
        "timeout_seconds": 3,
        "scan_fallback": True,
        "scan_timeout_seconds": 4,
    },
}


STATE_LABELS = {
    "RUNNING": ("打印中", "#13b85f"),
    "PAUSE": ("已暂停", "#f4a62a"),
    "PAUSED": ("已暂停", "#f4a62a"),
    "PREPARE": ("准备中", "#3b82f6"),
    "SLICING": ("处理中", "#3b82f6"),
    "FINISH": ("已完成", "#16a34a"),
    "FAILED": ("失败", "#ef4444"),
    "ERROR": ("错误", "#ef4444"),
    "IDLE": ("空闲", "#8a929d"),
    "UNKNOWN": ("未知", "#8a929d"),
}


class MqttError(RuntimeError):
    pass


class ConfigError(RuntimeError):
    pass


def log_connection_error(exc):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            timestamp = datetime.now().isoformat(timespec="seconds")
            fh.write(f"{timestamp} mqtt error {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def log_message(message):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            timestamp = datetime.now().isoformat(timespec="seconds")
            fh.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def ensure_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)


def _load_config():
    ensure_config()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"无法读取配置文件：{exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("配置文件的顶层必须是 JSON 对象")
    return deep_merge(DEFAULT_CONFIG, loaded)


def load_config():
    return _load_config()


def save_config(config):
    payload = json.dumps(config, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=APP_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, CONFIG_PATH)
    except OSError as exc:
        raise ConfigError(f"无法保存配置文件：{exc}") from exc
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@contextmanager
def config_lock(timeout_seconds=5):
    CONFIG_LOCK_PATH.touch(exist_ok=True)
    with CONFIG_LOCK_PATH.open("r+b") as fh:
        fh.seek(0)
        fh.write(b"\0")
        fh.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ConfigError("配置文件正被其他窗口修改") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def update_config(mutator):
    """Apply a read-modify-write change without racing another project process."""
    with config_lock():
        config = _load_config()
        mutator(config)
        save_config(config)
        return config


def deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def utf8_field(text):
    raw = str(text).encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def encode_remaining_length(length):
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length == 0:
            return bytes(encoded)


def read_exact(sock, count):
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise MqttError("连接已关闭")
        chunks.extend(chunk)
    return bytes(chunks)


def read_remaining_length(sock):
    multiplier = 1
    value = 0
    while True:
        digit = read_exact(sock, 1)[0]
        value += (digit & 127) * multiplier
        if digit & 128 == 0:
            return value
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise MqttError("MQTT 包长度异常")


def parse_ssdp_headers(payload):
    try:
        text = payload.decode("utf-8", errors="replace")
    except AttributeError:
        text = str(payload)
    headers = {}
    for line in text.replace("\r\n", "\n").split("\n")[1:]:
        if not line.strip() or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def ip_from_location(location, fallback_ip):
    location = str(location or "").strip()
    if location:
        parsed = urllib.parse.urlparse(location if "://" in location else f"//{location}")
        candidate = parsed.hostname or location.split("/", 1)[0].split(":", 1)[0]
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    try:
        ipaddress.ip_address(fallback_ip)
        return fallback_ip
    except ValueError:
        return ""


def parse_bambu_ssdp_packet(payload, sender_ip):
    headers = parse_ssdp_headers(payload)
    nt = headers.get("nt", "")
    usn = headers.get("usn", "")
    model = headers.get("devmodel.bambu.com", "")
    name = headers.get("devname.bambu.com", "")
    if SSDP_ST not in nt and not model and not usn:
        return None

    ip = ip_from_location(headers.get("location"), sender_ip)
    if not ip:
        return None
    return {
        "ip": ip,
        "serial": usn.strip(),
        "model": model.strip(),
        "name": name.strip(),
        "connect": headers.get("devconnect.bambu.com", "").strip(),
        "bind": headers.get("devbind.bambu.com", "").strip(),
    }


def serial_matches(target_serial, found_serial):
    target = str(target_serial or "").strip().upper()
    found = str(found_serial or "").strip().upper()
    return bool(found) and (not target or target == found)


def create_discovery_socket(bind_port=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if bind_port is None:
        sock.bind(("", 0))
    else:
        sock.bind(("", int(bind_port)))
        try:
            membership = socket.inet_aton(SSDP_GROUP) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError:
            pass
    return sock


def send_ssdp_queries(sock):
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_GROUP}:1990\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        f"ST: {SSDP_ST}\r\n"
        "\r\n"
    ).encode("ascii")
    for port in SSDP_QUERY_PORTS:
        for host in (SSDP_GROUP, "255.255.255.255"):
            try:
                sock.sendto(message, (host, port))
            except OSError:
                pass


def discover_bambu_printer(target_serial=None, timeout_seconds=3, stop_event=None):
    deadline = time.monotonic() + max(0.5, float(timeout_seconds or 3))
    sockets = []
    try:
        for port in SSDP_LISTEN_PORTS:
            try:
                sockets.append(create_discovery_socket(port))
            except OSError as exc:
                log_message(f"discovery listen {port} failed: {type(exc).__name__}: {exc}")
        try:
            query_socket = create_discovery_socket()
            sockets.append(query_socket)
            send_ssdp_queries(query_socket)
        except OSError as exc:
            log_message(f"discovery query socket failed: {type(exc).__name__}: {exc}")

        while sockets and time.monotonic() < deadline:
            if stop_event and stop_event.is_set():
                return None
            timeout = min(0.2, max(0.0, deadline - time.monotonic()))
            readable, _, _ = select.select(sockets, [], [], timeout)
            for sock in readable:
                try:
                    payload, address = sock.recvfrom(4096)
                except OSError:
                    continue
                device = parse_bambu_ssdp_packet(payload, address[0])
                if device and serial_matches(target_serial, device.get("serial")):
                    log_message(
                        "discovery matched serial="
                        f"{device.get('serial', '')} ip={device.get('ip', '')} "
                        f"model={device.get('model', '')} connect={device.get('connect', '')}"
                    )
                    return device
        return None
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass


def should_discover_after_error(exc):
    return isinstance(exc, (OSError, TimeoutError, socket.timeout, ssl.SSLError))


def private_ipv4(value):
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    if address.version == 4 and address.is_private and not address.is_loopback and not address.is_link_local:
        return address
    return None


def candidate_scan_networks(config):
    networks = []
    seen = set()

    def add_address(value):
        address = private_ipv4(value)
        if not address:
            return
        network = ipaddress.ip_network(f"{address}/24", strict=False)
        key = str(network)
        if key not in seen:
            seen.add(key)
            networks.append(network)

    add_address(config.get("printer_ip"))
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add_address(item[4][0])
    except OSError:
        pass
    return networks


def mqtt_port_open(host, port, timeout_seconds, stop_event=None):
    if stop_event and stop_event.is_set():
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        return sock.connect_ex((str(host), int(port))) == 0
    finally:
        try:
            sock.close()
        except OSError:
            pass


def scan_open_mqtt_hosts(config, timeout_seconds=4, stop_event=None):
    networks = candidate_scan_networks(config)
    if not networks:
        return []

    port = int(config["mqtt"]["port"])
    hosts = []
    seen = set()
    for network in networks:
        for host in network.hosts():
            value = str(host)
            if value not in seen:
                seen.add(value)
                hosts.append(value)

    deadline = time.monotonic() + max(1.0, float(timeout_seconds or 4))
    open_hosts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as executor:
        future_map = {
            executor.submit(mqtt_port_open, host, port, 0.25, stop_event): host
            for host in hosts
        }
        for future in concurrent.futures.as_completed(future_map):
            if stop_event and stop_event.is_set():
                break
            if time.monotonic() >= deadline:
                break
            host = future_map[future]
            try:
                if future.result():
                    open_hosts.append(host)
            except OSError:
                pass
    return open_hosts


def mqtt_send_packet(sock, packet_type, body):
    sock.sendall(bytes([packet_type]) + encode_remaining_length(len(body)) + body)


def mqtt_read_publish(sock):
    packet_type = read_exact(sock, 1)[0]
    remaining = read_remaining_length(sock)
    body = read_exact(sock, remaining)
    if (packet_type & 0xF0) != 0x30 or len(body) < 2:
        return None, None
    topic_len = struct.unpack("!H", body[:2])[0]
    if 2 + topic_len > len(body):
        return None, None
    topic = body[2 : 2 + topic_len].decode("utf-8", errors="replace")
    payload = body[2 + topic_len :]
    return topic, payload


def probe_bambu_mqtt(config, host, timeout_seconds=2, stop_event=None):
    port = int(config["mqtt"]["port"])
    serial = str(config.get("serial", "")).strip()
    raw = None
    sock = None
    try:
        raw = socket.create_connection((host, port), timeout=min(1.0, float(timeout_seconds)))
        raw.settimeout(0.8)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        sock = context.wrap_socket(raw, server_hostname=host)
        raw = None

        client_id = "codex-bambu-probe-" + uuid.uuid4().hex[:8]
        variable = utf8_field("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", int(config["mqtt"]["keepalive_seconds"]))
        payload = utf8_field(client_id)
        payload += utf8_field(config["mqtt"]["username"])
        payload += utf8_field(config["access_code"])
        mqtt_send_packet(sock, 0x10, variable + payload)

        packet_type = read_exact(sock, 1)[0]
        remaining = read_remaining_length(sock)
        body = read_exact(sock, remaining)
        if packet_type != 0x20 or len(body) < 2 or body[1] != 0:
            return False
        if not serial:
            return True

        topic = f"device/{serial}/report"
        packet_id = 1
        mqtt_send_packet(sock, 0x82, struct.pack("!H", packet_id) + utf8_field(topic) + bytes([0]))
        request_topic = f"device/{serial}/request"
        request_payload = json.dumps(
            {
                "pushing": {
                    "sequence_id": str(int(time.time())),
                    "command": "pushall",
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        mqtt_send_packet(sock, 0x30, utf8_field(request_topic) + request_payload)

        deadline = time.monotonic() + max(0.8, float(timeout_seconds))
        while time.monotonic() < deadline:
            if stop_event and stop_event.is_set():
                return False
            try:
                publish_topic, publish_payload = mqtt_read_publish(sock)
            except socket.timeout:
                continue
            if publish_topic != topic or not publish_payload:
                continue
            try:
                message = json.loads(publish_payload.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and isinstance(message.get("print"), dict):
                return True
        return False
    except Exception:
        return False
    finally:
        for close_sock in (sock, raw):
            if close_sock:
                try:
                    close_sock.close()
                except OSError:
                    pass


def discover_bambu_by_mqtt_scan(config, timeout_seconds=4, stop_event=None):
    open_hosts = scan_open_mqtt_hosts(config, timeout_seconds, stop_event)
    for host in open_hosts:
        if stop_event and stop_event.is_set():
            return None
        if probe_bambu_mqtt(config, host, 2, stop_event):
            log_message(f"mqtt scan matched ip={host}")
            return {
                "ip": host,
                "serial": str(config.get("serial", "")).strip(),
                "model": "",
                "name": "",
                "connect": "mqtt-scan",
                "bind": "",
            }
    return None


class BambuMqttClient:
    def __init__(self, config, event_queue, stop_event):
        self.config = config
        self.events = event_queue
        self.stop_event = stop_event
        self.packet_id = 1
        self.sock = None
        self.last_pushall = 0
        self.print_snapshot = {}

    def run_forever(self):
        reconnect = int(self.config["mqtt"]["reconnect_seconds"])
        while not self.stop_event.is_set():
            try:
                self.events.put(("connection", "连接中..."))
                self.connect_with_discovery()
                self.events.put(("connection", "已连接"))
                self.subscribe()
                self.publish_pushall()
                self.read_loop()
            except Exception as exc:
                if not self.stop_event.is_set():
                    log_connection_error(exc)
                    self.events.put(("offline", f"离线：{exc}"))
            finally:
                self.close()
            if not self.stop_event.is_set():
                self.stop_event.wait(reconnect)

    def connect_with_discovery(self):
        try:
            self.connect()
            return
        except Exception as first_exc:
            self.close()
            discovery = self.config.get("discovery", {})
            if not discovery.get("enabled", True) or not should_discover_after_error(first_exc):
                raise

            self.events.put(("connection", "正在搜索设备..."))
            device = discover_bambu_printer(
                self.config.get("serial"),
                discovery.get("timeout_seconds", 3),
                self.stop_event,
            )
            if not device and discovery.get("scan_fallback", True):
                self.events.put(("connection", "正在扫描当前网段..."))
                device = discover_bambu_by_mqtt_scan(
                    self.config,
                    discovery.get("scan_timeout_seconds", 4),
                    self.stop_event,
                )
            if not device:
                raise first_exc

            new_ip = device.get("ip")
            if not new_ip:
                raise first_exc

            def remember_ip(config):
                config["printer_ip"] = new_ip

            try:
                self.config = update_config(remember_ip)
            except ConfigError as exc:
                log_message(f"discovery could not save ip {new_ip}: {type(exc).__name__}: {exc}")
                self.config["printer_ip"] = new_ip

            self.events.put(("connection", f"发现设备 {new_ip}，正在连接..."))
            try:
                self.connect()
            except Exception as second_exc:
                raise second_exc from first_exc

    def connect(self):
        host = self.config["printer_ip"]
        port = int(self.config["mqtt"]["port"])
        timeout = float(self.config["mqtt"].get("connection_timeout_seconds", 4))
        raw = socket.create_connection((host, port), timeout=timeout)
        raw.settimeout(2)

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.sock = context.wrap_socket(raw, server_hostname=host)

        client_id = "codex-bambu-widget-" + uuid.uuid4().hex[:8]
        variable = utf8_field("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", int(self.config["mqtt"]["keepalive_seconds"]))
        payload = utf8_field(client_id)
        payload += utf8_field(self.config["mqtt"]["username"])
        payload += utf8_field(self.config["access_code"])
        self.send_packet(0x10, variable + payload)

        packet_type, body = self.read_packet()
        if packet_type != 0x20 or len(body) < 2 or body[1] != 0:
            code = body[1] if len(body) > 1 else "?"
            raise MqttError(f"连接被拒绝，返回码 {code}")

    def subscribe(self):
        topic = f"device/{self.config['serial']}/report"
        body = struct.pack("!H", self.next_packet_id()) + utf8_field(topic) + bytes([0])
        self.send_packet(0x82, body)

    def publish_pushall(self):
        topic = f"device/{self.config['serial']}/request"
        payload = json.dumps(
            {
                "pushing": {
                    "sequence_id": str(int(time.time())),
                    "command": "pushall",
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_packet(0x30, utf8_field(topic) + payload)
        self.last_pushall = time.monotonic()

    def read_loop(self):
        pushall_interval = int(self.config["mqtt"]["pushall_interval_seconds"])
        keepalive = max(1, int(self.config["mqtt"]["keepalive_seconds"]))
        last_activity = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now - self.last_pushall > pushall_interval:
                self.publish_pushall()
            try:
                packet_type, body = self.read_packet()
            except socket.timeout:
                if time.monotonic() - last_activity >= keepalive:
                    self.send_packet(0xC0, b"")
                    last_activity = time.monotonic()
                continue

            last_activity = time.monotonic()

            if (packet_type & 0xF0) == 0x30:
                if len(body) < 2:
                    raise MqttError("MQTT 发布包缺少主题长度")
                topic_len = struct.unpack("!H", body[:2])[0]
                if 2 + topic_len > len(body):
                    raise MqttError("MQTT 发布包主题长度异常")
                payload = body[2 + topic_len :]
                self.handle_payload(payload)

    def handle_payload(self, payload):
        try:
            data = json.loads(payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return
        data = self.merge_print_snapshot(data)
        if data is None:
            return
        self.events.put(("status", normalize_status(data, self.config)))

    def merge_print_snapshot(self, data):
        if not isinstance(data, dict):
            return None

        print_update = data.get("print")
        if isinstance(print_update, dict):
            self.print_snapshot.update(print_update)

            state = str(
                print_update.get("gcode_state")
                or print_update.get("print_status")
                or self.print_snapshot.get("gcode_state")
                or self.print_snapshot.get("print_status")
                or ""
            ).upper()
            if state in {"FINISH", "IDLE", "FAILED", "ERROR"}:
                self.print_snapshot["mc_remaining_time"] = None
                if state == "FINISH" and "mc_percent" not in print_update:
                    self.print_snapshot["mc_percent"] = 100

            merged = dict(data)
            merged["print"] = dict(self.print_snapshot)
            return merged

        if self.print_snapshot:
            merged = dict(data)
            merged["print"] = dict(self.print_snapshot)
            return merged

        return None

    def read_packet(self):
        header = read_exact(self.sock, 1)[0]
        remaining = read_remaining_length(self.sock)
        return header, read_exact(self.sock, remaining)

    def send_packet(self, packet_type, body):
        self.sock.sendall(bytes([packet_type]) + encode_remaining_length(len(body)) + body)

    def next_packet_id(self):
        self.packet_id += 1
        if self.packet_id > 65535:
            self.packet_id = 1
        return self.packet_id

    def close(self):
        sock = self.sock
        self.sock = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def normalize_status(data, config):
    print_info = data.get("print") if isinstance(data, dict) else {}
    if not isinstance(print_info, dict):
        print_info = {}

    state = str(print_info.get("gcode_state") or print_info.get("print_status") or "UNKNOWN").upper()
    percent = to_float(print_info.get("mc_percent"))
    remaining_raw = print_info.get("mc_remaining_time")
    remaining = to_timedelta(remaining_raw, config.get("remaining_time_unit", "minutes"))
    eta = datetime.now() + remaining if remaining is not None else None

    layer_num = print_info.get("layer_num")
    total_layer_num = print_info.get("total_layer_num")
    subtask_name = print_info.get("subtask_name") or print_info.get("gcode_file") or config.get("printer_name", "Bambu")

    return {
        "state": state,
        "state_label": STATE_LABELS.get(state, STATE_LABELS["UNKNOWN"])[0],
        "state_color": STATE_LABELS.get(state, STATE_LABELS["UNKNOWN"])[1],
        "percent": percent,
        "remaining_text": format_duration(remaining),
        "eta_text": eta.strftime("%H:%M") if eta else "--:--",
        "layers_text": format_layers(layer_num, total_layer_num),
        "job_name": str(subtask_name).strip() or config.get("printer_name", "Bambu"),
        "raw": print_info,
    }


def to_float(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def to_timedelta(value, unit):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None

    unit = str(unit).lower()
    if unit == "seconds":
        return timedelta(seconds=number)
    if unit == "auto":
        return timedelta(seconds=number if number > 10080 else number * 60)
    return timedelta(minutes=number)


def format_duration(delta):
    if delta is None:
        return "--"
    total = max(0, int(delta.total_seconds() + 30))
    minutes = total // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def format_layers(current, total):
    if current in (None, "", 0, "0") and total in (None, "", 0, "0"):
        return "--"
    return f"{current or '-'} / {total or '-'}"
