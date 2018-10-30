#!/usr/bin/env python

import os
import socket
import sys
import time
from kubernetes import client, config
from kubernetes.client.rest import ApiException

GLOBAL_TAGS = os.environ.get("GLOBAL_TAGS")
NAMESPACE = os.environ.get("NAMESPACE", "redis")
PERIOD = os.environ.get("PERIOD", 20)
PREFIX = os.environ.get("PREFIX", "redis")
STATSD_HOST = os.environ.get("NODE_IP")
STATSD_PORT = int(os.environ.get("STATSD_PORT", 8125))

GAUGES = {
    "blocked_clients": "blocked_clients",
    "connected_clients": "connected_clients",
    "instantaneous_ops_per_sec": "instantaneous_ops_per_sec",
    "latest_fork_usec": "latest_fork_usec",
    "mem_fragmentation_ratio": "mem_fragmentation_ratio",
    "migrate_cached_sockets": "migrate_cached_sockets",
    "pubsub_channels": "pubsub_channels",
    "pubsub_patterns": "pubsub_patterns",
    "uptime_in_seconds": "uptime_in_seconds",
    "used_memory": "used_memory",
    "used_memory_lua": "used_memory_lua",
    "used_memory_peak": "used_memory_peak",
    "used_memory_rss": "used_memory_rss",
}
COUNTERS = {
    "evicted_keys": "evicted_keys",
    "expired_keys": "expired_keys",
    "keyspace_hits": "keyspace_hits",
    "keyspace_misses": "keyspace_misses",
    "rejected_connections": "rejected_connections",
    "sync_full": "sync_full",
    "sync_partial_err": "sync_partial_err",
    "sync_partial_ok": "sync_partial_ok",
    "total_commands_processed": "total_commands_processed",
    "total_connections_received": "total_connections_received",
}
KEYSPACE_COUNTERS = {"expires": "expires"}
KEYSPACE_GAUGES = {"avg_ttl": "avg_ttl", "keys": "keys"}

last_seens = {}


def send_metric(name, mtype, value, tags=None):
    tagstring = ""
    finalvalue = value
    if tags is None:
        tags = []

    if GLOBAL_TAGS is not None:
        tags.extend(GLOBAL_TAGS.split(","))

    if len(tags) > 0:
        tagstring = "|#{}".format(",".join(tags))

    if mtype == "c":
        # For counters we will calculate our own deltas.
        mkey = f"{name}:{tagstring}"
        if mkey in last_seens:
            # global finalvalue
            # calculate our deltas and don't go below 0
            finalvalue = max(0, value - last_seens[mkey])
        else:
            # We'll default to 0, since we don't want our first counter
            # to be some huge number.
            finalvalue = 0
        last_seens[mkey] = value

    met = f"{name}:{finalvalue}|{mtype}{tagstring}"
    out_sock.sendto(met, (STATSD_HOST, STATSD_PORT))


def linesplit(socket):
    buffer = socket.recv(4096)
    buffering = True
    while buffering:
        if "\n" in buffer:
            (line, buffer) = buffer.split("\n", 1)
            if line == "\r":
                buffering = False
            yield line
        else:
            more = socket.recv(4096)
            if not more:
                buffering = False
            else:
                buffer += more
    if buffer:
        yield buffer


def send_metrics(redis_host: str, redis_port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((redis_host, redis_port))
    s.send("INFO\n")

    stats = {}
    stats["keyspaces"] = {}

    for line in linesplit(s):
        if "# Clients" in line:
            for l in line.split("\n"):
                if ":keys" in l:
                    (keyspace, kstats) = l.split(":")
                    if keyspace not in stats["keyspaces"]:
                        stats["keyspaces"][keyspace] = {}
                    for ks in kstats.split(","):
                        (n, v) = ks.split("=")
                        stats["keyspaces"][keyspace][n] = v.rstrip()

                elif ":" in l:
                    (name, value) = l.split(":")
                    stats[name] = value.rstrip()

    s.close()

    out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    for g in GAUGES:
        if g in stats:
            send_metric(f"{PREFIX}.{g}", "g", float(stats[g]), [f"host={host}"])

    for c in COUNTERS:
        if c in stats:
            send_metric(f"{PREFIX}.{c}", "c", float(stats[c]), [f"host={host}"])

    for ks in stats["keyspaces"]:
        for kc in KEYSPACE_COUNTERS:
            if kc in stats["keyspaces"][ks]:
                send_metric(
                    "{PREFIX}.keyspace.{kc}",
                    "c",
                    float(stats["keyspaces"][ks][kc]),
                    [f"keyspace={ks}", f"host={host}"],
                )

        for kg in KEYSPACE_GAUGES:
            if kg in stats["keyspaces"][ks]:
                send_metric(
                    "{PREFIX}.keyspace.{kg}",
                    "g",
                    float(stats["keyspaces"][ks][kg]),
                    [f"keyspace={ks}", f"host={host}"],
                )

    out_sock.close()


def send_error_metric(host: str):
    send_metric(f"{PREFIX}.error", "c", 1, [f"host={host}"])


def main():
    config.load_kube_config()
    k8_api_instance = client.CoreV1Api()

    while True:
        api_response = k8_api_instance.list_namespaced_service(NAMESPACE)

        for svc in api_response.items:
            host = f"{svc.metadata.name}.{namespace}.svc.cluster.local"
            port = svc.spec.ports[0].port

            try:
                send_metrics(host, port)
            except Exception as e:
                send_error_metric(host)
        time.sleep(PERIOD)


main()
