import os
import sys

# Los módulos de Clipeo viven en la raíz del repo (estructura plana).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
