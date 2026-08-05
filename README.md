# Monitor SNMP de Impresoras

Aplicación web (Python + Flask) para consultar el estado de impresoras en red mediante **SNMP v2c** y mostrar:
- **Modelo** de la impresora
- **Número de serie**
- **Contadores de páginas** (total, monocromo, color)
- **Suministros** (tóner/tinta) con niveles, tipo y porcentaje

## Arquitectura

```
mpsi/
├── app.py                 # Backend API Flask (REST)
├── snmp_utils.py          # Utilidades de consulta SNMP (pysnmp)
├── run.py                 # Script de arranque
├── requirements.txt       # Dependencias Python
├── templates/
│   └── index.html         # Frontend (dashboard web)
└── README.md              # Este archivo
```

- **Backend**: Flask expone una API REST en `/api/printers` que consulta las impresoras via SNMP de forma concurrente (threads).
- **Frontend**: Panel web con formulario de IPs, niveles de suministros visuales y auto-refresco cada 60s.

## Requisitos

- Python 3.7+
- Impresoras en red con **SNMP habilitado** (comunidad por defecto: `public`)

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

```bash
python run.py
```

Abrir en el navegador: **http://127.0.0.1:5000**

### Opciones de arranque

```bash
python run.py 192.168.1.10                          # Precarga una IP en el formulario
python run.py -p 8080                               # Cambia el puerto del servidor web
python run.py 192.168.1.10 -p 8080 -c private -t 5  # IP, puerto, comunidad y timeout
```

| Opción | Descripción | Default |
|--------|-------------|---------|
| `host` | IP de impresora a precargar (posicional) | - |
| `-p, --port` | Puerto del servidor web | 5000 |
| `-c, --community` | Comunidad SNMP | public |
| `-t, --timeout` | Timeout SNMP (segundos) | 3 |

## Uso de la API

### Consultar impresoras

```
GET /api/printers?hosts=192.168.1.10,192.168.1.11&community=public&port=161&timeout=3
```

**Respuesta JSON:**

```json
{
  "impresoras": [
    {
      "host": "192.168.1.10",
      "modelo": "HP LaserJet M428",
      "serie": "VNB3R12345",
      "contador_total": 12543,
      "contador_mono": 12543,
      "contador_color": 0,
      "en_linea": true,
      "suministros": [
        {
          "descripcion": "Black Cartridge HP 26A",
          "tipo": "Cartucho de tóner",
          "nivel": 42,
          "capacidad": 100,
          "porcentaje": 42
        }
      ]
    }
  ],
  "errores": []
}
```

### Health check

```
GET /api/health
```

## Notas sobre SNMP

- Se usa **SNMP v2c** con comunidad por defecto `public`.
- Para leer contadores y suministros, la impresora debe tener habilitado SNMP (normalmente en el panel web de la impresora: *Configuración de red → SNMP*).
- OIDs estándar consultados (RFC 3805 / RFC 1759):

| Dato | OID |
|------|-----|
| Modelo | `1.3.6.1.2.1.25.3.2.1.3.1` |
| Serie | `1.3.6.1.2.1.43.5.1.1.17.1` |
| Contador total | `1.3.6.1.2.1.43.10.2.1.4.1.1` |
| Contador mono | `1.3.6.1.2.1.43.10.2.1.4.1.2` |
| Contador color | `1.3.6.1.2.1.43.10.2.1.4.1.3` |
| Descripción suministro | `1.3.6.1.2.1.43.11.1.1.6.1.1` |
| Tipo suministro | `1.3.6.1.2.1.43.11.1.1.5.1.1` |
| Nivel suministro | `1.3.6.1.2.1.43.11.1.1.9.1.1` |
| Capacidad máx. | `1.3.6.1.2.1.43.11.1.1.8.1.1` |

> **Nota**: No todas las impresoras reportan contadores separados mono/color. Si sólo reportan el total, los campos mono/color quedarán en 0.

## Solución de problemas

- **"Sin respuesta"**: Verifica que la impresora esté encendida, tenga SNMP habilitado y que la comunidad sea correcta.
- **Timeout**: Aumenta el timeout en el formulario o con la opción `-t`.
- **Puerto bloqueado**: El firewall debe permitir el tráfico UDP 161 desde el equipo donde corre la app.