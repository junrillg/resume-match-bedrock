# RDS public certificate authorities

`rds-global-bundle.pem` is the unmodified public CA bundle downloaded on 2026-10-17
from [Amazon RDS truststore](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem).
SHA-256: `90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b`.

Direct RDS bootstrap configuration sets `POSTGRES_SSLMODE=verify-full` and
`POSTGRES_SSLROOTCERT=/app/certs/rds-global-bundle.pem`. libpq verifies both the
certificate chain and database hostname. Update this public bundle when RDS rotates
authorities; never replace it with a database password or private key.

## RDS Proxy client trust

`amazon-trust-services.pem` concatenates five unmodified PEM files from the
[official Amazon Trust Services repository](https://www.amazontrust.com/repository/),
downloaded 2026-10-19: [AmazonRootCA1.pem](https://www.amazontrust.com/repository/AmazonRootCA1.pem),
[AmazonRootCA2.pem](https://www.amazontrust.com/repository/AmazonRootCA2.pem),
[AmazonRootCA3.pem](https://www.amazontrust.com/repository/AmazonRootCA3.pem),
[AmazonRootCA4.pem](https://www.amazontrust.com/repository/AmazonRootCA4.pem), and
[SFSRootCAG2.pem](https://www.amazontrust.com/repository/SFSRootCAG2.pem).
The certificate DER SHA-256 hashes were verified against that repository.
Amazon Trust Services licenses these certificates under
[CC BY-ND 4.0](https://creativecommons.org/licenses/by-nd/4.0/); certificates are
unmodified and their authorship remains with the named certificate authorities.
Bundle SHA-256: `dfaa39c0350288ded35812f7b80f76c4a422b97ecc04c4ac84e325bec528b1b8`.

Proxy clients set `POSTGRES_PROXY_MODE=true`, `POSTGRES_SSLMODE=verify-full` and
`POSTGRES_SSLROOTCERT=/app/certs/amazon-trust-services.pem`. Direct bootstrap
keeps the RDS bundle above. Proxy mode omits startup `options`, keeps prepared
statements and server cursors disabled, and relies on role UTC/timeouts. These
settings are local/source checks; managed proxy pinning and TLS remain deployment
verification steps. Renew from official sources as trust roots rotate.
