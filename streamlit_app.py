"""Punto de entrada para Streamlit Community Cloud.

Community Cloud ejecuta `streamlit run` desde la raíz del repositorio e instala lo
que hay en `requirements.txt`, pero no el paquete `fantasy` en sí (vive en `src/`).
Este fichero lo hace importable y arranca el dashboard. En local sigue valiendo
`streamlit run src/fantasy/dashboard/app.py` con el paquete instalado.
"""

from pathlib import Path
import runpy
import sys

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

runpy.run_path(str(SRC / "fantasy" / "dashboard" / "app.py"), run_name="__main__")
