#!/usr/bin/python3
#
# minimal(?) implementation of the airable.wifiradiofrontier.com API
# define your own internet radio lists
# tested with Philips TAPR802/12,
# firmware version ir-cui-FS2340-0000-0024_V4.5.22.75d4f4-2A3
#
# (C) 2026 Stefan Seyfried
# License: GPL-3.0+
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.

#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.

#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.


from http.server import HTTPServer, BaseHTTPRequestHandler
import ssl
import json
import logging
import signal
import tomllib
from pathlib import Path
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# handle sigterm (container stop) and sigint (ctrl-C)
def handle_signal(sig, frame):
    sig_name = signal.Signals(sig).name
    logging.info(f"signal {sig} {sig_name}... exit")
    raise SystemExit


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


radios_hash: Dict[str, Any] = {}
cwd = Path(__file__).parent
logging.info(f"cwd: {cwd}")


index = {
    "id": ["airable", "directory", "index"],
    "title": "Index",
    "url": "https://airable.wifiradiofrontier.com/",
    "content": {
        "entries": [
            {  # radio stations
                "id": ["api", "service", "radio"],
                "title": "Internet radio",
                "url": "https://airable.wifiradiofrontier.com/api/dir",
            },
            # {  # podcast feeds / not yet implemented
            #     "id": ["api", "service", "feed"],
            #     "title": "Podcasts",
            #     "url": "https://airable.wifiradiofrontier.com/api/feeds"
            # }
        ]
    },
}


def load_stations(file: str) -> dict:
    ret: Dict[str, Any] = {}
    try:
        with open(file, "rb") as f:
            data = tomllib.load(f)

        logging.info(f"loading {file}")
        for folder, content in data.items():
            if folder == "station":  # top level stations
                logging.info(f"Top Level: {folder} ---")
                ret["station"] = {}
                for station in content:
                    key = station["id"]
                    logging.info(f"{key:15s} {station['name']:25s} {station['url']}")
                    ret["station"][key] = station
                continue
            ret[folder] = {}
            if "label" in content:
                ret[folder]["label"] = content["label"]
            else:
                ret[folder]["label"] = folder
            logging.info(f"Folder: {folder} ---")
            if "station" not in content:
                logging.warning("folder does not contain entries?")
                continue
            ret[folder]["station"] = {}
            for station in content["station"]:
                key = f"{folder}/{station["id"]}"
                logging.info(f"{key:15s} {station['name']:25s} {station['url']}")
                ret[folder]["station"][key] = station
    except FileNotFoundError:
        logging.error(f"station config file {file} not found.")
    except tomllib.TOMLDecodeError as e:
        logging.error(f"config file:{e}")
    return ret


