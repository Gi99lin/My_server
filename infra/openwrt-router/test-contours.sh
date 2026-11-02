#!/usr/bin/env bash
set -uo pipefail

PASS=0; FAIL=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }
expect_eq() { if [ "$2" = "$3" ]; then ok "$1 ($2)"; else bad "$1 (got '$2', expected '$3')"; fi; }
expect_fail() { if [ "$2" = "FAIL" ]; then ok "$1 (blocked as expected)"; else bad "$1 (UNEXPECTEDLY SUCCEEDED: $2)"; fi; }

cleanup() {
  ssh -o BatchMode=yes root@192.168.1.13 "nft delete table inet test_outage 2>/dev/null || true; /etc/init.d/sing-box start >/dev/null 2>&1 || true" 2>/dev/null || true
  for vid in 10 20 30 40 50 60 70; do
    ip netns del ns$vid 2>/dev/null || true
    ip link del vp$vid 2>/dev/null || true
  done
}
trap cleanup EXIT
cleanup

for vid in 10 20 30 40 50 60 70; do
  ip netns add ns$vid
  ip link add vp$vid type veth peer name eth0 netns ns$vid
  ip link set vp$vid master vmbr1 up
  bridge vlan del vid 1 dev vp$vid 2>/dev/null || true
  bridge vlan add vid $vid pvid untagged dev vp$vid
  ip -n ns$vid link set lo up
  ip -n ns$vid link set eth0 up
  ip -n ns$vid addr add 10.10.$vid.250/24 dev eth0
  ip -n ns$vid route add default via 10.10.$vid.1
  mkdir -p /etc/netns/ns$vid
  if [ "$vid" = "10" ] || [ "$vid" = "70" ]; then
    echo "nameserver 10.10.$vid.1" > /etc/netns/ns$vid/resolv.conf
  else
    echo "nameserver 1.1.1.1" > /etc/netns/ns$vid/resolv.conf
  fi
done

probe() {
  local vid=$1; shift
  local out
  if out=$(ip netns exec ns$vid curl -fsS -m 8 "$@" 2>/dev/null); then
    echo "$out"
  else
    echo "FAIL"
  fi
}
probe_code() {
  local vid=$1; shift
  local code
  code=$(ip netns exec ns$vid curl -sS -o /dev/null -w "%{http_code}" -m 8 "$@" 2>/dev/null) || true
  [ -z "$code" ] && code="000"
  echo "$code"
}

HOME_IP="128.0.130.144"
KZ_IP="212.116.240.211"
BK_IP="194.60.132.37"

echo "=== 1. Exit IP per contour (Normal state: KZ primary active) ==="
expect_eq "VLAN 10 (edge)     exit IP" "$(probe 10 https://ifconfig.me)" "$HOME_IP"
expect_eq "VLAN 20 (personal) exit IP" "$(probe 20 https://ifconfig.me)" "$HOME_IP"
expect_eq "VLAN 30 (apps)     exit IP" "$(probe 30 https://ifconfig.me)" "$HOME_IP"
expect_eq "VLAN 40 (dev)      exit IP" "$(probe 40 https://ifconfig.me)" "$KZ_IP"
expect_eq "VLAN 50 (agents)   exit IP" "$(probe 50 https://ifconfig.me)" "$KZ_IP"
expect_eq "VLAN 60 (llm)      exit IP" "$(probe 60 https://ifconfig.me)" "$KZ_IP"
expect_eq "VLAN 70 (corp)     exit IP" "$(probe 70 https://ifconfig.me)" "$HOME_IP"

