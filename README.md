# Tools for airable-enabled Frontier Silicon based radios
Here are some hacks for airable enabled Frontier Silicon based internet radios
(i.e. the ones that do not work with https://github.com/KIMB-technologies/Radio-API)

This is inspired by https://github.com/Half-Shot/fairable (which did not work as-is for me), but I try to reimplement this in python to reduce the number of dependencies.

## Setup
You need to run this on a machine whose IP is pointed to locally by "airable.wifiradiofrontier.com" and "assets.wifiradiofrontier.com".
The frontier radios do not seem to verify the ssl certificate, so you can simply create your own with:
```
openssl req -x509 -newkey rsa:4096 \
        -sha256 -days 3650 -nodes \
        -subj "/CN=airable.wifiradiofrontier.com" \
        -keyout key.pem -out cert.pem
```

## airable-proxy.py
airable-proxy is a simple proxy that intercepts all calls to the Frontier servers and caches the results.
This can improve the performance hugely in case the Frontier servers have performance issues (which seems to happen more often recenty).
It also writes all content and metadata of the API calls for later inspection, to help with the implementation of an own API implementation.
Because it listens on port 443, it needs to run as root.
