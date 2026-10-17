FROM busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092 AS health
RUN mkdir /data && chown 10001:10001 /data

FROM public.ecr.aws/zinclabs/openobserve:v1.1.1@sha256:dae91bc1f9d4c11db54e924d8d25bac7f6c50e080a8f06fc90d9468eaab81b67
# The OSS image is distroless; copy a static HTTP probe instead of assuming curl exists.
COPY --from=health /bin/busybox /busybox
COPY --from=health --chown=10001:10001 /data /data
USER 10001:10001
