#!/usr/bin/env bash
#
# Close the AI model ports to the network; keep them open to this machine.
#
#   sudo deploy/lock-model-ports.sh            apply (takes effect at once, no model restart)
#   sudo deploy/lock-model-ports.sh status     show the rule
#   sudo deploy/lock-model-ports.sh remove     undo (add --forever to drop the boot unit too)
#   sudo deploy/lock-model-ports.sh persist    keep it across reboots (a small systemd unit re-applies it)
#
# Why (6 Oct 2026): vision :8011, OCR :8012 and embedding :8093 listened on every address with no
# key, so anyone on the office network could use the GPU and send it data. The pension pipeline and
# GP Fund call them on 127.0.0.1 since 5 Oct 2026, so loopback is all they need.
#
# What it does: one nftables table of its own (inet pension_models), so it touches no other rule
# and is removed in one step. Traffic to those ports is accepted from loopback and from Docker's
# bridge networks on this machine, and dropped from every other interface (Wi-Fi, the wired ports,
# Tailscale). Ports and allowed sources are below.
#
# The lasting fix is to start the models with --host 127.0.0.1 and an --api-key; that needs their
# unit files changed and a restart of each model (docs/DEPLOYMENT.md §3.5). This rule is right either way.
set -euo pipefail

TABLE="pension_models"
PORTS="8011, 8012, 8093"
DOCKER_NETS="172.16.0.0/12"

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

apply() {
  nft delete table inet "$TABLE" 2>/dev/null || true
  nft -f - <<EOF
table inet $TABLE {
  chain input {
    type filter hook input priority -10; policy accept;
    iifname "lo" tcp dport { $PORTS } accept
    ip saddr $DOCKER_NETS tcp dport { $PORTS } accept
    tcp dport { $PORTS } counter drop
  }
}
EOF
  echo "model ports $PORTS: open to this machine only"
}

case "${1:-apply}" in
  apply)   apply ;;
  status)  nft list table inet "$TABLE" 2>/dev/null || echo "not applied" ;;
  remove)
    nft delete table inet "$TABLE" 2>/dev/null && echo "removed" || echo "was not applied"
    if [[ "${2:-}" == "--forever" ]]; then
      systemctl disable --now pension-model-ports.service 2>/dev/null || true
      rm -f /etc/systemd/system/pension-model-ports.service && systemctl daemon-reload
      echo "boot unit removed"
    fi
    ;;
  persist)
    # Its own oneshot unit, not nftables.service: this machine's /etc/nftables.conf begins with
    # "flush ruleset", and enabling that service would wipe Docker's rules at every boot.
    apply
    self="$(readlink -f "${BASH_SOURCE[0]}")"
    printf '%s\n' \
      '[Unit]' \
      'Description=Close the AI model ports to the network (deploy/lock-model-ports.sh)' \
      'After=network-online.target docker.service' \
      'Wants=network-online.target' \
      '' \
      '[Service]' \
      'Type=oneshot' \
      'RemainAfterExit=yes' \
      "ExecStart=$self apply" \
      "ExecStop=$self remove" \
      '' \
      '[Install]' \
      'WantedBy=multi-user.target' > /etc/systemd/system/pension-model-ports.service
    systemctl daemon-reload
    systemctl enable pension-model-ports.service >/dev/null
    echo "enabled pension-model-ports.service: the rule is re-applied at every boot"
    ;;
  *) echo "usage: $0 [apply|status|remove|persist]" >&2; exit 2 ;;
esac
