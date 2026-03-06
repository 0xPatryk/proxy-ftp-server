#!/usr/bin/env python3
import io
import logging
import os
import posixpath
from datetime import datetime
from ftplib import FTP

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ProxyFS(AbstractedFS):
    """Filesystem that proxies operations to an upstream FTP server."""

    def __init__(self, root, cmd_channel):
        super().__init__(root, cmd_channel)
        self.upstream = (
            cmd_channel.upstream if hasattr(cmd_channel, "upstream") else None
        )

    def _require_upstream(self) -> FTP:
        if not self.upstream:
            raise OSError("upstream FTP not connected")
        return self.upstream

    def _norm(self, path: str) -> str:
        return self.ftpnorm(path)

    def chdir(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        up.cwd(target)
        self.cwd = target

    def listdir(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        names = up.nlst(target)
        out = []
        for name in names:
            clean = name.rstrip("/")
            base = posixpath.basename(clean)
            out.append(base if base else clean)
        return out

    def format_list(self, basedir, listing, ignore_err=True):
        up = self._require_upstream()
        target = self._norm(basedir)
        lines = []
        up.retrlines(f"LIST {target}", lines.append)
        for line in lines:
            yield (line + "\r\n").encode(
                self.cmd_channel.encoding, self.cmd_channel.unicode_errors
            )

    def format_mlsx(self, basedir, listing, perms, facts, ignore_err=True):
        up = self._require_upstream()
        target = self._norm(basedir)
        try:
            entries = list(up.mlsd(target))
        except Exception:
            entries = [(name, {}) for name in self.listdir(target)]

        for name, meta in entries:
            facts_map = {}
            if "type" in facts:
                facts_map["type"] = meta.get("type", "file")
            if "size" in facts and "size" in meta:
                facts_map["size"] = meta["size"]
            if "modify" in facts and "modify" in meta:
                facts_map["modify"] = meta["modify"]
            if "perm" in facts and "perm" in meta:
                facts_map["perm"] = meta["perm"]

            factstring = "".join(f"{k}={facts_map[k]};" for k in sorted(facts_map))
            yield f"{factstring} {name}\r\n".encode(
                self.cmd_channel.encoding, self.cmd_channel.unicode_errors
            )

    def isdir(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        cur = up.pwd()
        try:
            up.cwd(target)
            return True
        except Exception:
            return False
        finally:
            try:
                up.cwd(cur)
            except Exception:
                pass

    def isfile(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        if self.isdir(target):
            return False
        try:
            up.size(target)
            return True
        except Exception:
            return False

    def getsize(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        size = up.size(target)
        if size is None:
            raise OSError(f"size unavailable for {target}")
        return size

    def getmtime(self, path):
        up = self._require_upstream()
        target = self._norm(path)
        resp = up.sendcmd(f"MDTM {target}")
        # 213 YYYYMMDDHHMMSS
        ts = resp.split(" ", 1)[1].strip()
        dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
        return dt.timestamp()

    def realpath(self, path):
        return self._norm(path)

    def open(self, filename, mode):
        up = self._require_upstream()
        target = self._norm(filename)

        if "r" in mode:
            buffer = io.BytesIO()
            up.retrbinary(f"RETR {target}", buffer.write)
            buffer.seek(0)
            return buffer

        return ProxyFile(target, up)

    def mkdir(self, path):
        up = self._require_upstream()
        up.mkd(self._norm(path))

    def rmdir(self, path):
        up = self._require_upstream()
        up.rmd(self._norm(path))

    def remove(self, path):
        up = self._require_upstream()
        up.delete(self._norm(path))

    def rename(self, src, dst):
        up = self._require_upstream()
        up.rename(self._norm(src), self._norm(dst))


class ProxyFile(io.BytesIO):
    """Write buffer uploaded to upstream on close."""

    def __init__(self, filename: str, upstream: FTP):
        super().__init__()
        self.filename = filename
        self.upstream = upstream
        self._uploaded = False

    def close(self):
        if not self._uploaded:
            try:
                self.seek(0)
                self.upstream.storbinary(f"STOR {self.filename}", self)
            except Exception as e:
                logging.error(f"close/upload({self.filename}) failed: {e}")
            self._uploaded = True
        super().close()


class ProxyFTPHandler(FTPHandler):
    """FTP handler that proxies authenticated sessions to upstream FTP."""

    abstracted_fs = ProxyFS

    def __init__(self, conn, server, ioloop=None):
        super().__init__(conn, server, ioloop)
        self.upstream = None
        self.target_host = os.getenv("TARGET_HOST", "ftp.example.com")
        self.target_port = int(os.getenv("TARGET_PORT", "21"))
        self.target_user = os.getenv("TARGET_USER", "user")
        self.target_pass = os.getenv("TARGET_PASS", "pass")

    def on_login(self, username):
        try:
            self.upstream = FTP(timeout=60)
            self.upstream.connect(self.target_host, self.target_port)
            self.upstream.login(self.target_user, self.target_pass)
            self.upstream.set_pasv(True)
            fs = self.fs
            if fs is not None and isinstance(fs, ProxyFS):
                fs.upstream = self.upstream
            logging.info(f"Proxied {username} -> {self.target_host}:{self.target_port}")
        except Exception as e:
            logging.error(f"Upstream connection failed: {e}")
            self.upstream = None

    def on_logout(self, username):
        if self.upstream:
            try:
                self.upstream.quit()
            except Exception:
                pass
            self.upstream = None

        super().on_logout(username)

    def handle_error(self):
        if self.upstream:
            try:
                self.upstream.quit()
            except Exception:
                pass
            self.upstream = None
        super().handle_error()


if __name__ == "__main__":
    local_user = os.getenv("LOCAL_USER", "proxy")
    local_pass = os.getenv("LOCAL_PASS", "proxypass")

    authorizer = DummyAuthorizer()
    authorizer.add_user(local_user, local_pass, "/", perm="elradfmwMT")

    handler = ProxyFTPHandler
    handler.authorizer = authorizer
    handler.passive_ports = range(  # pyright: ignore[reportAttributeAccessIssue]
        int(os.getenv("PASV_MIN", "41000")), int(os.getenv("PASV_MAX", "41011"))
    )

    handler.masquerade_address = os.getenv("PUBLIC_IP")  # pyright: ignore[reportAttributeAccessIssue]

    print("FTP Proxy starting...")
    print(f"Local login: {local_user}")
    print(
        f"Target: {os.getenv('TARGET_HOST', 'N/A')} ({os.getenv('TARGET_USER', 'N/A')})"
    )
    server = FTPServer(("0.0.0.0", 21), handler)
    server.max_cons = 50
    server.max_cons_per_ip = 5
    server.serve_forever()
