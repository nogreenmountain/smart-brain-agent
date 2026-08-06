FROM smartbrain-dashboard-local:latest

RUN apk add --no-cache openssh-client

COPY entrypoint.sh /usr/local/bin/smartbrain-tunnel-entrypoint
RUN chmod 0755 /usr/local/bin/smartbrain-tunnel-entrypoint

ENTRYPOINT ["/usr/local/bin/smartbrain-tunnel-entrypoint"]
