#!/bin/sh
set -eu
umask 077
# Secret material exists only in the ignored environment and ephemeral container config.
cat > /tmp/s3.json <<EOF
{"identities":[
{"name":"initializer","credentials":[{"accessKey":"$OBJECT_ADMIN_ACCESS_KEY","secretKey":"$OBJECT_ADMIN_SECRET_KEY"}],"actions":["Admin"]},
{"name":"api","credentials":[{"accessKey":"$OBJECT_API_ACCESS_KEY","secretKey":"$OBJECT_API_SECRET_KEY"}],"actions":["Read:resume-originals","Write:resume-originals"]},
{"name":"worker","credentials":[{"accessKey":"$OBJECT_WORKER_ACCESS_KEY","secretKey":"$OBJECT_WORKER_SECRET_KEY"}],"actions":["Read:resume-originals"]},
{"name":"relay","credentials":[{"accessKey":"$OBJECT_RELAY_ACCESS_KEY","secretKey":"$OBJECT_RELAY_SECRET_KEY"}],"actions":["Write:resume-originals"]}
]}
EOF
exec weed mini -dir=/data -ip=objectstore -ip.bind=0.0.0.0 -webdav=false -admin.ui=false -master.telemetry=false -s3.config=/tmp/s3.json -s3.autoCreateBucket=false -s3.port.iceberg=0 -s3.port.lance=0 -s3.iam=false
