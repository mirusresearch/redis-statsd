#!/usr/bin/env python

import os
import socket
import sys
import time
from datadog.dogstatsd.base import DogStatsd
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from redis import StrictRedis

GLOBAL_TAGS = os.environ.get("GLOBAL_TAGS")
NAMESPACE = os.environ.get("NAMESPACE", "redis")
PERIOD = os.environ.get("PERIOD", 20)
PREFIX = os.environ.get("PREFIX", "redis")
STATSD_HOST = os.environ.get("NODE_IP", "127.0.0.1")
STATSD_PORT = int(os.environ.get("STATSD_PORT", 8125))

GAUGES = [
    "blocked_clients",
    "connected_clients",
    "instantaneous_ops_per_sec",
    "latest_fork_usec",
    "mem_fragmentation_ratio",
    "migrate_cached_sockets",
    "pubsub_channels",
    "pubsub_patterns",
    "uptime_in_seconds",
    "used_memory",
    "used_memory_lua",
    "used_memory_peak",
    "used_memory_rss",
]
COUNTERS = [
    "evicted_keys",
    "expired_keys",
    "keyspace_hits",
    "keyspace_misses",
    "rejected_connections",
    "sync_full",
    "sync_partial_err",
    "sync_partial_ok",
    "total_commands_processed",
    "total_connections_received",
]


statsd = DogStatsd(host=STATSD_HOST, port=STATSD_PORT)


def send_metrics(redis_host: str, redis_port: int, tags):
    print(redis_host)
    redis = StrictRedis(host=redis_host, port=redis_port)
    stats = redis.info()
    tags = [f"host:{host}"]
    print(stats)

    for g in GAUGES:
        if g in stats:
            statsd.gauge(f"{PREFIX}.{g}", float(stats[g]), tags=tags)

    for c in COUNTERS:
        if c in stats:
            statsd.histogram(f"{PREFIX}.{c}", float(stats[c]), tags=tags)


def send_error_metric(tags):
    statsd.histogram(f"{PREFIX}.error", float(1), tags=tags)


def main():
    config.load_incluster_config()
    k8_api_instance = client.CoreV1Api()

    while True:
        out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        api_response = k8_api_instance.list_namespaced_service(NAMESPACE)

        for svc in api_response.items:
            host = f"{svc.metadata.name}.{NAMESPACE}.svc.cluster.local"
            port = svc.spec.ports[0].port
            tags = [f"host:{host}"]
            try:
                send_metrics(host, port, tags)
            except Exception as e:
                print(e)
                send_error_metric(tags)

        out_sock.close()
        time.sleep(PERIOD)


main()
