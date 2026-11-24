import os
import sys

# Los módulos de Clipeo viven en la raíz del repo (estructura plana).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Las pruebas no registran la identidad de Hypazo en el registro de Windows del PC.
os.environ["HYPAZO_SIN_IDENTIDAD"] = "1"
