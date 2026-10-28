"""requirements.txt (lo que instala Streamlit Cloud) no puede desviarse de pyproject.toml."""

from pathlib import Path
import tomllib

RAIZ = Path(__file__).resolve().parent.parent


def test_requirements_coincide_con_pyproject():
    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    esperadas = set(pyproject["project"]["dependencies"])
    lineas = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    actuales = {l.strip() for l in lineas if l.strip() and not l.lstrip().startswith("#")}
    assert actuales == esperadas
