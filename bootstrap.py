import sys

from . import mock_cloud

ha_cloud_module = type(sys)("cloud")
sys.modules["homeassistant.components.cloud"] = ha_cloud_module

for key in mock_cloud.__dict__:
    if not key.startswith("_"):
        setattr(ha_cloud_module, key, getattr(mock_cloud, key))
