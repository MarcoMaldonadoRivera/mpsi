# -*- coding: utf-8 -*-
"""Backend API Flask para monitoreo SNMP de impresoras en red."""

import concurrent.futures
from flask import Flask, jsonify, render_template, request, send_from_directory

from snmp_utils import query_printer

app = Flask(__name__)

# Configuración por defecto
DEFAULT_COMMUNITY = "public"
DEFAULT_PORT = 161
DEFAULT_TIMEOUT = 3


@app.route("/")
def index():
    """Página principal (frontend)."""
    initial_hosts = request.args.get("hosts", "")
    return render_template("index.html", initial_hosts=initial_hosts)


@app.route("/fondo.png")
def serve_fondo():
    """Sirve la imagen de fondo/bienvenida desde la raíz."""
    return send_from_directory(".", "fondo.png")


@app.route("/Banner.png")
def serve_banner():
    """Sirve el banner de Quiénes Somos desde la raíz."""
    return send_from_directory(".", "Banner.png")


@app.route("/api/printers", methods=["GET"])
def get_printers():
    """Consulta una o varias impresoras conservando el orden de entrada.

    Parámetros:
        hosts: IP o lista de IPs separadas por coma. 
               Ej: /api/printers?hosts=192.168.1.10,192.168.1.11
        community: comunidad SNMP (opcional, default 'public')
        port: puerto SNMP (opcional, default 161)
        timeout: timeout en segundos (opcional, default 3)
    """
    hosts_param = request.args.get("hosts", "")
    community = request.args.get("community", DEFAULT_COMMUNITY) or DEFAULT_COMMUNITY
    
    try:
        port = int(request.args.get("port", DEFAULT_PORT))
    except (ValueError, TypeError):
        port = DEFAULT_PORT
        
    try:
        timeout = int(request.args.get("timeout", DEFAULT_TIMEOUT))
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT

    if not hosts_param:
        return jsonify({"error": "Falta el parámetro 'hosts' (IPs separadas por coma)."}), 400

    host_list = [h.strip() for h in hosts_param.split(",") if h.strip()]

    if not host_list:
        return jsonify({"error": "La lista de hosts ingresada no contiene IPs válidas."}), 400

    results_by_host = {}
    errors = []

    def fetch_host(h):
        try:
            return h, query_printer(h, community, port, timeout), None
        except Exception as exc:
            return h, None, str(exc)

    # Ejecución concurrente con ThreadPoolExecutor manteniendo el orden
    max_workers = min(len(host_list), 20)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_host, host) for host in host_list]
        for future in concurrent.futures.as_completed(futures):
            host, data, err = future.result()
            if err:
                errors.append({"host": host, "error": err})
            else:
                results_by_host[host] = data

    # Reconstruir lista ordenada según el input del usuario
    ordered_results = []
    for host in host_list:
        if host in results_by_host:
            ordered_results.append(results_by_host[host])

    return jsonify({"impresoras": ordered_results, "errores": errors})


@app.route("/api/health", methods=["GET"])
def health():
    """Health check del servicio."""
    return jsonify({"status": "ok", "service": "Monitor SNMP de Impresoras"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)