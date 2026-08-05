# -*- coding: utf-8 -*-
"""Utilidades SNMP optimizadas para consultar impresoras en red.

Consulta información de impresoras mediante SNMP v2c:
  - Modelo (hrDeviceDescr / sysDescr)
  - Serie (prtGeneralSerialNumber)
  - Alertas y Estado: Puerta abierta, Falta papel, Sin tóner
  - Contadores de páginas (total, color, monocromo)
  - Niveles de suministros (tóner/tinta) con tabla unificada

Usa pysnmp 7.x (API asíncrona).
"""

import asyncio

from pysnmp.hlapi.v1arch.asyncio import (
    CommunityData,
    ObjectIdentity,
    ObjectType,
    SnmpDispatcher,
    UdpTransportTarget,
    get_cmd,
    walk_cmd,
)

# OIDs estándar (RFC 1213 / RFC 1759 / RFC 2790 / RFC 3805)
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"               # sysDescr.0
OID_HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3.1"   # hrDeviceDescr.1
OID_SERIAL_EXACT = "1.3.6.1.2.1.43.5.1.1.17.1.1"   # prtGeneralSerialNumber.1.1
OID_SERIAL_BASE = "1.3.6.1.2.1.43.5.1.1.17"        # prtGeneralSerialNumber table
OID_LIFE_COUNT_EXACT = "1.3.6.1.2.1.43.10.2.1.4.1.1" # prtMarkerLifeCount.1.1
OID_LIFE_COUNT_BASE = "1.3.6.1.2.1.43.10.2.1.4"    # prtMarkerLifeCount table
OID_MARKER_SUPPLIES_ENTRY = "1.3.6.1.2.1.43.11.1.1" # prtMarkerSuppliesEntry table

# OIDs de estado y alertas de impresora
OID_HR_PRINTER_ERROR_STATE = "1.3.6.1.2.1.25.3.5.1.2.1" # hrPrinterDetectedErrorState.1
OID_PRT_COVER_STATUS = "1.3.6.1.2.1.43.6.1.1.3"         # prtCoverStatus table
OID_PRT_INPUT_LEVEL = "1.3.6.1.2.1.43.8.2.1.10"         # prtInputCurrentLevel table

# Tipos de suministro definidos en Printer MIB (RFC 3805)
SUPPLY_TYPE_MAP = {
    1: "Otro",
    2: "Desconocido",
    3: "Toner",
    4: "Tinta de chorro",
    5: "Toner/Inkjet",
    6: "Tinta de cera",
    7: "Tinta solida",
    8: "Cinta de tinta",
    9: "Cera",
    10: "Manguera",
    11: "Correa de impresion",
    12: "Miembro de suministro",
    13: "Cartucho de toner",
    14: "Cartucho de tinta de cera",
    15: "Cartucho de tinta solida",
    16: "Cartucho de cinta",
    17: "Cartucho de cera",
    18: "Cartucho de correa",
    19: "Cartucho de miembro de suministro",
    20: "Unidad de tambor",
    21: "Unidad de fusor",
    22: "Pegado",
    23: "Perforador",
    24: "Cartucho de tinta",
    25: "Rollo de tinta",
    26: "Cabezal de impresion",
    27: "Cintas",
    28: "Material de cera",
    29: "Abrazadera de tambor",
    30: "Cepillo de limpieza",
    31: "Pano de limpieza",
    32: "Rodillo de extraccion",
    33: "Engrasador",
    34: "Espatula",
    35: "Interruptor de toner",
    36: "Unidad de recoleccion de toner",
    37: "Unidad intermediaria de transferencia",
    38: "Balde",
    39: "Desfiladero",
    40: "Cartucho de cera solida",
    41: "Cartucho de cera solida (directa)",
    42: "Cinta de tinta (transferencia)",
    43: "Cinta de tinta (directa)",
    44: "Tambor de imagen",
    45: "Variedad de placas",
    46: "Toner libre",
    47: "Toner (contenedor)",
}


def _parse_counter(value):
    """Convierte un valor SNMP a entero de forma segura."""
    if value is None:
        return 0
    try:
        cleaned = str(value).strip().replace(",", "")
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def _oid_to_tuple(oid_str):
    """Convierte un string OID numérico en tupla de enteros."""
    parts = oid_str.strip(".").split(".")
    res = []
    for p in parts:
        if p.isdigit():
            res.append(int(p))
    return tuple(res)


