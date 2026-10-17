# RDS public certificate authorities

`rds-global-bundle.pem` is the unmodified public CA bundle downloaded on 2026-10-17
from [Amazon RDS truststore](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem).
SHA-256: `90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b`.

Cloud configuration sets `POSTGRES_SSLMODE=verify-full` and
`POSTGRES_SSLROOTCERT=/app/certs/rds-global-bundle.pem`. libpq verifies both the
certificate chain and database hostname. Update this public bundle when RDS rotates
authorities; never replace it with a database password or private key.
