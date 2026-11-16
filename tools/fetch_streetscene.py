"""Fetch a small part of the Street Scene dataset without downloading all 49 GB.

    uv run python tools/fetch_streetscene.py list
    uv run python tools/fetch_streetscene.py get PREFIX [PREFIX ...] --every 3 --limit-gb 1.5

The dataset is one large zip file. The server allows reading byte ranges, so
this reads the zip's table of contents and then only the files asked for.

Street Scene: Ramachandra and Jones, "Street Scene: A new dataset and
evaluation protocol for video anomaly detection", WACV 2020.
Zenodo DOI 10.5281/zenodo.10870471, licence CC BY-SA 4.0.
"""
from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import httpx

URL = "https://zenodo.org/api/records/10870472/files/StreetScene.zip/content"
OUT = Path("data/streetscene")
BLOCK = 4 * 1024 * 1024


class RemoteFile(io.RawIOBase):
    """A read-only, seekable view of a file on a web server, read in blocks."""

    def __init__(self, url: str):
        self.client = httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": "python-httpx"})
        head = self._range(0, 0)
        self.size = int(head.headers["content-range"].split("/")[1])
        self.url, self.pos, self.blocks, self.fetched = url, 0, {}, 0

    def _range(self, start: int, end: int) -> httpx.Response:
        for attempt in range(6):
            try:
                response = self.client.get(URL, headers={"Range": f"bytes={start}-{end}"})
                if response.status_code == 429:
                    time.sleep(float(response.headers.get("retry-after", 30)) + 1)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPError:
                time.sleep(5 * (attempt + 1))
        raise SystemExit("The server kept refusing; try again later.")

    def read_range(self, start: int, length: int) -> bytes:
        data = self._range(start, start + length - 1).content
        self.fetched += len(data)
        return data

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        out = bytearray()
        while n > 0:
            index, inner = divmod(self.pos, BLOCK)
            if index not in self.blocks:
                if len(self.blocks) > 16:
                    self.blocks.pop(next(iter(self.blocks)))
                self.blocks[index] = self.read_range(index * BLOCK, min(BLOCK, self.size - index * BLOCK))
            piece = self.blocks[index][inner:inner + n]
            out += piece
            self.pos += len(piece)
            n -= len(piece)
        return bytes(out)


def listing() -> list[dict]:
    cache = OUT / "listing.json"
    if cache.exists():
        return json.loads(cache.read_text())
    remote = RemoteFile(URL)
    with zipfile.ZipFile(remote) as archive:
        items = [
            {"name": i.filename, "size": i.compress_size, "offset": i.header_offset, "method": i.compress_type}
            for i in archive.infolist() if not i.is_dir()
        ]
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items))
    print(f"Read the table of contents: {len(items)} files, {remote.fetched / 1e6:.1f} MB fetched.")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=["list", "get"])
    parser.add_argument("prefixes", nargs="*")
    parser.add_argument("--every", type=int, default=1, help="keep every Nth picture of a sequence")
    parser.add_argument("--limit-gb", type=float, default=1.5)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    items = listing()
    if args.action == "list":
        folders: dict[str, list[int]] = {}
        for item in items:
            folder = item["name"].rsplit("/", 1)[0]
            entry = folders.setdefault(folder, [0, 0])
            entry[0] += 1
            entry[1] += item["size"]
        for folder, (count, size) in sorted(folders.items()):
            print(f"{count:6d} files {size / 1e6:9.1f} MB  {folder}")
        return

    wanted = []
    for prefix in args.prefixes:
        group = sorted((i for i in items if i["name"].startswith(prefix)), key=lambda i: i["name"])
        pictures = [i for i in group if i["name"].lower().endswith((".jpg", ".png"))]
        others = [i for i in group if i not in pictures]
        wanted += others + pictures[:: args.every]
    total = sum(i["size"] for i in wanted)
    print(f"{len(wanted)} files, {total / 1e9:.2f} GB")
    if total > args.limit_gb * 1e9:
        raise SystemExit(f"That is over the {args.limit_gb} GB limit. Nothing fetched.")

    import threading
    import zlib
    from concurrent.futures import ThreadPoolExecutor

    local = threading.local()
    todo = [i for i in wanted if not (OUT / "files" / i["name"]).exists()]
    print(f"{len(todo)} still to fetch", flush=True)

    def fetch(item: dict) -> int:
        if not hasattr(local, "remote"):
            local.remote = RemoteFile(URL)
        remote = local.remote
        # Local header: 30 fixed bytes, then the name and an extra field.
        raw = remote.read_range(item["offset"], 30 + 600 + item["size"])
        name_len = int.from_bytes(raw[26:28], "little")
        extra_len = int.from_bytes(raw[28:30], "little")
        start = 30 + name_len + extra_len
        body = raw[start:start + item["size"]]
        if len(body) < item["size"]:
            body += remote.read_range(item["offset"] + len(raw), item["size"] - len(body))
        if item["method"] == 8:
            body = zlib.decompress(body, -15)
        elif item["method"] != 0:
            raise SystemExit(f"Unknown compression in {item['name']}")
        target = OUT / "files" / item["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        partial.write_bytes(body)
        partial.rename(target)  # a file that exists is always complete
        time.sleep(args.workers * 0.55)  # all workers together stay under ~110 requests a minute
        return len(body)

    done = 0
    with ThreadPoolExecutor(args.workers) as pool:
        for number, size in enumerate(pool.map(fetch, todo), start=1):
            done += size
            if number % 200 == 0:
                print(f"{number}/{len(todo)} files, {done / 1e6:.0f} MB", flush=True)
    print(f"Finished: {len(wanted)} files in {OUT / 'files'}")


if __name__ == "__main__":
    main()