def build_radios_hash():

    def get_entry(kind: str, name: str, path: str, idname: str = "") -> dict:
        if kind == "radio":
            urlpath = "radio"
        else:
            urlpath = path
        if not idname:
            idname = path
        entry = {
            "id": ["api", kind, idname],
            "title": name,
            "url": f"https://airable.wifiradiofrontier.com/api/{urlpath}",
        }
        return entry

    def get_folder(name: str, path: str) -> dict:
        folder = get_entry("directory", name, path, name)
        folder["content"] = {"entries": []}  # a folder has place for entries...
        return folder

    ret = {}
    # the top level container
    ret["dir"] = get_folder("Radios", "dir")
    top_entries = []
    for folder, entries in radios.items():
        if folder == "station":
            continue
        label = entries["label"]
        top_entries.append(get_entry("directory", label, f"dir/{folder}"))
        ret[f"dir/{folder}"] = get_folder(label, f"dir/{folder}")
        if "station" not in entries:
            logging.warning(f"folder {folder} has no station")
            continue
        f_stations = []
        for key, entry in entries["station"].items():
            f_stations.append(get_entry("radio", entry["name"], f"{key}"))
        ret[f"dir/{folder}"]["content"]["entries"].extend(f_stations)
    if "station" in radios:
        for key, entry in radios["station"].items():
            top_entries.append(get_entry("radio", entry["name"], f"{key}"))
    ret["dir"]["content"]["entries"].extend(top_entries)
    return ret


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server, directory=None):
        self.directory = directory
        super().__init__(request, client_address, server)

    def __respond(self, code: int, data: bytes, content_type: str = "") -> None:
        if not content_type:
            if code in (400, 403, 404, 500):
                content_type = "text/plain"
            else:
                logging.warning("__respond: content_type is empty!")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(data)

    def generate_radios(self, path: str) -> None:
        subpath = path[5:]  # strip /api/
        if subpath not in radios_hash:
            return self.__respond(400, b"Bad request, generate_radios")
        resp = radios_hash[subpath]
        return self.__respond(200, json.dumps(resp).encode(), "application/json")

    def get_radio(self, path) -> None:
        if not path.startswith(("/api/radio/", "/api/play/")):  # paranoia, programming error...
            return self.__respond(500, b"get_radio internal error\n")
        command, key = path.split("/", maxsplit=3)[-2:]  # remove /api/radio or /api/play
        try:
            if "/" in key:  # from a folder
                folder = key.split("/", maxsplit=1)[0]
                radio = radios[folder]["station"][key]
            else:
                radio = radios["station"][key]
            name = radio["name"]
            logging.info(f"station {key} ({name}) requested")
            resp = {
                "content": {"entries": []},
                "description": name,
                "id": ["api", "radio", key],
                # "language": {"id": ["frontiersmart", "language", "5287211298011244"], "title": "German", "iso": "de"},
                # "place": {"id": ["frontiersmart", "place", "1234567890ABCDEF"], "title": "Place", "type": "city"},
                "slogan": f"slogan {key}",
                "images": [
                    {
                        "url": f"https://airable.wifiradiofrontier.com/logos/{key}.png",
                        "size": [1, 1],  # if size is [0,0], the logo is not loaded
                        "type": "cover",
                    }
                ],
                "streams": [
                    {
                        "codec": {
                            "bitrate": 96,
                            "name": "AAC",
                        },  # this does not matter, but must be present
                        "id": ["api", "stream", key],
                        "reliability": 1,
                        "url": f"https://airable.wifiradiofrontier.com/api/play/{key}",
                    }
                ],
                "title": name,
                "url": f"https://airable.wifiradiofrontier.com/api/radio/{key}",
            }
            if command == "play":
                resp["id"] = ["api", "redirect", key]
                resp["url"] = radio["url"]
                logging.info(f"redirecting to {radio['url']}")
            self.__respond(200, json.dumps(resp).encode(), "application/json")
        except KeyError:
            self.__respond(400, b"Bad request, get_radio\n")

    def get_logo(self, path: str) -> None:
        mime = "image/png"
        requested = (cwd / path.lstrip("/")).resolve()  # avoid path traversal
        if not str(requested).startswith(str(cwd / "logos")):
            return self.__respond(403, b"403 - Forbidden\n")
        try:
            with open(f"{requested}", "rb") as f:
                content = f.read()
            if requested.suffix.lower() in (".jpeg", ".jpg"):  # for future expansion ;-)
                mime = "image/jpeg"
        except (FileNotFoundError, IsADirectoryError):
            logging.info(f"{path} not found, send default")
            try:
                with open(cwd / "logos/logo-internet-radio.png", "rb") as f:
                    content = f.read()
            except FileNotFoundError:
                logging.error("logos/logo-internet-radio.png not found?")
                return self.__respond(404, b"404 - not found\n")
        self.__respond(200, content, mime)

    def do_GET(self):
        host = self.headers["Host"]
        path = self.path
        logging.info(f"Host: {host} Path: '{path}'")
        if "update.wifiradiofrontier.com" in host:
            logging.info("updates -- blocked")
            self.__respond(404, b"404 - updates blocked\n")
            return
        if path == "/":
            return self.__respond(200, json.dumps(index).encode(), "application/json")
        if path.startswith("/api/dir"):
            return self.generate_radios(path)
        if path.startswith(("/api/radio/", "/api/play/")):
            return self.get_radio(path)
        if path.startswith("/logos"):
            return self.get_logo(path)
        self.__respond(404, b"404 - not found\n")


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=str(cwd / "cert.pem"), keyfile=str(cwd / "key.pem"))
radios = load_stations(str(cwd / "stations.toml"))
radios_hash = build_radios_hash()

# print("====RADIOS====")
# print(json.dumps(radios, indent=2))
# print("====RADIOS_HASH====")
# print(json.dumps(radios_hash, indent=2))
try:
    httpd = HTTPServer(("0.0.0.0", 443), SimpleHTTPRequestHandler)
except PermissionError:  # only for testing, will not work with the radio...
    httpd = HTTPServer(("0.0.0.0", 8443), SimpleHTTPRequestHandler)
httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
httpd.serve_forever()
