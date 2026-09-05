#!/usr/bin/env python3
"""Public, read-only Hyperliquid BTC collector. Python 3.11+, standard library only."""
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

API = 'https://api.hyperliquid.xyz/info'
LEADER = 'https://stats-data.hyperliquid.xyz/Mainnet/leaderboard'
ROOT = Path(__file__).resolve().parent / 'data'
ADDRESS = re.compile(r'^0x[0-9a-f]{40}$')


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


class Client:
    def __init__(self, interval=0.35):
        self.interval = max(0.35, interval)
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.cooldown = 0.0

    def pace(self):
        while True:
            with self.lock:
                now = time.monotonic()
                delay = max(self.next_at, self.cooldown) - now
                if delay <= 0:
                    self.next_at = now + self.interval
                    return
            time.sleep(min(delay, 1.0))

    def request(self, body=None, url=API):
        for attempt in range(4):
            self.pace()
            request = urllib.request.Request(
                url, data=json.dumps(body).encode() if body else None,
                headers={'Content-Type': 'application/json', 'User-Agent': 'HL-Snapshot-Collector/3'})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise
                retry = number(exc.headers.get('Retry-After')) or 0
                if attempt == 3:
                    raise
                with self.lock:
                    self.cooldown = max(self.cooldown, time.monotonic() + max(retry, 3 * 2 ** attempt))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError('Request failed')


def read(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def roster(client, limit):
    old = read(ROOT / 'wallets.json', {})
    if old.get('limit') == limit and old.get('addresses') and os.getenv('REFRESH_WALLETS') != '1':
        return old['addresses']
    rows = client.request(url=LEADER).get('leaderboardRows')
    if not isinstance(rows, list):
        raise ValueError('Leaderboard schema changed; use data/wallets.json with addresses and limit.')
    rows.sort(key=lambda r: number(r.get('accountValue')) or 0, reverse=True)
    addresses = list(dict.fromkeys(str(r.get('ethAddress', '')).lower() for r in rows))
    addresses = [a for a in addresses if ADDRESS.fullmatch(a)]
    if limit:
        addresses = addresses[:limit]
    if not addresses:
        raise ValueError('No leaderboard wallets')
    write(ROOT / 'wallets.json', {'limit': limit, 'createdAt': stamp(), 'addresses': addresses})
    return addresses


def normalize(wallet, items):
    rows, skipped = [], 0
    for item in items:
        p = item.get('position', item)
        if p.get('coin') != 'BTC':
            continue
        qty, price = number(p.get('szi')), number(p.get('liquidationPx'))
        if not qty or not price or price < 0:
            skipped += 1
            continue
        rows.append({'wallet': wallet, 'coin': 'BTC', 'szi': qty,
                     'entryPx': number(p.get('entryPx')), 'liquidationPx': price,
                     'leverage': p.get('leverage'), 'positionValue': number(p.get('positionValue')),
                     'direction': 'long' if qty > 0 else 'short',
                     'liquidationNotional': abs(qty) * price, 'collectedAt': stamp()})
    return rows, skipped


def aggregate(positions, mid, size=250):
    bins, wrong = {}, 0
    for p in positions:
        price, direction = p['liquidationPx'], p['direction']
        if (direction == 'long' and price >= mid) or (direction == 'short' and price <= mid):
            wrong += 1
            continue
        k = math.floor(price / size)
        b = bins.setdefault(k, {'priceLow': k * size, 'priceHigh': (k + 1) * size,
                               'long': 0, 'short': 0, 'longQty': 0, 'shortQty': 0})
        b[direction] += abs(p['szi']) * price
        b[direction + 'Qty'] += abs(p['szi'])
    return [bins[k] for k in sorted(bins)], wrong


def main():
    ROOT.mkdir(exist_ok=True)
    limit = int(os.getenv('WALLET_LIMIT', '5000'))
    if limit < 0:
        raise ValueError('WALLET_LIMIT must be >=0; 0 selects all leaderboard wallets')
    client = Client(float(os.getenv('REQUEST_INTERVAL', '0.35')))
    wallets = roster(client, limit)
    started = stamp()
    positions, failed = [], []
    skipped = success = 0
    print(f'Start: {len(wallets)} wallets; frozen roster, BTC, $250 bins', flush=True)

    def collect(wallet):
        response = client.request({'type': 'clearinghouseState', 'user': wallet})
        if not isinstance(response, dict) or not isinstance(response.get('assetPositions'), list):
            raise ValueError('assetPositions missing')
        return normalize(wallet, response['assetPositions'])

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect, w): w for w in wallets}
        for count, future in enumerate(cf.as_completed(futures), 1):
            try:
                rows, count_skipped = future.result()
                positions.extend(rows)
                skipped += count_skipped
                success += 1
            except Exception as exc:
                failed.append({'wallet': futures[future], 'error': str(exc)[:250]})
            if count % 100 == 0 or count == len(wallets):
                print(f'{count}/{len(wallets)} success={success} failed={len(failed)} BTC positions={len(positions)}', flush=True)
    # A failed run must not replace a good published snapshot.
    if success / len(wallets) < 0.90:
        raise RuntimeError(f'Only {success}/{len(wallets)} successful; previous data retained')
    mids = client.request({'type': 'allMids'})
    mid = number(mids.get('BTC'))
    if not mid or mid <= 0:
        raise ValueError('BTC price missing')
    finished = stamp()
    bins, wrong = aggregate(positions, mid)
    snapshot = {'time': int(time.time() * 1000), 'startedAt': started, 'coin': 'BTC', 'mid': mid,
                'bins': bins, 'success': success, 'requested': len(wallets), 'skipped': skipped,
                'wrongSide': wrong, 'positions': len(positions), 'binSize': 250,
                'rosterHash': hashlib.sha256('\n'.join(wallets).encode()).hexdigest()[:16]}
    h = read(ROOT / 'history.json', {'format': 'hl-history-v2', 'history': [], 'demo': False})
    if h.get('format') != 'hl-history-v2' or not isinstance(h.get('history'), list):
        raise ValueError('history.json schema mismatch')
    h['history'] = (h['history'] + [snapshot])[-180:]
    h.update({'updatedAt': finished, 'demo': False})
    latest = {'version': 1, 'source': 'live', 'startedAt': started, 'finishedAt': finished,
              'priceAt': finished, 'requested': len(wallets), 'success': success, 'failed': failed,
              'skipped': skipped, 'positions': positions, 'mids': {'BTC': mid}}
    # Price failure doesn't discard collected liquidation data.
    try:
        candles = client.request({'type': 'candleSnapshot', 'req': {'coin': 'BTC', 'interval': '5m',
                                  'startTime': h['history'][0]['time'] - 300000,
                                  'endTime': snapshot['time']}})
        if isinstance(candles, list):
            clean = [{'t': int(c['t']), 'c': float(c['c'])} for c in candles
                     if number(c.get('t')) is not None and (number(c.get('c')) or 0) > 0]
            write(ROOT / 'candles.json', clean)
    except Exception as exc:
        print(f'Price history not refreshed: {exc}', flush=True)
    write(ROOT / 'latest.json', latest)
    write(ROOT / 'history.json', h)
    print(f'Saved {len(h["history"])} snapshots. Positions are sampled over {started} to {finished}.', flush=True)


if __name__ == '__main__':
    main()
