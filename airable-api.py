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
import binascii
import json
import logging
import os
import signal
import threading
import tomllib
from pathlib import Path
from typing import Dict, Any, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# handle sigterm (container stop) and sigint (ctrl-C)
def handle_signal(sig, frame):
    sig_name = signal.Signals(sig).name
    logging.info(f"signal {sig} {sig_name}... exit")
    raise SystemExit


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

hostname = os.environ.get("AIRABLE_HOSTNAME", "airable.wifiradiofrontier.com")

radios_hash: Dict[str, Any] = {}
xmlid_rev: Dict[str, Any] = {}
cwd = Path(__file__).parent
logging.info(f"cwd: {cwd}")


# this is for the FS2340 modules, which only do https
index = {
    "id": ["airable", "directory", "index"],
    "title": "Index",
    "url": "https://airable.wifiradiofrontier.com/",
    "content": {
        "entries": [
            {  # radio stations
                "id": ["api", "service", "radio"],
                "title": "Internet radio",
                "url": "_APIBASE_/dir",
            },
            # {  # podcast feeds / not yet implemented
            #     "id": ["api", "service", "feed"],
            #     "title": "Podcasts",
            #     "url": "_APIBASE_/feeds"
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


def build_radios_hash() -> dict:

    def get_entry(kind: str, name: str, path: str, idname: str = "") -> dict:
        if not idname:
            idname = path
        if kind == "radio":
            urlpath = "radio"
            station_id = binascii.crc32(idname.encode())
            xmlid_rev[f"{station_id}"] = path  # string, because search is string also...
        else:
            urlpath = path
        entry = {
            "id": ["api", kind, idname],
            "title": name,
            "url": f"_APIBASE_/{urlpath}",
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
        self.port = server.server_port
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
        apiurl = f"https://{hostname}/api"
        return self.__respond(200, json.dumps(resp).replace("_APIBASE_", apiurl).encode(), "application/json")

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
                        "url": f"http://{hostname}/logos/{key}.png",
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
                        "url": f"_APIBASE_/play/{key}",
                    }
                ],
                "title": name,
                "url": f"_APIBASE_/radio/{key}",
            }
            if command == "play":
                resp["id"] = ["api", "redirect", key]
                resp["url"] = radio["url"]
                logging.info(f"redirecting to {radio['url']}")
            apiurl = f"https://{hostname}/api"
            self.__respond(200, json.dumps(resp).replace("_APIBASE_", apiurl).encode(), "application/json")
        except KeyError:
            self.__respond(400, b"Bad request, get_radio\n")

    def get_xmlradio(self, path) -> None:
        mime = "text/html; charset=UTF-8"  # it is actually XML, but that's what the frontier servers return...
        if not path.startswith("/xmlapi/radio/"):  # paranoia, programming error...
            return self.__respond(500, b"get_xmlradio internal error\n")
        command, key = path.split("/", maxsplit=3)[-2:]  # remove /api/radio or /api/play
        try:
            if "/" in key:  # from a folder
                folder = key.split("/", maxsplit=1)[0]
                radio = radios[folder]["station"][key]
            else:
                radio = radios["station"][key]
            name = radio["name"]
            logging.info(f"station {key} ({name}) requested")
            mime = "audio/x-mpegurl"
            logging.info(f"redirecting to {radio['url']}")
            return self.__respond(200, radio["url"].encode(), mime)
        except KeyError:
            self.__respond(400, b"Bad request, get_xmlradio\n")

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

    def get_station_xml(self, station: dict, mac: str) -> str:
        if station["id"][1] != "radio":
            return ""
        path = station["id"][2]
        title = station["title"]
        surl = station["url"]
        url = surl.replace("_APIBASE_", f"http://{self.hhost}/xmlapi")
        station_id = binascii.crc32(path.encode())
        url += f"/{path}"
        xml = (
            "  <Item>\n    <ItemType>Station</ItemType>\n"
            f"    <StationId>{station_id}</StationId>\n"
            f"    <StationName>{title}</StationName>\n"
            f"    <StationUrl>{url}{mac}</StationUrl>\n"
            f"    <StationDesc>{title} desc</StationDesc>\n"
            f"    <Logo>http://{hostname}/logos/{path}.png</Logo>\n"
            "    <StationFormat>Radio</StationFormat>\n"
            "    <StationLocation>Earth</StationLocation>\n"
            "    <StationBandWidth>32</StationBandWidth>\n"
            "    <StationMime>MP3</StationMime>\n"
            "    <Relia>5</Relia>\n"
            "  </Item>\n"
        )
        return xml

    def dict2xml(self, subpath: str, args: str = "") -> Tuple[bool, str]:
        try:
            data = radios_hash[subpath]["content"]["entries"]
        except KeyError:
            return False, f"Bad request, dict2xml {subpath}"
        """
        mac = ""
        if args:
            for arg in args.split("&"):
                if arg.startswith("mac="):
                    mac = f"?{arg}"
                    break
        """
        xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        xml += f"<ListOfItems>\n  <ItemCount>{len(data)}</ItemCount>\n"
        if subpath != "dir":
            xml += (
                "  <Item>\n    <ItemType>Previous</ItemType>\n"
                f"    <UrlPrevious>http://{self.hhost}/xmlapi/dir</UrlPrevious>\n"
                f"    <UrlPreviousBackUp>http://{self.hhost}/xmlapi/dir</UrlPreviousBackUp>\n"
                "  </Item>\n"
            )
        for i in data:
            itype = i["id"][1]
            if itype == "radio":
                # xml += self.get_station_xml(i, mac)
                xml += self.get_station_xml(i, "")
            else:
                ititle = i["title"]
                iurl = i["url"]
                url = iurl.replace("_APIBASE_", f"http://{self.hhost}/xmlapi")
                xml += (
                    "  <Item>\n"
                    "    <ItemType>Dir</ItemType>\n"
                    f"    <Title>{ititle}</Title>\n"
                    f"    <UrlDir>{url}</UrlDir>\n"
                    f"    <UrlDirBackup>{url}</UrlDirBackup>\n"
                    "  </Item>\n"
                )
        xml += "</ListOfItems>\n"
        return True, xml

    def generate_xmlradios(self, path: str) -> None:
        subpath = path[8:]  # strip /xmlapi/
        subpath, args = subpath.split("?", maxsplit=1)
        if subpath not in radios_hash:
            return self.__respond(400, b"Bad request, generate_xmlradios")
        ok, xml = self.dict2xml(subpath)
        if ok:
            return self.__respond(200, xml.encode(), "text/html; charset=UTF-8")
        return self.__respond(400, xml.encode())

    def handle_setupapp(self, fullpath: str) -> None:
        mime = "text/html; charset=UTF-8"  # it is actually XML, but that's what the frontier servers return...
        path, args = fullpath.split("?", maxsplit=1)
        pl = path.lower()
        if pl.endswith("/asp/browsexml/loginxml.asp"):
            if args == "token=0":
                return self.__respond(200, b"<EncryptedToken>3a3f5ac48a1dab4e</EncryptedToken>", mime)
            if args.startswith("gofile=&mac="):
                ok, xml = self.dict2xml("dir")
                if ok:
                    return self.__respond(200, xml.encode(), "text/html; charset=UTF-8")
                return self.__respond(400, xml.encode())
            return self.__respond(400, f"bad request, path '{fullpath}'".encode())
        if pl.endswith("/asp/browsexml/search.asp"):
            if args.startswith("sSearchtype=3&Search="):
                search = args.split("&", maxsplit=2)[1]
                station_id = search[7:]
                if station_id not in xmlid_rev:
                    return self.__respond(400, f"{station_id} not found".encode())
                station = xmlid_rev[station_id]  # News/dlf
                if "/" in station:
                    d = station.rsplit("/", maxsplit=1)[0]
                    d = f"dir/{d}"
                else:
                    d = "dir"
                for e in radios_hash[d]["content"]["entries"]:
                    if e["id"][2] == station:
                        logging.info(f"found station: {e}")
                        xml = (
                            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                            "<ListOfItems>\n  <ItemCount>1</ItemCount>\n"
                        )
                        xml += self.get_station_xml(e, "")
                        xml += "</ListOfItems>\n"
                        return self.__respond(200, xml.encode(), mime)
                logging.info(f" {station} not found???")
        return self.__respond(404, b"not found")

    def do_GET(self):
        host = self.headers["Host"]
        self.hhost = host
        if host == "hama2.wifiradiofrontier.com":  # the radio seems picky about the hostname the urls direct to...
            self.hhost = "hama.wifiradiofrontier.com"
        path = self.path
        logging.info(f"Host: {host}:{self.port} Path: '{path}'")
        if "update.wifiradiofrontier.com" in host:
            logging.info("updates -- blocked")
            self.__respond(404, b"404 - updates blocked\n")
            return
        if path == "/":
            apiurl = f"https://{hostname}/api"
            return self.__respond(200, json.dumps(index).replace("_APIBASE_", apiurl).encode(), "application/json")
        if path.startswith("/api/dir"):
            return self.generate_radios(path)
        if path.startswith(("/api/radio/", "/api/play/")):
            return self.get_radio(path)
        if path.startswith("/xmlapi/dir"):
            return self.generate_xmlradios(path)
        if path.startswith("/xmlapi/radio/"):
            return self.get_xmlradio(path)
        if path.startswith("/setupapp/"):
            return self.handle_setupapp(path)
        if path.startswith("/logos"):
            return self.get_logo(path)
        self.__respond(404, b"404 - not found\n")


radios = load_stations(str(cwd / "stations.toml"))
radios_hash = build_radios_hash()


def run_http_server(port, use_ssl=False):
    server_address = ("", port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    if use_ssl:
        # SSL-Kontext für Port 443 erstellen
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cwd / "cert.pem"), keyfile=str(cwd / "key.pem"))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        logging.info(f"HTTPS-Server started on port {port}")
    else:
        logging.info(f"HTTP-Server started on port {port}")
    httpd.serve_forever()


# print("====RADIOS====")
# print(json.dumps(radios, indent=2))
# print("====RADIOS_HASH====")
# print(json.dumps(radios_hash, indent=2))
def main():
    try:
        # run http (port 80) in its own thread
        thread_80 = threading.Thread(target=run_http_server, args=(80, False))
        thread_80.daemon = True
        thread_80.start()
        # run HTTPS (port 443) in main thread
        run_http_server(443, True)
    except PermissionError:  # only for testing, will not work with the radio...
        thread_80 = threading.Thread(target=run_http_server, args=(8080, False))
        thread_80.daemon = True
        thread_80.start()
        run_http_server(8443, True)


if __name__ == "__main__":
    main()