echo "=== 2. Selective proxy in personal/apps (Telegram & Open-Meteo) ==="
c_tg20=$(probe_code 20 https://api.telegram.org)
c_tg30=$(probe_code 30 https://api.telegram.org)
c_mt20=$(probe_code 20 -k https://149.154.166.110)
c_wx20=$(probe_code 20 "https://api.open-meteo.com/v1/forecast?latitude=55.75&longitude=37.61&current_weather=true")
[ "$c_tg20" = "302" ] || [ "$c_tg20" = "200" ] && ok "VLAN 20 Telegram reachable via proxy (HTTP $c_tg20)" || bad "VLAN 20 Telegram HTTP $c_tg20"
[ "$c_tg30" = "302" ] || [ "$c_tg30" = "200" ] && ok "VLAN 30 Telegram reachable via proxy (HTTP $c_tg30)" || bad "VLAN 30 Telegram HTTP $c_tg30"
[ "$c_mt20" = "302" ] || [ "$c_mt20" = "200" ] && ok "VLAN 20 raw-IP MTProto Telegram reachable (HTTP $c_mt20)" || bad "VLAN 20 raw-IP MTProto HTTP $c_mt20"
expect_eq "VLAN 20 Open-Meteo reachable via proxy" "$c_wx20" "200"

echo "=== 3. LLM direct-bypass block (must use omniroute!) ==="
for vid in 20 30 40 50; do
  expect_fail "VLAN $vid blocked from openrouter.ai" "$(probe $vid https://openrouter.ai/api/v1/models | head -c 20)"
  expect_fail "VLAN $vid blocked from openai.bothub.chat" "$(probe $vid https://openai.bothub.chat | head -c 20)"
done
c_or60=$(probe_code 60 https://openrouter.ai/api/v1/models)
expect_eq "VLAN 60 (llm) CAN reach openrouter.ai" "$c_or60" "200"
c_ant50=$(probe_code 50 https://api.anthropic.com)
[[ "$c_ant50" =~ ^[234][0-9][0-9]$ ]] && ok "VLAN 50 (agents) CAN reach api.anthropic.com for Claude OAuth (HTTP $c_ant50)" || bad "VLAN 50 api.anthropic.com HTTP $c_ant50"
expect_fail "VLAN 30 (apps) blocked from api.anthropic.com" "$(probe 30 https://api.anthropic.com | head -c 20)"

echo "=== 4. Isolation: contours cannot reach Proxmox / home LAN or forbidden VLANs ==="
for vid in 10 20 30 40 50 60 70; do
  ip netns exec ns$vid nc -z -w 2 192.168.1.12 22 2>/dev/null && bad "VLAN $vid reached Proxmox 192.168.1.12:22!" || ok "VLAN $vid blocked from Proxmox 192.168.1.12:22"
done
ip netns exec ns40 ping -c1 -W1 10.10.20.250 >/dev/null 2>&1 && bad "dev reached personal!" || ok "dev (40) isolated from personal (20)"
ip netns exec ns70 ping -c1 -W1 10.10.20.250 >/dev/null 2>&1 && bad "corp reached personal!" || ok "corp (70) isolated from personal (20)"
ip netns exec ns50 ping -c1 -W1 10.10.20.250 >/dev/null 2>&1 && bad "agents reached personal!" || ok "agents (50) isolated from personal (20)"

echo "=== 5. DNS Leak check on WAN (eth1 port 53) for VLAN 40, 50, 60 ==="
ssh -o BatchMode=yes root@192.168.1.13 "rm -f /tmp/dnsleak.txt; tcpdump -ni eth1 -c 5 'port 53' > /tmp/dnsleak.txt 2>&1 &"
sleep 1
ip netns exec ns40 curl -fsS -m 6 https://example.com >/dev/null 2>&1 || true
ip netns exec ns50 curl -fsS -m 6 https://example.com >/dev/null 2>&1 || true
ip netns exec ns60 curl -fsS -m 6 https://example.com >/dev/null 2>&1 || true
# Also try rogue direct DNS query to router gateway 10.10.40.1:53
ip netns exec ns40 nc -u -w 1 10.10.40.1 53 </dev/null >/dev/null 2>&1 || true
sleep 2
ssh -o BatchMode=yes root@192.168.1.13 "killall tcpdump 2>/dev/null || true"
LEAK_PKTS=$(ssh -o BatchMode=yes root@192.168.1.13 "grep -cE 'IP .*\.53[: ]' /tmp/dnsleak.txt 2>/dev/null || true")
expect_eq "WAN port 53 packets during VLAN 40/50/60 lookups" "${LEAK_PKTS:-0}" "0"

echo "=== 6. Simulated KZ Proxy (212.116.240.211) Outage ==="
ssh -o BatchMode=yes root@192.168.1.13 "nft add table inet test_outage; nft 'add chain inet test_outage out { type filter hook output priority 0; policy accept; }'; nft add rule inet test_outage out ip daddr 212.116.240.211 tcp dport 1080 reject with tcp reset"
echo "  Waiting 17s for sing-box urltest (interval=15s) to detect KZ outage..."
sleep 17
expect_fail "VLAN 60 (llm)    FAIL-CLOSED when KZ proxy down" "$(probe 60 https://ifconfig.me)"
expect_fail "VLAN 50 (agents) FAIL-CLOSED when KZ proxy down" "$(probe 50 https://ifconfig.me)"
expect_eq   "VLAN 40 (dev)    AUTO-FAILOVER to backup proxy"  "$(probe 40 https://ifconfig.me)" "$BK_IP"
c_tg20_bk=$(probe_code 20 https://api.telegram.org)
c_wx20_bk=$(probe_code 20 "https://api.open-meteo.com/v1/forecast?latitude=55.75&longitude=37.61&current_weather=true")
[ "$c_tg20_bk" = "302" ] || [ "$c_tg20_bk" = "200" ] && ok "VLAN 20 Telegram AUTO-FAILOVER to backup proxy (HTTP $c_tg20_bk)" || bad "VLAN 20 Telegram failover HTTP $c_tg20_bk"
expect_eq   "VLAN 20 Open-Meteo AUTO-FAILOVER to backup proxy" "$c_wx20_bk" "200"
ssh -o BatchMode=yes root@192.168.1.13 "nft delete table inet test_outage"

echo "=== 7. Hard Kill-Switch (sing-box process stopped completely) ==="
ssh -o BatchMode=yes root@192.168.1.13 "/etc/init.d/sing-box stop"
sleep 2
expect_fail "VLAN 40 (dev)    FAIL-CLOSED when sing-box stopped" "$(probe 40 https://ifconfig.me)"
expect_fail "VLAN 50 (agents) FAIL-CLOSED when sing-box stopped" "$(probe 50 https://ifconfig.me)"
expect_fail "VLAN 60 (llm)    FAIL-CLOSED when sing-box stopped" "$(probe 60 https://ifconfig.me)"
expect_eq   "VLAN 10 (edge)   still online when sing-box stopped" "$(probe 10 https://ifconfig.me)" "$HOME_IP"
expect_eq   "VLAN 70 (corp)   still online when sing-box stopped" "$(probe 70 https://ifconfig.me)" "$HOME_IP"

echo "=== 8. Auto-recovery after sing-box start (hotplug route restore) ==="
ssh -o BatchMode=yes root@192.168.1.13 "/etc/init.d/sing-box start"
sleep 4
expect_eq "VLAN 60 (llm)    recovered to KZ proxy" "$(probe 60 https://ifconfig.me)" "$KZ_IP"
expect_eq "VLAN 50 (agents) recovered to KZ proxy" "$(probe 50 https://ifconfig.me)" "$KZ_IP"
expect_eq "VLAN 40 (dev)    recovered to KZ proxy" "$(probe 40 https://ifconfig.me)" "$KZ_IP"

echo "========================================="
echo "TOTAL SUMMARY: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
