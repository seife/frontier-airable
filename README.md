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

## airable-api.py
airable-api implementes the API to provide radio station lists to the radios.
Your list of radios is stored in `stations.toml`, there is an example file in the repo which should be somewhat self-explaining.
The format is like this:
```toml
[Foldername]
label = "Describe folder"
  [[Foldername.station]]
  id = "unique_id"
  name = "Describe the station"
  url = "http://the.url.of/the/radio/stream.aac

  [[Foldername.station]]
  id = "another_id"
  name = "Another name"
  url = "http://next.url/of/radio/stream"

[Anotherfolder]
label = "..."
  [[Anotherfolder.station]]
  id = "foo"
  name = "Foo Bar"
  url = "http://yet.another/station/url.mp3"

[[station]]
id = "id1"
name = "A station that appears in the top level menu"
url = "http://url.of/toplevel.station"
```
The API also serves station logos, the station logos probably should not be too big and in PNG format (150x150 works fine).
Logos are stored in the file system in the `logos/` subdirectory, the file system structure corresponds to the `stations.toml` file, the path is built from the folder name, the id and an appended `.png'
```
logos/id1.png
logos/Anotherfolder/foo.png
logos/Foldername/unique_id.png
logos/Foldername/another_id.png
```
if no matching logo file is found, `logos/logo-internet-radio.png` is served instead.
