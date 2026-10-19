#!/bin/sh
set -eu
umask 077
# Secrets enter through the environment, never process arguments or startup output.
# Application roles cannot inspect users/config; viewer cannot publish or mutate.
{
 printf 'user default off\n'
 printf 'user gateway on >%s ~owner-cap:* &owner:* +ping +subscribe +unsubscribe +publish +eval +zremrangebyscore +zscore +zcard +zadd +expire +zrem\n' "$STREAM_GATEWAY_PASSWORD"
 printf 'user relay on >%s &owner:* +ping +publish\n' "$STREAM_RELAY_PASSWORD"
 printf 'user viewer on >%s ~owner-cap:* +ping +info +select +scan +type +ttl +pttl +zrange +zcard +zcount +zscore +memory|usage +client|setname +command +dbsize\n' "$STREAM_VIEWER_PASSWORD"
} > /tmp/users.acl
exec valkey-server --bind 0.0.0.0 --port 6379 --aclfile /tmp/users.acl --save '' --appendonly no --maxmemory 128mb --maxmemory-policy noeviction
