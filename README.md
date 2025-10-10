# `faas`

Function-as-a-service runtime.

## to run

  sudo ifconfig lo0 alias 10.0.0.1 netmask 255.255.255.0
  sudo ifconfig lo0 alias 10.0.0.2 netmask 255.255.255.0
  sudo python3 server.py
  python3 test_client.py

## Summary

- Translates HTTP requests into container runs.
- Containers receive HTTP URL and headers as CLI arguments, the HTTP body as
  stdin, and the corresponding client request socket
- IP addresses and Domain Names will be managed by a faas daemon, which will
  accept requests, start the appropriate container, and pass along request data
  to the running container.

# TODO

- Graceful shutdowns on ctrl-c, ctrl-d kills.
- Generate domain names for IPs, update DNS records.
