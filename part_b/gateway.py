#!/usr/bin/env python3
"""
Part B — IoT Gateway with Store-and-Forward

Simulates compressor discharge pressure and publishes to MQTT every 1 second.
Features:
  - Accurate ISO-8601 UTC timestamps taken at sample time (not publish time)
  - Store-and-forward: buffers readings locally during network outage
  - Automatic reconnection with exponential backoff
  - Settings read from config file or CLI args — no hard-coded values
  - Monotonically increasing sequence numbers

Usage:
    python gateway.py --config gateway.ini
    python gateway.py --broker test.mosquitto.org --topic sparkline/firstname-lastname/compressor1

To demonstrate store-and-forward:
  1. Start the gateway
  2. Block the broker (e.g., sudo iptables -A OUTPUT -p tcp --dport 1883 -j DROP)
  3. Wait ~20 seconds, observe "Buffered" messages
  4. Unblock (sudo iptables -F), observe "Flushed" messages — no gap in seq
"""

import json
import time
import random
import argparse
import configparser
from datetime import datetime, timezone
from collections import deque

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt==1.6.1")
    raise


class CompressorGateway:
    def __init__(self, config):
        self.broker = config.get('mqtt', 'broker', fallback='test.mosquitto.org')
        self.port = config.getint('mqtt', 'port', fallback=1883)
        self.topic = config.get('mqtt', 'topic', fallback='sparkline/firstname-lastname/compressor1')
        self.device_id = config.get('gateway', 'device_id', fallback='firstname-lastname-compressor-1')
        self.sample_rate = config.getfloat('gateway', 'sample_rate', fallback=1.0)
        self.max_buffer = config.getint('gateway', 'max_buffer', fallback=10000)

        self.seq = 0
        self.buffer = deque(maxlen=self.max_buffer)
        self.connected = False
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        # Simulated signal: compressor discharge pressure ~7 bar with realistic noise
        self.pressure_base = 7.0
        self.noise_level = 0.05

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[CONNECTED] {self.broker}:{self.port}")
            self.connected = True
            self.flush_buffer()
        else:
            print(f"[CONNECT FAILED] rc={rc}")

    def on_disconnect(self, client, userdata, rc):
        print(f"[DISCONNECTED] rc={rc}")
        self.connected = False

    def generate_pressure(self):
        """Realistic noisy pressure signal hovering around 7 bar."""
        noise = random.gauss(0, self.noise_level)
        drift = 0.05 * random.gauss(0, 1)  # Slow process drift
        return round(self.pressure_base + noise + drift, 3)

    def create_message(self, seq, timestamp, value):
        return {
            "device_id": self.device_id,
            "seq": seq,
            "timestamp": timestamp,
            "parameter": "discharge_pressure",
            "value": value,
            "unit": "bar"
        }

    def flush_buffer(self):
        """Send buffered messages when connection restored."""
        flushed = 0
        while self.buffer and self.connected:
            msg = self.buffer.popleft()
            payload = json.dumps(msg, separators=(',', ':'))
            try:
                self.client.publish(self.topic, payload)
                flushed += 1
            except Exception as e:
                print(f"[FLUSH ERROR] {e}")
                self.buffer.appendleft(msg)
                break
        if flushed:
            print(f"[FLUSHED] {flushed} buffered messages")

    def connect_with_backoff(self, max_retries=20):
        """Connect with exponential backoff (1s, 2s, 4s, ... max 30s)."""
        retries = 0
        while retries < max_retries:
            try:
                self.client.connect(self.broker, self.port, keepalive=60)
                self.client.loop_start()
                return True
            except Exception as e:
                wait = min(2 ** retries, 30)
                print(f"[CONNECT FAIL] {e}. Retry in {wait}s...")
                time.sleep(wait)
                retries += 1
        return False

    def run(self):
        print(f"[STARTING] Gateway for {self.device_id}")
        print(f"[CONFIG] broker={self.broker}, topic={self.topic}, rate={self.sample_rate}s")

        if not self.connect_with_backoff():
            print("[FATAL] Could not connect after max retries")
            return

        try:
            while True:
                # CRITICAL: Timestamp taken at SAMPLE time, not publish time
                sample_time = datetime.now(timezone.utc)
                timestamp = sample_time.strftime('%Y-%m-%dT%H:%M:%SZ')

                value = self.generate_pressure()
                self.seq += 1

                msg = self.create_message(self.seq, timestamp, value)
                payload = json.dumps(msg, separators=(',', ':'))

                if self.connected:
                    try:
                        self.client.publish(self.topic, payload)
                        print(f"[PUBLISH] seq={self.seq} t={timestamp} val={value} bar")
                    except Exception as e:
                        print(f"[PUBLISH FAIL] {e}, buffering seq={self.seq}")
                        self.buffer.append(msg)
                else:
                    self.buffer.append(msg)
                    print(f"[BUFFERED] seq={self.seq} (offline, buffer={len(self.buffer)})")

                time.sleep(self.sample_rate)

        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Stopping gateway...")
            self.client.loop_stop()
            self.client.disconnect()
            print(f"[STATS] Final seq={self.seq}, buffer remaining={len(self.buffer)}")


def build_config_from_args(args):
    """Build ConfigParser from CLI arguments."""
    config = configparser.ConfigParser()
    config['mqtt'] = {}
    config['gateway'] = {}

    if args.broker:
        config['mqtt']['broker'] = args.broker
    if args.port:
        config['mqtt']['port'] = str(args.port)
    if args.topic:
        config['mqtt']['topic'] = args.topic
    if args.device_id:
        config['gateway']['device_id'] = args.device_id
    if args.sample_rate:
        config['gateway']['sample_rate'] = str(args.sample_rate)

    return config


def main():
    parser = argparse.ArgumentParser(description='Compressor IoT Gateway')
    parser.add_argument('--config', default='gateway.ini', help='Path to config file')
    parser.add_argument('--broker', help='MQTT broker hostname')
    parser.add_argument('--port', type=int, help='MQTT broker port')
    parser.add_argument('--topic', help='MQTT topic to publish to')
    parser.add_argument('--device-id', help='Unique device identifier')
    parser.add_argument('--sample-rate', type=float, help='Sample rate in seconds')
    args = parser.parse_args()

    config = configparser.ConfigParser()

    # Read config file if it exists
    if config.read(args.config):
        print(f"[CONFIG] Loaded from {args.config}")
    else:
        print(f"[CONFIG] No file at {args.config}, using defaults/CLI args")

    # Override with CLI args
    cli_config = build_config_from_args(args)
    for section in cli_config.sections():
        if section not in config.sections():
            config.add_section(section)
        for key, val in cli_config.items(section):
            config.set(section, key, val)

    gateway = CompressorGateway(config)
    gateway.run()


if __name__ == '__main__':
    main()
