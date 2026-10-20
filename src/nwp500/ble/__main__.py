"""``python -m nwp500.ble``: scan for the heater and dump its data blocks."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import (
    NOT_ADVERTISING_HINT,
    NWP500_RESPONDING_CLASSES,
    ClassCode,
    NavienBleClient,
    SubStatus,
    answers_class_codes,
    best_heater,
    scan,
)


def _class_name(code: int) -> str:
    try:
        return ClassCode(code).name
    except ValueError:
        return str(code)


def _parse_class(text: str) -> tuple[int, int | None]:
    name, _, length = text.partition(":")
    code = (
        ClassCode[name.upper()]
        if name.upper() in ClassCode.__members__
        else int(name)
    )
    return int(code), (int(length) if length else None)


async def _print_tou(ble: NavienBleClient) -> None:
    # The block read above holds only the first twelve slots; the plan is
    # read whole here.
    try:
        records = await ble.read_tou_records()
    except (TimeoutError, ValueError) as e:
        print(f"  (not decoded: {e or 'no reply'})")
        return
    for r in records:
        print(
            f"  season={r.season:#05x} week={r.week:#04x} "
            f"{r.start_hour:02}:{r.start_min:02}-"
            f"{r.end_hour:02}:{r.end_min:02} "
            f"price={r.decoded_price_min:g}-{r.decoded_price_max:g}"
        )


def _print_sub_status(data: bytes) -> None:
    try:
        ssd = SubStatus.parse(data)
    except ValueError as e:
        print(f"  (not decoded: {e})")
        return
    print(
        f"  dip_switch_1={ssd.dip_switch_1:#06x} "
        f"dip_switch_2={ssd.dip_switch_2:#06x} (layout unconfirmed)"
    )


async def _scan(args: argparse.Namespace) -> int:
    found = await scan(args.seconds)
    if not found:
        print(NOT_ADVERTISING_HINT)
        return 1
    for address, name, rssi in sorted(found, key=lambda t: -t[2]):
        note = "" if answers_class_codes(name) else "  (Wi-Fi setup mode)"
        print(f"{address}  rssi={rssi}  {name}{note}")
    return 0


async def _read(args: argparse.Namespace) -> int:
    address = args.address
    if not address:
        best = best_heater(await scan(args.seconds))
        if best is None:
            print(NOT_ADVERTISING_HINT)
            return 1
        address, name, _ = best
        print(f"using {name} at {address}")
    results: list[dict[str, object]] = []
    async with NavienBleClient(address) as ble:
        if args.classes:
            targets = [_parse_class(c) for c in args.classes]
        else:
            # The classes an NWP500 answers; the boiler parameter classes
            # 51-54 only time out on it and are read when named.
            targets = [(c, None) for c in sorted(NWP500_RESPONDING_CLASSES)]
        for code, length in targets:
            try:
                pkt = await ble.read(code, length)
            except (TimeoutError, ValueError) as e:
                print(f"{_class_name(code)}: {e or 'no reply'}")
                continue
            print(
                f"{pkt.class_name:6} len={len(pkt.data):3} "
                f"crc_ok={pkt.crc_ok} {pkt.data.hex()}"
            )
            if pkt.class_code == ClassCode.TOU_PLAN and pkt.crc_ok:
                await _print_tou(ble)
            elif pkt.class_code == ClassCode.SSD and pkt.crc_ok:
                _print_sub_status(pkt.data)
            results.append(
                {
                    "class": pkt.class_code,
                    "name": pkt.class_name,
                    "data": pkt.data.hex(),
                    "crc_ok": pkt.crc_ok,
                }
            )
        for raw in ble.unparsed_notifications:
            print("unparsed notification:", raw.hex())
    if not results:
        print("No blocks read.", file=sys.stderr)
        return 1
    if args.out:
        await asyncio.to_thread(
            Path(args.out).write_text, json.dumps(results, indent=1)
        )
        print("saved", args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m nwp500.ble", description=__doc__
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="list heaters advertising nearby")
    s.add_argument("--seconds", type=float, default=10.0)
    s.set_defaults(func=_scan)
    r = sub.add_parser("read", help="read data blocks (read-only)")
    r.add_argument("--address", help="device address; scans when omitted")
    r.add_argument(
        "--seconds", type=float, default=15.0, help="scan time when no address"
    )
    r.add_argument("--out", help="write the blocks as JSON here")
    r.add_argument(
        "classes", nargs="*", help="CLASS[:LEN], e.g. SPD:59 or 240:58"
    )
    r.set_defaults(func=_read)
    args = p.parse_args(argv)
    result: int = asyncio.run(args.func(args))
    return result


if __name__ == "__main__":
    sys.exit(main())
