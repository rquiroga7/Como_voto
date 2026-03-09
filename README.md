# ¿Cómo Votó? 🗳️

Visualización interactiva de cómo votan los Diputados y Senadores de la Nación Argentina, y su alineamiento con los principales partidos políticos.

## 🌐 Ver el sitio

👉 **[Abrir ¿Cómo Votó?](https://rquiroga7.github.io/Como_voto/)**

*(Reemplazá TU-USUARIO con tu nombre de usuario de GitHub)*

## 📊 ¿Qué muestra?

- **Buscador** de todos los Diputados y Senadores de la Nación
- **Visualización waffle/grilla** de los votos de cada legislador, agrupados por ley
- **Nombres comunes de leyes** (ej: "Ley Bases", "Reforma Laboral" en vez de títulos formales)
- **Agrupación inteligente**: votos EN GENERAL + EN PARTICULAR de la misma ley se muestran juntos
- **Cruce entre cámaras**: legisladores que fueron Diputados y Senadores aparecen unificados
- **Historial de votos** con filtros por año, tipo de voto y nombre de ley
- **Alineamiento por año** con las coaliciones principales:
  - **PJ** (Partido Justicialista / Frente de Todos / Frente para la Victoria / Unión por la Patria)
  - **PRO** (PRO / Cambiemos / Juntos por el Cambio / UCR)
  - **LLA** (La Libertad Avanza)
- **Gráficos interactivos** de distribución de votos y tendencia de alineamiento
- **Exportar imagen** de la grilla para compartir en redes sociales

## 🏗️ Arquitectura

```
Como_voto/
├── scraper.py           # Script de recolección de datos (HCDN + Senado)
├── generate_site.py     # Procesador: agrupación de leyes, nombres comunes, cruce de cámaras, waffle
├── requirements.txt     # Dependencias Python
├── data/                # Base de datos local (JSON)
│   ├── diputados/       # Detalle de cada votación de Diputados
│   └── senadores/       # Detalle de cada votación de Senadores
├── docs/                # Sitio web (GitHub Pages)
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/            # JSON generados para el frontend
│       ├── stats.json
│       ├── legislators.json
│       ├── votaciones.json
│       ├── law_names.json
│       └── legislators/  # Un archivo por legislador (con datos waffle)
└── .github/workflows/
    └── update-data.yml  # Actualización automática (lun + jue)
```

## 🚀 Uso

### Requisitos

- Python 3.10+
- pip

### Instalación

```bash
pip install -r requirements.txt
```

### Recolectar datos

```bash
# Scrape ambas cámaras
python tools/scraper.py

# Solo Diputados
python tools/scraper.py diputados

# Solo Senadores
python tools/scraper.py senadores
```

El scraper **no vuelve a descargar** votaciones que ya están en `data/`. Solo descarga las nuevas.

### Generar el sitio

```bash
python tools/generate_site.py
```

Esto genera los archivos JSON en `docs/data/` que son consumidos por el frontend.

### Ver localmente

Podés abrir `docs/index.html` directamente en el navegador, o usar un servidor local:

```bash
cd docs
python -m http.server 8000
```

Y visitar `http://localhost:8000`

## 📡 Fuentes de datos

- **Diputados**: [votaciones.hcdn.gob.ar](https://votaciones.hcdn.gob.ar/)
- **Senadores**: [senado.gob.ar/votaciones/actas](https://www.senado.gob.ar/votaciones/actas)

> La información contenida en estos sitios es de dominio público y puede ser utilizada libremente (según las propias fuentes).

## 🔄 Actualización automática

El GitHub Action `update-data.yml` se ejecuta automáticamente dos veces por semana, recolecta nuevas votaciones y actualiza el sitio.

## 📜 Licencia

MIT
