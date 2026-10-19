#!/bin/sh
set -eu
umask 077
# The image's existing Node runtime writes its private config without echoing secrets.
cp /redis-commander/config/default.json /tmp/default.json
node - <<'JS'
const fs = require('fs');
fs.writeFileSync('/tmp/local-production.json', JSON.stringify({
 noSave:true,noLogData:true,redis:{readOnly:true,useScan:true,rootPattern:'owner-cap:*'},
 server:{address:'0.0.0.0',port:8081,httpAuth:{username:'viewer',password:process.env.STREAM_GUI_PASSWORD}},
 connections:['fanout','fanout-b'].map((host,index)=>({label:'Fan-out shard '+index+' (Valkey)',host,port:6379,username:'viewer',password:process.env.STREAM_VIEWER_PASSWORD}))
}),{mode:0o600});
JS
export NODE_CONFIG_DIR=/tmp
export NODE_ENV=production
exec node ./bin/redis-commander.js
