#!/usr/bin/python3

from http.server import HTTPServer, BaseHTTPRequestHandler
from http.client import InvalidURL
import base64
import ssl
import json
import logging
import urllib.request
from pathlib import Path
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

cache: dict = {}

cwd = Path(__file__).parent
logging.info(f"cwd: {cwd}")


@dataclass
class HttpResponse:
    status_code: int
    headers: dict
    content: bytes


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def __respond(self, code: int, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def get(self, url: str, headers: dict) -> HttpResponse:
        # cannot use requests, because it strips additional double slashes // in url
        logging.info(f"GET {url}")
        for k, v in headers.items():
            logging.info(f"> {k}: {v}")
        req = urllib.request.Request(url, headers=headers)
        try:
            context = ssl._create_unverified_context()
            u = urllib.request.urlopen(req, context=context)
        except urllib.error.HTTPError as e:
            u = e
        except urllib.error.URLError as e:
            return HttpResponse(status_code=500, headers={}, content=str(e).encode("utf-8"))
        except InvalidURL as e:
            return HttpResponse(status_code=500, headers={}, content=str(e).encode("utf-8"))
        head = {}
        for k, v in u.headers.items():
            head[k] = v
        return HttpResponse(status_code=u.status, headers=head, content=u.read())

    def json_encode(self, obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("utf-8")
        raise TypeError(f"Type {type(obj)} not serializable")

    def do_GET(self):
        host = self.headers["Host"]
        path = self.path
        outfilebase = f"{cwd}/{host}{path}"
        assets = host == "assets.wifiradiofrontier.com"
        # this adds an additional / between host and path (path already starts with /)
        # this is needed for assets, or it will return 404 always.
        url = f"https://{host}/{path}"
        logging.info(f"Host: {host} Path: {path}")
        if "update.wifiradiofrontier.com" in host:
            logging.info("updates -- blocked")
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 - updates blocked\n")
            return
        fromcache = url in cache
        if fromcache:
            logging.info("from cache")
            req = cache[url]
            # print(type(req))
            # print(req)
            # print(json.dumps(asdict(req), default=self.json_encode))
        else:
            req = self.get(url, headers=self.headers)
            if req.status_code == 200:
                cache[url] = req
        self.send_response(req.status_code)
        for k, v in req.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(req.content)
        if assets:
            return
        if fromcache:
            return
        if req.status_code != 200:
            logging.info(f"error: {req.status_code}")
            logging.info(req.content.decode())
            return
        logging.info("save cache...")
        Path(outfilebase).parent.mkdir(parents=True, exist_ok=True)
        with open(f"{outfilebase}.req", "wb") as f:
            f.write(bytes(f"{self.command} {self.path} {self.request_version}\n", encoding="utf-8"))
            f.write(bytes(self.headers))
        with open(f"{outfilebase}.ret", "wb") as f:
            f.write(bytes(json.dumps(dict(req.headers)), encoding="utf-8"))
        if req.content:
            with open(f"{outfilebase}.content", "wb") as f:
                f.write(req.content)


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=f"{cwd}/cert.pem", keyfile=f"{cwd}/key.pem")
context.check_hostname = False

httpd = HTTPServer(("0.0.0.0", 443), SimpleHTTPRequestHandler)
httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
httpd.serve_forever()
