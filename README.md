# `faas`

Function-as-a-service runtime.

## to run

  sudo ip addr add 10.0.0.1/24 dev lo
  sudo ip addr add 10.0.0.2/24 dev lo
  sudo python3 server.py
  python3 test_client.py

## Summary

- Translates HTTP requests into container runs.
- Containers receive HTTP URL and headers as CLI arguments, the HTTP body as
  stdin, and the corresponding client request socket
- IP addresses and Domain Names will be managed by a faas daemon, which will
  accept requests, start the appropriate container, and pass along request data
  to the running container.

