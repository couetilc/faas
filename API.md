# `faas` and `faasd` API

These utility are intended to be used through CLIs.

## `faas`

Client program installed on user machines.

### API ideas

Upload and register a container image as a handler in the faas service.

```
# create a handler named <image-name> from an image <image-name>
faas new <image-name>
# or 
docker image save <image-name> | faas new <handler-name>
# or
faas new -t <image-name> <handler-name>
```

Get network information for a configured handler

```
faas ip <handler-name>
```


## `faasd`

Server program installed on service provider machine.

Manages docker images, creates a rootfs and OCI spec on handler upload, not on
each run, how about that? Then runc on each request

## Function runtime

Interfaces to make runtime details like receiving a tcp socket effortless.

Python interface for functions:

```py
from faas import connection
write('HTTP 1.0...', connection)
```

Python interface for apps:

```py
from faas import listening
# could be generator fn of connection sockets, but I'd need to know what an
# efficient pattern is to enable multiplexing so the app itself can spawn
# threads or functions.
for connection in listening:
  write('HTTP 1.0...', connection)
```

Python interface for apps to run functions:

```py
from faas import listening, run
for connection in listening:
  run(faas='fibonacci', connection)
```

Imagine: Python interface for apps to use a DB.

```py
# pip install faas[psycopg]
from faas import listening, rdb
with rdb.connect() as pgconn:
  for connection in listening:
    with pgconn.cursor as cur:
      cur.execute("SELECT ...")
    write('HTML...', connection)
```
