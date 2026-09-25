"""Read single files out of a huge remote ZIP using HTTP range requests (no full download)."""
import io
import requests


class HttpRangeFile(io.RawIOBase):
    def __init__(self, url, block=1 << 20):
        self.session = requests.Session()
        r = self.session.head(url, allow_redirects=True, timeout=60)
        r.raise_for_status()
        self.url = r.url  # final CDN URL after redirects
        self.size = int(r.headers["Content-Length"])
        self.pos = 0
        self.block = block
        self.cache = {}
        self.requests = 0

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _fetch(self, start, end):
        self.requests += 1
        r = self.session.get(self.url, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=120)
        r.raise_for_status()
        return r.content

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        if n > 4 * self.block:  # big reads: fetch directly
            data = self._fetch(self.pos, self.pos + n)
        else:
            out = bytearray()
            end = self.pos + n
            p = self.pos
            while p < end:
                b = p // self.block
                if b not in self.cache:
                    if len(self.cache) > 64:
                        self.cache.clear()
                    s = b * self.block
                    self.cache[b] = self._fetch(s, min(s + self.block, self.size))
                chunk = self.cache[b]
                off = p - b * self.block
                take = min(len(chunk) - off, end - p)
                out += chunk[off:off + take]
                p += take
            data = bytes(out)
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)
