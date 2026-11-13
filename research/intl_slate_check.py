import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, intl_picks as IP
print("slate:", MS.get_setting("intl_slate"))