async def _snmp_get(dispatcher, host, oid, community="public", port=161, timeout=2, retries=0):
    """Realiza una consulta SNMP GET y devuelve el valor como cadena limpia."""
    try:
        transport = await UdpTransportTarget.create(
            (host, port), timeout=timeout, retries=retries
        )
        error_indication, error_status, error_index, var_binds = await get_cmd(
            dispatcher,
            CommunityData(community, mpModel=1),
            transport,
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication or error_status:
            return None
        for name, val in var_binds:
            val_str = str(val.prettyPrint()).strip()
            if val_str and "No Such" not in val_str:
                return val_str
    except Exception:
        return None
    return None


async def _snmp_walk(dispatcher, host, base_oid, community="public", port=161, timeout=2, retries=0):
    """Realiza un SNMP WALK sobre base_oid deteniéndose inmediatamente al salir de la tabla."""
    results = []
    base_tuple = _oid_to_tuple(base_oid)
    if not base_tuple:
        return results

    try:
        transport = await UdpTransportTarget.create(
            (host, port), timeout=timeout, retries=retries
        )
        async for error_indication, error_status, error_index, var_binds in walk_cmd(
            dispatcher,
            CommunityData(community, mpModel=1),
            transport,
            ObjectType(ObjectIdentity(base_oid)),
        ):
            if error_indication or error_status:
                break

            should_stop = False
            for name, val in var_binds:
                name_tuple = name.asTuple()
                if len(name_tuple) < len(base_tuple) or name_tuple[:len(base_tuple)] != base_tuple:
                    should_stop = True
                    break

                val_str = str(val.prettyPrint()).strip()
                oid_str = "." + ".".join(str(x) for x in name_tuple)
                results.append((oid_str, val_str))

            if should_stop:
                break
    except Exception:
        pass
    return results


def _calculate_supply_percentage(nivel, maximo):
    """Calcula el porcentaje de un suministro respetando códigos de Printer MIB (RFC 3805)."""
    if nivel == -3:
        return 100
    if nivel in (-2, -11) or nivel < -3:
        return None
    if nivel == -1:
        return 100

    if maximo and maximo > 0 and nivel >= 0:
        pct = round((nivel / maximo) * 100)
        return min(100, max(0, pct))
    
    return None


def _parse_error_state_bits(val_str):
    """Parsea el campo hrPrinterDetectedErrorState (RFC 2790 bitmask)."""
    puerta_abierta = False
    falta_papel = False
    sin_toner = False

    if not val_str:
        return puerta_abierta, falta_papel, sin_toner

    try:
        if val_str.startswith("0x"):
            hex_body = val_str[2:]
            if len(hex_body) % 2 != 0:
                hex_body = "0" + hex_body
            raw_bytes = bytes.fromhex(hex_body)
        else:
            raw_bytes = val_str.encode("latin1", errors="ignore")

        b0 = raw_bytes[0] if len(raw_bytes) > 0 else 0
        b1 = raw_bytes[1] if len(raw_bytes) > 1 else 0

        # Byte 0
        if b0 & 0x40:  # noPaper
            falta_papel = True
        if b0 & 0x10:  # noToner
            sin_toner = True
        if b0 & 0x08:  # doorOpen
            puerta_abierta = True

        # Byte 1
        if b1 & 0x08:  # inputTrayEmpty
            falta_papel = True
        if b1 & 0x20:  # markerSupplyMissing
            sin_toner = True
    except Exception:
        pass

    return puerta_abierta, falta_papel, sin_toner


async def _query_printer_async(host, community="public", port=161, timeout=2):
    """Consulta una impresora de forma asíncrona incluyendo detección de alertas de estado."""
    dispatcher = SnmpDispatcher()

    info = {
        "host": host,
        "modelo": "Desconocido",
        "serie": "Desconocido",
        "contador_total": 0,
        "contador_mono": 0,
        "contador_color": 0,
        "puerta_abierta": False,
        "falta_papel": False,
        "sin_toner": False,
        "puertas": [],
        "bandejas_papel": [],
        "suministros": [],
        "en_linea": False,
    }

    try:
        # Sonda inicial de conectividad
        sys_descr_task = _snmp_get(dispatcher, host, OID_SYS_DESCR, community, port, timeout=min(timeout, 2), retries=0)
        hr_descr_task = _snmp_get(dispatcher, host, OID_HR_DEVICE_DESCR, community, port, timeout=min(timeout, 2), retries=0)
        
        probe_sys, probe_hr = await asyncio.gather(sys_descr_task, hr_descr_task)

        if not probe_sys and not probe_hr:
            return info

        info["en_linea"] = True
        info["modelo"] = probe_hr or probe_sys or "Impresora SNMP"

        if probe_sys and not probe_hr:
            first_line = probe_sys.split("\n")[0].split(";")[0].strip()
            info["modelo"] = first_line if first_line else probe_sys

        # Consultas secundarias paralelas incluyendo alertas
        serial_task = _snmp_get(dispatcher, host, OID_SERIAL_EXACT, community, port, timeout, retries=0)
        serial_walk_task = _snmp_walk(dispatcher, host, OID_SERIAL_BASE, community, port, timeout, retries=0)
        life_exact_task = _snmp_get(dispatcher, host, OID_LIFE_COUNT_EXACT, community, port, timeout, retries=0)
        life_walk_task = _snmp_walk(dispatcher, host, OID_LIFE_COUNT_BASE, community, port, timeout, retries=0)
        supplies_walk_task = _snmp_walk(dispatcher, host, OID_MARKER_SUPPLIES_ENTRY, community, port, timeout, retries=0)
        
        # OIDs de alertas y detalles de puertas y bandejas de papel
        error_state_task = _snmp_get(dispatcher, host, OID_HR_PRINTER_ERROR_STATE, community, port, timeout, retries=0)
        cover_walk_task = _snmp_walk(dispatcher, host, OID_PRT_COVER_STATUS, community, port, timeout, retries=0)
        cover_entry_walk_task = _snmp_walk(dispatcher, host, "1.3.6.1.2.1.43.6.1.1", community, port, timeout, retries=0)
        input_entry_walk_task = _snmp_walk(dispatcher, host, "1.3.6.1.2.1.43.8.2.1", community, port, timeout, retries=0)

        (
            serial_val, serial_walk, life_val, life_walk, supplies_walk,
            error_state_val, cover_walk, cover_entry_walk, input_entry_walk
        ) = await asyncio.gather(
            serial_task, serial_walk_task, life_exact_task, life_walk_task, supplies_walk_task,
            error_state_task, cover_walk_task, cover_entry_walk_task, input_entry_walk_task
        )

        # Número de Serie
        if serial_val:
            info["serie"] = serial_val
        elif serial_walk:
            info["serie"] = serial_walk[0][1]

        # Contadores de páginas
        life_counts = []
        if life_val:
            life_counts.append(_parse_counter(life_val))
        if life_walk:
            for _, v in life_walk:
                c = _parse_counter(v)
                if c > 0 and c not in life_counts:
                    life_counts.append(c)

        if life_counts:
            info["contador_total"] = max(life_counts)
            if len(life_counts) >= 3:
                info["contador_mono"] = life_counts[1]
                info["contador_color"] = life_counts[2]
            elif len(life_counts) == 2:
                info["contador_mono"] = life_counts[0]
                info["contador_color"] = life_counts[1]
            else:
                info["contador_mono"] = info["contador_total"]

        # Procesar tabla unificada de suministros (prtMarkerSuppliesEntry)
        supplies_by_index = {}
        for oid_str, val_str in supplies_walk:
            parts = oid_str.strip(".").split(".")
            if len(parts) >= 13:
                col = parts[-3]
                idx = f"{parts[-2]}.{parts[-1]}"
                if idx not in supplies_by_index:
                    supplies_by_index[idx] = {}
                supplies_by_index[idx][col] = val_str

        for idx in sorted(supplies_by_index.keys()):
            sdata = supplies_by_index[idx]
            desc = sdata.get("6", f"Suministro {idx}")
            tipo_raw = sdata.get("5", "2")
            maximo = _parse_counter(sdata.get("8", "0"))
            nivel = _parse_counter(sdata.get("9", "0"))

            try:
                tipo_int = int(str(tipo_raw).strip())
            except (ValueError, TypeError):
                tipo_int = 2

            tipo_nombre = SUPPLY_TYPE_MAP.get(tipo_int, "Suministro")
            porcentaje = _calculate_supply_percentage(nivel, maximo)

            # Si el nivel de tóner/tinta es 0 o 0%, marcar alerta de sin_toner
            if (nivel == 0 or porcentaje == 0) and tipo_int in (3, 4, 5, 13, 24):
                info["sin_toner"] = True

            info["suministros"].append({
                "descripcion": desc,
                "tipo": tipo_nombre,
                "nivel": nivel,
                "capacidad": maximo,
                "porcentaje": porcentaje,
            })

        # Procesar tabla de Cubiertas / Puertas (prtCoverEntry: 1.3.6.1.2.1.43.6.1.1)
        covers_by_index = {}
        for oid_str, val_str in cover_entry_walk:
            parts = oid_str.strip(".").split(".")
            if len(parts) >= 13:
                col = parts[-3]
                idx = f"{parts[-2]}.{parts[-1]}"
                if idx not in covers_by_index:
                    covers_by_index[idx] = {}
                covers_by_index[idx][col] = val_str

        puertas_list = []
        for idx in sorted(covers_by_index.keys()):
            cdata = covers_by_index[idx]
            nombre = cdata.get("2", f"Puerta/Cubierta {idx}")
            status_code = str(cdata.get("3", "4")).strip()
            
            # 3 = coverOpen, 5 = interlockOpen
            is_open = status_code in ("3", "5")
            if is_open:
                info["puerta_abierta"] = True
                estado_str = "Abierta"
            elif status_code in ("4", "6"):
                estado_str = "Cerrada"
            else:
                estado_str = "Desconocido"

            puertas_list.append({
                "nombre": nombre,
                "estado": estado_str,
                "abierta": is_open
            })
        info["puertas"] = puertas_list

        # Procesar tabla de Bandejas de Papel (prtInputEntry: 1.3.6.1.2.1.43.8.2.1)
        trays_by_index = {}
        for oid_str, val_str in input_entry_walk:
            parts = oid_str.strip(".").split(".")
            if len(parts) >= 13:
                col = parts[-3]
                idx = f"{parts[-2]}.{parts[-1]}"
                if idx not in trays_by_index:
                    trays_by_index[idx] = {}
                trays_by_index[idx][col] = val_str

        bandejas_list = []
        for idx in sorted(trays_by_index.keys()):
            tdata = trays_by_index[idx]
            nombre = tdata.get("13") or tdata.get("12") or f"Bandeja {idx}"
            maximo = _parse_counter(tdata.get("9", "0"))
            nivel = _parse_counter(tdata.get("10", "0"))

            # -3 = atLeastOne, -2 = unknown, 0 = empty
            is_empty = False
            porcentaje = None
            if nivel == 0:
                is_empty = True
                porcentaje = 0
                info["falta_papel"] = True
            elif nivel == -3:
                porcentaje = 100
            elif nivel == -2 or nivel < -3:
                porcentaje = None
            elif maximo > 0 and nivel > 0:
                pct = round((nivel / maximo) * 100)
                porcentaje = min(100, max(0, pct))

            bandejas_list.append({
                "nombre": nombre,
                "capacidad": maximo,
                "nivel": nivel,
                "porcentaje": porcentaje,
                "vacia": is_empty
            })
        info["bandejas_papel"] = bandejas_list

        # Evaluación de Alertas globales (Puerta abierta, Falta papel, Sin tóner)
        p_abierta, f_papel, s_toner = _parse_error_state_bits(error_state_val)
        if p_abierta:
            info["puerta_abierta"] = True
        if f_papel:
            info["falta_papel"] = True
        if s_toner:
            info["sin_toner"] = True

        # Verificar cubierta/puerta abierta vía prtCoverStatus fallback
        if cover_walk:
            for _, cval in cover_walk:
                if str(cval).strip() in ("3", "5"):
                    info["puerta_abierta"] = True

    finally:
        try:
            dispatcher.close()
        except Exception:
            pass

    return info


def query_printer(host, community="public", port=161, timeout=2):
    """Consulta una impresora garantizando un timeout máximo global."""
    hard_timeout = max(3, timeout + 2)
    try:
        return asyncio.run(asyncio.wait_for(_query_printer_async(host, community, port, timeout), timeout=hard_timeout))
    except Exception:
        return {
            "host": host,
            "modelo": "Desconocido",
            "serie": "Desconocido",
            "contador_total": 0,
            "contador_mono": 0,
            "contador_color": 0,
            "puerta_abierta": False,
            "falta_papel": False,
            "sin_toner": False,
            "puertas": [],
            "bandejas_papel": [],
            "suministros": [],
            "en_linea": False,
        }