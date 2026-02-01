#!/bin/bash

# Linux Network Optimization Script for High-Latency/Throttled Links (Youtube-DL VPS)
# Run as root or with sudo

echo "Applying Network Optimizations..."

# 1. Enable TCP BBR (Bottleneck Bandwidth and RTT)
# Google's congestion control algorithm, excellent for packet loss/throttling.
if grep -q "bbr" /proc/sys/net/ipv4/tcp_available_congestion_control; then
    echo "TCP BBR is available. Enabling..."
    sysctl -w net.core.default_qdisc=fq
    sysctl -w net.ipv4.tcp_congestion_control=bbr
else
    echo "TCP BBR not found. Updating kernel might be required for BBR."
    echo "Falling back to 'cubic' but optimizing buffers."
fi

# 2. Increase TCP Window Sizes (Buffer Tuning)
# Allows more data in flight, crucial for high latency connections.
# Values are in bytes.

# Max receive buffer size (16MB)
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216

# TCP Autotuning settings (Min, Default, Max)
# Max set to 16MB to match core.rmem_max.
sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"

# 3. Enable Window Scaling
sysctl -w net.ipv4.tcp_window_scaling=1

# 4. Increase backlog for incoming connections (helps with bursty connect attempts)
sysctl -w net.core.netdev_max_backlog=5000

# 5. Make settings persistent
cat <<EOF > /etc/sysctl.d/99-custom-network-tuning.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_window_scaling = 1
net.core.netdev_max_backlog = 5000
EOF

echo "-----------------------------------------------------"
echo "Optimizations applied!"
echo "Current Congestion Control: $(sysctl -n net.ipv4.tcp_congestion_control)"
echo "Current Max Receive Buffer: $(sysctl -n net.core.rmem_max)"
echo "Persistent config saved to /etc/sysctl.d/99-custom-network-tuning.conf"
