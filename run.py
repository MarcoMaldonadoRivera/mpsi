# -*- coding: utf-8 -*-
"""Script de arranque del Monitor SNMP de Impresoras.

Uso:
    python run.py [host] [-p PORT] [-c COMMUNITY] [-t TIMEOUT]

Ejemplos:
    python run.py 192.168.1.50
    python run.py 192.168.1.10,192.168.1.11 -p 8080 -c public
"""

import argparse
from app import app


def main():
    parser = argparse.ArgumentParser(
        description="Monitor SNMP de impresoras en red (Flask + pysnmp)."
    )
    parser.add_argument(
        "host",
        nargs="?",
        default=None,
        help="IP o IPs separadas por coma a precargar en la interfaz.",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=5000,
        help="Puerto del servidor web (default: 5000).",
    )
    parser.add_argument(
        "-c", "--community",
        default="public",
        help="Comunidad SNMP por defecto (default: public).",
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=3,
        help="Timeout SNMP en segundos por consulta (default: 3).",
    )
    args = parser.parse_args()

    app.config["DEFAULT_COMMUNITY"] = args.community
    app.config["DEFAULT_TIMEOUT"] = args.timeout

    url = f"http://127.0.0.1:{args.port}"
    if args.host:
        url += f"/?hosts={args.host}"

    print("=" * 65)
    print("  🖨️  Monitor SNMP de Impresoras en Red")
    print("  =======================================")
    print(f"  Acceso Web:     {url}")
    print(f"  Comunidad SNMP: {args.community}")
    print(f"  Timeout SNMP:   {args.timeout}s")
    print("  Presiona CTRL+C para detener el servidor.")
    print("=" * 65)

    app.run(host="0.0.0.0", port=args.port, debug=True)


if __name__ == "__main__":
    main()