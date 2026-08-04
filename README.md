# Playlist Builder

Utilidad interactiva para escanear una discoteca organizada por carpetas, filtrar por artista de
pista, artista de álbum, género y año, y generar una playlist M3U equilibrada. Funciona con
Python 3.12 o posterior en macOS, Windows 11 y Linux.

## Decisiones y compatibilidad

- `mutagen` lee los metadatos sin programas externos. Algunos contenedores o variantes poco
  habituales pueden no exponer todas las etiquetas; se registran como ausentes y el escaneo sigue.
- `prompt_toolkit` gestiona teclas especiales, autocompletado, colores y terminales multiplataforma.
- La identidad de un álbum es la carpeta relativa que lo contiene, no el texto de la etiqueta.
- `Artist` representa al artista de la pista. `AlbumArtist` no se mezcla con él (algo esencial en
  recopilatorios cuyo artista de álbum es `Various Artists`). Para ASF/WMA, `Author` se usa solo como
  fallback cuando no existe `Artist`.
- Por ejemplo, una pista de un recopilatorio con `Artist = The Hoffpauir Family` y
  `AlbumArtist = Various Artists` aparece bajo The Hoffpauir Family en «Artistas de pista» y bajo
  Various Artists únicamente en «Artistas de álbum». Ambos filtros se pueden combinar.
- Los valores múltiples de `Genre` separados por comas, punto y coma o valores nativos independientes
  se convierten en géneros separados; por ejemplo, `Jazz, Contemporary Jazz` permite buscar cualquiera.
- La caché `.playlist_catalog.json` se guarda en la raíz musical, usa rutas relativas y compara
  ruta, tamaño y `mtime_ns`. Su reemplazo es atómico y una caché corrupta se ignora.
- Los M3U usan UTF-8, separadores `/` y saltos de línea LF. Es una combinación entendida por los
  reproductores actuales de los tres sistemas y mantiene portabilidad entre ellos.

No existe una incompatibilidad técnica general con los formatos pedidos, aunque la disponibilidad
real de etiquetas depende de que cada archivo las contenga y de que `mutagen` reconozca esa variante.

## Instalación

### macOS o Linux

```bash
cd playlist_builder
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows 11 (PowerShell)

```powershell
cd playlist_builder
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Configurar la discoteca

Abra `playlist_builder/config.py` y cambie únicamente esta constante por la ruta real:

```python
MUSIC_ROOT = Path(r"/Users/usuario/Música/MiDiscoteca")
```

En Windows, por ejemplo:

```python
MUSIC_ROOT = Path(r"D:\MiDiscoteca")
```

El margen usado cuando solo se indica uno de los años también se configura allí:

```python
DEFAULT_YEAR_MARGIN = 5
DEFAULT_MAX_ARTIST = 0  # 0 significa sin límite
```

## Ejecución

Desde la raíz del proyecto:

```bash
python crear_playlist.py
python crear_playlist.py --size 4000
python crear_playlist.py --size 4000 --max-album 1
python crear_playlist.py --max-artist 3
python crear_playlist.py --audit simple
python crear_playlist.py --audit full --audit-only
python crear_playlist.py --copy "D:\Musica para el coche"
python crear_playlist.py --size 8000 --seed 12345
```

Después de instalar el proyecto en el entorno virtual, también puede usarse:

```bash
crear-playlist --size 4000
```

En Windows está disponible `crear-playlist.cmd`; en macOS/Linux puede hacerse ejecutable el launcher
opcional con `chmod +x crear-playlist.sh`.

### Parámetros

- `--size N`: máximo en MB decimales (`1 MB = 1_000_000 bytes`); acepta decimales y vale 8000 por
  defecto. El resultado nunca supera el límite.
- `--max-album N`: máximo de canciones por carpeta de álbum; vale 2 por defecto.
- `--max-artist N`: máximo de canciones por artista de pista. `0`, un valor vacío o
  `sin límite` desactiva la cuota; está desactivada por defecto.
- `--copy RUTA`: copia las canciones a `RUTA/Music/<ruta original>` y crea allí el M3U.
- `--audit simple|full`: muestra el resumen o también el detalle por archivo y continúa hacia la UI.
- `--audit-only`: muestra la auditoría (simple si no se especificó otra) y termina.
- `--seed N`: hace reproducible la selección si catálogo y filtros no cambian.
- `--rescan`: descarta la caché y relee todos los metadatos.
- `--verbose`: informa sobre caché, lectura y operaciones.
- `--debug`: añade detalles de depuración y deja visibles los tracebacks inesperados.

## Interfaz

En artistas de pista, artistas de álbum y géneros:

- `+` seguido de texto incluye una opción; `-` la excluye.
- La búsqueda encuentra texto en cualquier posición e ignora mayúsculas, acentos, Unicode
  equivalente y espacios repetidos.
- `Tab` y `Shift+Tab` recorren coincidencias. `Enter` acepta la coincidencia exacta o la primera
  sugerida. No admite nombres que no existan en el catálogo.
