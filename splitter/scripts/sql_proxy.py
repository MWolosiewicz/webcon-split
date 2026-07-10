"""Forwarder TCP: host -> SQL Server na VM Hyper-V.

Potrzebny, gdy splitter dziala w kontenerze Docker Desktop (WSL2), ktory nie ma
trasy do podsieci Hyper-V Default Switch, a host ja ma. Kontener laczy sie
z host.docker.internal:14330, a proxy przekazuje ruch do SQL Servera na VM.

Uzycie:
    python scripts/sql_proxy.py [--listen-port 14330] [--target 172.19.180.146:1433]
"""

import argparse
import asyncio


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        writer.close()


async def handle(client_reader, client_writer, target_host: str, target_port: int) -> None:
    try:
        server_reader, server_writer = await asyncio.open_connection(target_host, target_port)
    except OSError as exc:
        print(f"Nie mozna polaczyc z {target_host}:{target_port}: {exc}")
        client_writer.close()
        return
    await asyncio.gather(
        pipe(client_reader, server_writer),
        pipe(server_reader, client_writer),
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=14330)
    parser.add_argument("--target", default="172.19.180.146:1433")
    args = parser.parse_args()

    target_host, target_port = args.target.rsplit(":", 1)
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, target_host, int(target_port)),
        args.listen_host,
        args.listen_port,
    )
    print(f"SQL proxy: {args.listen_host}:{args.listen_port} -> {args.target}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
