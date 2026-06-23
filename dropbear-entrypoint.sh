#!/bin/sh
set -e

if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key
fi
if [ ! -f /etc/dropbear/dropbear_dss_host_key ]; then
    dropbearkey -t dss -f /etc/dropbear/dropbear_dss_host_key
fi
if [ ! -f /etc/dropbear/dropbear_ecdsa_host_key ]; then
    dropbearkey -t ecdsa -f /etc/dropbear/dropbear_ecdsa_host_key
fi

exec dropbear -F -E -p 22 -a
