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
