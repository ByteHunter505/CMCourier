# Windows vs Linux: portabilidad real, no aspiracional

> [← Volver al índice](../INDEX.md) · [Explanation](README.md)

## El problema que estamos resolviendo

CMCourier corre en **dos entornos productivos**:

1. **Linux** — los servidores de batch nocturno, donde corren las migraciones masivas. Pueden ser AlmaLinux corporativo o RHEL del banco.
2. **Windows Server** — donde típicamente vive el iSeries Access ODBC Driver de IBM (el driver oficial para AS400 está soportado en Windows; el driver Linux es second-class citizen).

Los desarrolladores trabajan en **macOS** o **Linux** localmente. Las staging environments suelen ser Linux. Pero la **producción es Windows Server con frecuencia** porque el banco licenció el iSeries Access ahí.

Esto significa que el código tiene que funcionar **realmente** en los dos. No "técnicamente compatible" — funcionar. Esta explicación documenta qué fue intencional, qué funciona out-of-the-box, y dónde están las trampas.

## Lo que fue diseñado pensando en Windows

### 1. `spawn` en lugar de `fork` para procesos

Spec 066 introduce `ProcessPoolExecutor` para S4. Forzamos explícitamente `multiprocessing.get_context("spawn")`:

```python
spawn_ctx = multiprocessing.get_context("spawn")
pool = ProcessPoolExecutor(..., mp_context=spawn_ctx)
```

¿Por qué importa esto para Windows?

- **`fork` no existe en Windows**. Windows no implementa `fork()` syscall — solo `CreateProcess`. Si dejáramos el default de Linux (`fork`), el código fallaría duro en Windows.
- **`spawn` es el default histórico en Windows**. Al forzarlo en todos los platforms, el comportamiento es **idéntico** Linux/Windows. Cero divergencia, cero "funciona en mi máquina pero no en la del cliente".
- **`fork` ya está siendo deprecado en Linux también** por el bug del multi-threaded parent (Python 3.12 emite warning, Python 3.14 cambia default a `forkserver`). Forzar `spawn` ahora nos saca de esa transición.

Ver [`processpool-for-pdf-assembly.md`](processpool-for-pdf-assembly.md) para el racional completo.

### 2. Path handling con `pathlib`

Todo el código de paths usa `pathlib.Path`, **no string concatenation**. Eso no es estético — es correctitud:

```python
# ✓ BIEN — pathlib normaliza separators según el OS
source = Path(config.assembly.source_root) / abaicd / abajcd / filename

# ⛔ MAL — hardcodea forward slash
source = f"{source_root}/{abaicd}/{abajcd}/{filename}"
```

`Path` en Linux usa `/`, en Windows usa `\\`. Cuando hacés `Path("a/b/c")` y serializás a string, en Linux te da `a/b/c`, en Windows te da `a\\b\\c`. Los syscalls del kernel reciben lo que cada uno espera.

La regla: **si el código manipula filesystem paths, usa `Path`**. Si necesitás string para algo (un log, un YAML serializado), usa `str(path)` al final.

### 3. Encoding explícito al leer archivos

CSV, YAML, todos los archivos de texto se abren con encoding explícito:

```python
with open(path, encoding="utf-8") as f:
    ...
```

En Linux el default es `utf-8` (en sistemas razonables). En Windows el default es `cp1252` (Latin-1 extendido). Si dependieras del default, en Windows un YAML con acentos en español rompería. Encoding explícito lo blinda.

### 4. La capa de tracking store usa SQLite

Elegir SQLite (en lugar de PostgreSQL o MySQL como tracking store) tiene una razón operativa concreta: **es archivo único, no requiere daemon, funciona idéntico en los dos OS**. WAL mode funciona en los dos. El driver `sqlite3` viene en la stdlib de Python — cero dependencias platform-specific.

Si hubiéramos elegido PostgreSQL, tendríamos que gestionar el daemon en cada OS, lidiar con permisos, abrir puertos, manejar instalaciones distintas. Spec 007 (SQLite tracking store) eligió esto deliberadamente.

## Lo que funciona out-of-the-box en los dos

### `httpx[http2]`

`httpx` es puro Python con dependencias en `h2` (HTTP/2 codec) y `httpcore` (transport). Las dependencias compilan wheels para Windows y Linux. La librería funciona idéntica.

El único caveat: en Windows hay una idiosincrasia con sockets aborted que devuelve **WinError 10053**. El `CmisUploader` lo detecta y lo trata como 5xx retryable (`_WINDOWS_ABORT_MARKER = "10053"`). Ver [`idempotency-and-retries.md`](idempotency-and-retries.md) para detalle.