- `Enter` sobre una línea vacía avanza.
- `Esc` borra la búsqueda parcial; estando vacío, vuelve a la pantalla anterior.
- `Backspace` borra texto y, estando completamente vacío, deshace la última selección confirmada.
- Las inclusiones se muestran en verde y las exclusiones en rojo. Si una opción pasa de un conjunto
  al otro, prevalece la última operación.

Las inclusiones de una misma categoría usan OR: una canción puede coincidir con cualquiera. Artista
de pista, artista de álbum, género y año se combinan con AND. Cualquier exclusión coincidente gana
siempre. Una canción sin tag
puede participar si no hay inclusión positiva para ese tag; sin año queda fuera solo cuando existe
un filtro temporal.

Los años son opcionales e inclusivos. Si se rellena solo un extremo, el otro se calcula con
`DEFAULT_YEAR_MARGIN` y se limita al rango disponible.

Si el nombre del M3U ya existe, la aplicación propone automáticamente `Nombre (2).m3u`, sin
sobrescribirlo. Antes de escribir muestra filtros, candidatas, tamaños y selección prevista, y deja
confirmar, volver o cancelar.

## Selección equilibrada

Las candidatas se agrupan por carpeta de álbum. Las canciones y álbumes se barajan y la selección
avanza por rondas, como máximo una canción por álbum y ronda. Se respeta `--max-album`; si una pista
no cabe se siguen probando pistas más pequeñas. Esto evita depender del orden del sistema de archivos
y no favorece sistemáticamente los primeros artistas.

La cuota opcional `--max-artist` se aplica a cada valor de `Artist`, nunca a `AlbumArtist`. Una
colaboración consume una unidad del cupo de cada artista de pista distinto y no entra si cualquiera
ya alcanzó el máximo. Las pistas omitidas por la cuota no detienen la ronda: se siguen probando otras
del mismo álbum y los álbumes posteriores. El resumen muestra el límite y el número de candidatas
omitidas por él. La cuota no cambia el orden previo ni el resultado reproducible cuando está
desactivada.

## Copia segura

Con `--copy`, primero se copian todas las pistas a una zona temporal mediante `shutil.copy2`. Solo
después se publican en `Music/`, y el M3U se publica el último. Ante un fallo se retiran exclusivamente
los archivos creados por esa operación; nunca se borran archivos preexistentes. Una copia idéntica
se reutiliza y una colisión con contenido distinto recibe un sufijo incremental.

Si el destino se encuentra dentro de la discoteca, se excluye por completo del escaneo de esa
ejecución. Los archivos originales nunca se modifican.

## Auditoría

La auditoría se recopila durante el escaneo normal. `simple` cuenta archivos, tags ausentes y errores.
`full` añade cada ruta, sus tags ausentes y el error concreto. Un archivo corrupto, borrado durante el
escaneo o con metadatos no legibles no detiene el resto.

## Pruebas y calidad

```bash
pytest
ruff check .
ruff format --check .
mypy playlist_builder
```

Los tests usan directorios temporales y lectores simulados: no acceden a la colección real. Cubren
normalización, años, filtros, tags ausentes, selección por rondas, límites, semillas, M3U, caché,
auditoría, colisiones y fallos de copia. Incluyen además regresiones obtenidas de ejemplos MP3 y FLAC
reales con `Artist`/`AlbumArtist`, géneros separados por comas y nombres Unicode descompuestos.

## Solución de problemas

- **La terminal muestra mal colores o teclas:** use Windows Terminal, iTerm2 o una terminal moderna;
  evite ejecutar dentro de una consola sin soporte interactivo. `Ctrl+C` cancela limpiamente.
- **Faltan tags:** ejecute `--audit full --audit-only` y corrija los archivos con un editor de tags.
- **Un formato figura como ilegible:** compruebe que el archivo se reproduce y pruebe `--rescan`.
  Mutagen puede reconocer el contenedor pero no una variante o etiqueta propietaria concreta.
- **Cambió música pero sigue la información anterior:** `--rescan` reconstruye la caché. La detección
  normal ya invalida entradas si cambia tamaño o fecha de modificación.
- **No puede escribir el M3U o copiar:** compruebe permisos sobre `MUSIC_ROOT` o el destino. La
  aplicación muestra la ruta problemática y no publica un M3U incompleto.
- **La reproducción desde otra máquina no encuentra archivos:** una playlist sin `--copy` contiene
  rutas relativas a la discoteca original. Use `--copy` para crear un árbol autocontenido.

## Estructura

```text
playlist_builder/
├── crear_playlist.py
├── pyproject.toml
├── playlist_builder/
│   ├── audit.py, cache.py, cli.py, config.py, copier.py
│   ├── filters.py, m3u.py, metadata.py, models.py
│   ├── normalization.py, scanner.py, selector.py, ui.py
└── tests/
```