### `pyodbc` + iSeries Access

Acá hay matices:

- **Windows**: el driver oficial de IBM (iSeries Access ODBC Driver) se instala vía instalador MSI. Aparece en el registry como un ODBC DSN. `pyodbc` lo encuentra por nombre o por driver string.
- **Linux**: hay un driver Linux de IBM (Access Client Solutions for Linux) pero requiere `unixODBC` por debajo. La instalación es más artesanal — copiar `.rpm`/`.deb`, registrar el driver en `/etc/odbcinst.ini`, configurar `LD_LIBRARY_PATH`.

Para CMCourier el código es **idéntico** en los dos casos:

```python
import pyodbc
conn = pyodbc.connect(connection_string)  # mismo código, distinto driver detrás
```

La diferencia está en el `connection_string` y la instalación del driver, no en el código Python. Esto vive en `adapters/sources/as400.py`. Si querés correr CMCourier contra AS400 desde Linux, el README del runbook tiene los pasos para `unixODBC` — separados del código.

### Pillow / img2pdf / PyPDF2

Las tres librerías de PDF tienen wheels precompilados para Windows y Linux. Cero compilación local. Las versiones que usamos (Pillow >= 10, PyPDF2 >= 3, img2pdf >= 0.5) son cross-platform por diseño.

### psutil

Para system metrics (Tier 5). Tiene implementaciones cross-platform. Lo único distinto entre OS son las métricas que **no existen** en uno u otro (process I/O counters tienen shape diferente), pero `psutil` los normaliza con campos que pueden ser `None` o `0` cuando no aplica.

## Los caveats reales

### Shell scripts en `scripts/staging/`

Hay scripts bash en `scripts/staging/`:

- `wipe-alfresco-docs.sh`
- `wipe-local-state.sh`
- `alfresco-purge-watchdog.sh`

Esos **son bash**. En Windows necesitás correrlos vía:

- **WSL** (Windows Subsystem for Linux) — la opción moderna.
- **Git Bash** que viene con Git for Windows — viable para scripts simples, no para los que usan herramientas Unix complejas.
- Convertir manualmente a PowerShell — el approach más invasivo.

Estos scripts son **utilitarios operativos**, no son parte del runtime de CMCourier. Si tu pipeline productivo es Windows-only y querés purgar Alfresco staging, podés:

1. Tener una VM Linux dedicada para estas tareas operativas.
2. Reescribirlos a PowerShell (PRs welcome).
3. Correrlos vía WSL.

Lo importante: **el `cmcourier` runtime no depende de bash**. Solo estos scripts auxiliares.

### Logs en `./logs/` con paths absolutos

`logs/` se crea bajo el cwd. En Windows con `cmd.exe`, el cwd puede ser `C:\Users\admin\Documents` y los logs aparecen ahí. En Linux con bash, en `/opt/cmcourier` o donde sea. El comportamiento es el mismo — el cwd-relative path se respeta — pero **el operador tiene que saber dónde está parado** al lanzar `cmcourier`.

Recomendación operativa: siempre lanzar `cmcourier` desde un cwd controlado (un directorio de runtime dedicado), no desde `Documents` o `Desktop`.

### File locks en SQLite

SQLite en WAL mode funciona igual en los dos OS, pero el comportamiento de **locks de archivo** difiere:

- En Linux, `flock()` y advisory locks son cooperativos. Si un proceso muere, el lock se libera automáticamente.
- En Windows, los locks son mandatory (a nivel del kernel). Si un proceso muere abruptamente sin cerrar SQLite, el archivo puede quedar en estado donde otro proceso no puede abrirlo hasta que el OS limpie.

Mitigation: el tracking store cierra explícitamente en `try/finally` con `tracking_store.close()`. Spec 007 también incluye `PRAGMA journal_mode=WAL` que reduce la duración de los locks. En la práctica esto raramente da problemas, pero si una corrida se cae con SIGKILL en Windows y el siguiente `cmcourier` no puede abrir el SQLite, sabés por qué — esperá unos segundos o reiniciá el server (el OS limpia los handles).

### Symlinks

Pre-Python-3.8 había issues con symlinks en Windows que requerían admin privileges. Post-3.8 no, pero algunos environments corporativos los deshabilitan. CMCourier **no usa symlinks** en ningún lado — todos los paths son archivos reales o directorios. Eso evita el problema.

### Line endings

Git tiene `core.autocrlf` que en Windows convierte LF a CRLF al checkout. Para archivos `.py` esto generalmente no es problema (Python parsea los dos), pero para archivos de fixture (CSV, YAML) puede ser. Recomendamos `.gitattributes` con `* text=auto eol=lf` para forzar LF en todo el repo — eso vive en el repo y se aplica al checkout.

## ¿Qué hace CMCourier para detectar el OS?

Casi nada. La arquitectura está diseñada para que el platform sea **transparente**:

- `Path` se ocupa de los separators.
- `pyodbc` resuelve el driver correcto según el `connection_string`.
- `multiprocessing.get_context("spawn")` se comporta igual en los dos.
- `httpx` es puro Python.

El único `sys.platform` check que existe en el codebase es **defensivo en el `CmisUploader`**:

```python
_WINDOWS_ABORT_MARKER = "10053"
# ...
if _WINDOWS_ABORT_MARKER in str(exc):
    # tratar como 5xx con sleep duplicado
```

Eso no es un branch "si es Windows hacé X" — es "si ves este mensaje específico (que solo Windows emite), aplicale esta heurística". El código corre idéntico en Linux; simplemente nunca matchea porque Linux no emite ese mensaje.

## La pirámide de portabilidad

| Capa | Estado |
|------|--------|
| Lenguaje (Python 3.11+) | Idéntico ambos OS |
| Dependencies puras Python (pydantic, click, pyyaml) | Idéntico |
| Dependencies con wheels (Pillow, img2pdf, PyPDF2, httpx, h2) | Idéntico, wheels precompilados |
| Dependencies platform-specific (pyodbc + iSeries driver) | Driver distinto, código idéntico |
| Process model (`spawn`) | Forzado idéntico |
| Filesystem (`pathlib`) | Idéntico, separators handled |
| Network (`httpx`) | Idéntico, 10053 manejado |
| Shell tooling (`scripts/staging/`) | Linux/WSL only |

## Recomendación operativa

Si te toca elegir donde correr CMCourier en producción:

- **Linux con AS400 vía iSeries Access for Linux**: viable, requiere setup de `unixODBC` y posible licensing check con IBM. La performance de pyodbc en Linux es comparable a Windows.
- **Windows Server con iSeries Access nativo**: el camino "tradicional" del banco. Funciona perfecto.
- **Hybrid (Linux para CMCourier, Windows para AS400 server)**: la red entre ambos es lo único que importa. Si la VPN/firewall corporativo permite la ruta, funciona.

CMCourier no tiene preferencia. Las dos opciones están testeadas en staging. La decisión es operativa (donde está la licencia de iSeries Access, donde tiene infra el banco).

## Lo que NO probamos

- **macOS productivo**. macOS es supported para desarrollo (dependencies todas tienen wheels, `spawn` es default). Pero no testeamos contra AS400 desde macOS — el driver IBM no tiene soporte mac oficial. Si vas a correr CMCourier en mac, asumí que es solo para `csv-trigger-pipeline` contra CSVs locales, no contra AS400 real.

- **Arquitecturas ARM**. Linux ARM (Raspberry Pi, ARM cloud servers) tiene wheels para la mayoría de dependencies pero no para todas las versiones que pinneamos. Si te toca correr en ARM, esperá compilación local de algunas wheels.

- **Python 3.11 en Windows 7**. La constitución pide Python 3.11+. Windows 7 no soporta Python 3.10+. Si tu infra es Windows 7, primero actualizá el OS.

## Resumen

CMCourier es **realmente portable** entre Linux y Windows porque la decisión arquitectónica se tomó desde el día uno. No es retrofit — es diseño. Los caveats son:

- **El driver de AS400** se instala distinto pero el código es idéntico.
- **Los shell scripts** son bash, requieren WSL/Git Bash en Windows. No son parte del runtime.
- **El cwd-relative `./logs/`** requiere que el operador lance desde un cwd controlado.

Para el resto, el código funciona. No hay sorpresas.

## Ver también

- [`processpool-for-pdf-assembly.md`](processpool-for-pdf-assembly.md) — por qué `spawn` en lugar de `fork` y qué nos compra eso para Windows
- [`idempotency-and-retries.md`](idempotency-and-retries.md) — el manejo especial de Windows 10053
- [`architecture-overview.md`](architecture-overview.md) — la arquitectura que hace que el adapter de AS400 sea pluggable
- `src/cmcourier/adapters/sources/as400.py` — el adapter de AS400 con pyodbc
- `scripts/staging/` — los scripts bash auxiliares
